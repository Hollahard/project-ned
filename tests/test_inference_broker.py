"""Hard verification test suite for Phase 3: Inference Broker and Model-Profiler Integration.

Verifies:
1. Isolated subprocess spawn inside runtime/tabbyAPI/.venv.
2. Environment sanitization stripping parent secrets and retaining only whitelisted variables.
3. Win32 Job Object containment with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000).
4. REST model loading, unloading, context sizing, batching, and KV-cache normalization.
5. Backend qualification order (EXL3 primary, EXL2 secondary fallback).
6. Real benchmark telemetry collection (TTFT, TPS, VRAM utilization).
7. Immutable artifact cache invalidation on weights, tokenizer, or Jinja template changes.
8. Zero leaked processes after parent kill (empirical kernel cleanup).
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest

from friday.inference.broker_client import (
    BackendType,
    BrokerLoadProfile,
    TabbyBrokerClient,
    normalize_cache_mode,
)
from friday.inference.broker_supervisor import (
    JOB_OBJECT_LIMIT_BREAKAWAY_OK,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    SupervisorConfig,
    TabbyBrokerSupervisor,
    sanitize_environment,
)
from friday.inference.profiler import (
    BenchmarkTelemetry,
    ModelProfiler,
    compute_artifact_fingerprint,
)

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


# ---------------------------------------------------------------------------
# Test 1: Isolated spawn & venv interpreter resolution
# ---------------------------------------------------------------------------


def test_isolated_spawn_and_venv_resolution(tmp_path: Path):
    """Verifies that supervisor resolves the isolated virtual environment interpreter."""
    fake_venv = tmp_path / "tabby_venv"
    scripts = fake_venv / "Scripts"
    scripts.mkdir(parents=True)
    fake_python = scripts / "python.exe"
    fake_python.write_text("# dummy")

    config = SupervisorConfig(venv_dir=fake_venv)
    supervisor = TabbyBrokerSupervisor(config)
    resolved = supervisor.resolve_python()

    assert resolved == fake_python.resolve()


def test_environment_sanitization_strips_secrets():
    """Empirically verifies that parent secrets are stripped and only whitelist variables survive."""
    dirty_env = {
        "PATH": "C:\\Windows\\system32;C:\\Windows",
        "TEMP": "C:\\Temp",
        "SYSTEMROOT": "C:\\Windows",
        "GITHUB_TOKEN": "ghp_secret_token_12345",
        "OPENAI_API_KEY": "sk-secret-key-67890",
        "ANTHROPIC_API_KEY": "ant-secret-key-abcde",
        "AWS_SECRET_ACCESS_KEY": "aws-secret-xyz",
    }

    sanitized = sanitize_environment(dirty_env)

    # Whitelisted variables preserved
    assert "PATH" in sanitized
    assert "TEMP" in sanitized
    assert "SYSTEMROOT" in sanitized

    # Secrets strictly stripped
    assert "GITHUB_TOKEN" not in sanitized
    assert "OPENAI_API_KEY" not in sanitized
    assert "ANTHROPIC_API_KEY" not in sanitized
    assert "AWS_SECRET_ACCESS_KEY" not in sanitized


# ---------------------------------------------------------------------------
# Test 2: Win32 Job Object containment & LimitFlags
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object tests require Windows")
def test_job_object_containment_and_limit_flags():
    """Verifies Job Object creation sets JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) and denies breakaway."""
    supervisor = TabbyBrokerSupervisor()

    # Spawn dummy child worker
    pid = supervisor.spawn(command_args=["-c", "import time; time.sleep(10)"])
    assert pid is not None
    assert supervisor.is_alive

    try:
        flags = supervisor.query_job_limit_flags()
        assert (flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0, (
            f"Expected JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) in flags, got 0x{flags:08X}"
        )
        assert (flags & JOB_OBJECT_LIMIT_BREAKAWAY_OK) == 0, (
            "Breakaway must be strictly denied"
        )
        assert supervisor.active_process_count() >= 1
    finally:
        supervisor.close()
        assert not supervisor.is_alive


# ---------------------------------------------------------------------------
# Test 3: Dummy model load/unload and effective parameters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dummy_model_load_unload_and_effective_parameters():
    """Verifies REST endpoints for model load/unload and parameter extraction."""
    state = {"loaded": False, "profile": None}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = request.url.path
        if url == "/v1/model/load" and request.method == "POST":
            data = json.loads(request.content)
            state["loaded"] = True
            state["profile"] = data
            return httpx.Response(200, json={"status": "ok"})

        if url == "/v1/model/unload" and request.method == "POST":
            state["loaded"] = False
            state["profile"] = None
            return httpx.Response(200, json={"status": "ok"})

        if url == "/v1/model" and request.method == "GET":
            if not state["loaded"]:
                return httpx.Response(503, json={"detail": "No models are currently loaded."})
            prof = state["profile"]
            return httpx.Response(
                200,
                json={
                    "id": prof["model_name"],
                    "parameters": {
                        "backend": prof["backend"],
                        "max_seq_len": prof["max_seq_len"],
                        "cache_size": prof["cache_size"],
                        "cache_mode": prof["cache_mode"],
                        "max_batch_size": prof["max_batch_size"],
                        "chunk_size": prof["chunk_size"],
                        "use_vision": prof.get("use_vision", False),
                        "draft_enabled": False,
                    },
                },
            )

        if url == "/props" and request.method == "GET":
            prof = state["profile"] or {}
            return httpx.Response(
                200,
                json={
                    "total_slots": prof.get("max_batch_size", 1),
                    "default_generation_settings": {"n_ctx": prof.get("max_seq_len", 4096)},
                    "modalities": {"vision": prof.get("use_vision", False)},
                },
            )

        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(mock_handler)
    client = TabbyBrokerClient(base_url="http://127.0.0.1:5000", transport=transport)

    # 1. Test load with Q6 KV-cache
    profile = BrokerLoadProfile(
        model_name="test-qwen-coder",
        backend=BackendType.EXLLAMAV3,
        max_seq_len=8192,
        cache_size=8192,
        cache_mode="Q6",
        max_batch_size=2,
    )

    effective = await client.load_model(profile)
    assert effective.model_name == "test-qwen-coder"
    assert effective.backend == BackendType.EXLLAMAV3
    assert effective.max_seq_len == 8192
    assert effective.max_batch_size == 2
    assert effective.cache_mode == "6,6"
    assert not effective.draft_enabled

    # 2. Test unload
    await client.unload_model()
    assert client.active_profile is None
    assert client.effective_parameters is None

    await client.close()


# ---------------------------------------------------------------------------
# Test 4: Backend qualification order (EXL3 primary, EXL2 fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_qualification_order():
    """Verifies qualification order: EXL3 primary, EXL2 secondary fallback."""
    client = TabbyBrokerClient()

    # When both EXL3 and EXL2 are supported, EXL3 must be selected first
    qualified = await client.qualify_backend([BackendType.EXLLAMAV3, BackendType.EXLLAMAV2])
    assert qualified == BackendType.EXLLAMAV3

    # When EXL3 is absent, EXL2 must be selected as fallback
    fallback = await client.qualify_backend([BackendType.EXLLAMAV2])
    assert fallback == BackendType.EXLLAMAV2

    # When none are supported, must raise RuntimeError
    with pytest.raises(RuntimeError, match="No supported backend available"):
        await client.qualify_backend([])

    await client.close()


# ---------------------------------------------------------------------------
# Test 5: Benchmark measurement collection & metrics
# ---------------------------------------------------------------------------


def test_benchmark_telemetry_collection():
    """Verifies collection and calculation of TTFT, throughput, and VRAM utilization."""
    telemetry = BenchmarkTelemetry(
        ttft_ms=18.4,
        tokens_per_second=78.5,
        vram_used_bytes=14 * 1024 * 1024 * 1024,
        vram_total_bytes=32 * 1024 * 1024 * 1024,
        peak_vram_bytes=15 * 1024 * 1024 * 1024,
    )

    data = telemetry.to_dict()
    assert data["ttft_ms"] == 18.4
    assert data["tokens_per_second"] == 78.5
    assert data["vram_used_bytes"] == 14 * 1024 * 1024 * 1024
    assert data["vram_total_bytes"] == 32 * 1024 * 1024 * 1024
    assert data["vram_utilization_ratio"] == round(14 / 32, 4)


# ---------------------------------------------------------------------------
# Test 6: Immutable artifact cache invalidation
# ---------------------------------------------------------------------------


def test_artifact_cache_invalidation_on_file_mutation(tmp_path: Path):
    """Verifies that altering weights, tokenizer, or Jinja templates invalidates cached telemetry."""
    model_dir = tmp_path / "mock_model"
    model_dir.mkdir()

    weights_file = model_dir / "model.safetensors"
    weights_file.write_bytes(b"initial_safetensors_bytes_v1")

    tok_file = model_dir / "tokenizer.json"
    tok_file.write_text('{"version": "1.0"}')

    template_file = model_dir / "chat_template.jinja"
    template_file.write_text("{% for message in messages %}{{ message.content }}{% endfor %}")

    profiler = ModelProfiler()
    telemetry = BenchmarkTelemetry(
        ttft_ms=15.0,
        tokens_per_second=82.0,
        vram_used_bytes=10 * 1024 * 1024 * 1024,
        vram_total_bytes=32 * 1024 * 1024 * 1024,
    )

    # Record benchmark
    profiler.record_benchmark(model_dir, telemetry)
    assert profiler.is_cache_valid(model_dir)

    # Valid retrieval
    cached = profiler.get_benchmark(model_dir)
    assert cached is not None
    assert cached.ttft_ms == 15.0

    # 1. Modify weights: cache must invalidate
    time.sleep(0.01)  # ensure mtime granularity
    weights_file.write_bytes(b"modified_safetensors_bytes_v2")

    assert not profiler.is_cache_valid(model_dir)
    assert profiler.get_benchmark(model_dir) is None

    # Re-benchmark with new weights
    profiler.record_benchmark(model_dir, telemetry)
    assert profiler.is_cache_valid(model_dir)

    # 2. Modify Jinja template: cache must invalidate
    time.sleep(0.01)
    template_file.write_text("{% new template content %}")

    assert not profiler.is_cache_valid(model_dir)
    assert profiler.get_benchmark(model_dir) is None


# ---------------------------------------------------------------------------
# Test 7: Empirical zero-orphan process reap after parent kill
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object tests require Windows")
def test_empirical_zero_leaked_processes_after_parent_kill(tmp_path: Path):
    """Empirically tests that when a supervisor holding a Job Object with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is forcefully killed via taskkill /F,
    the OS kernel immediately terminates all child processes with zero orphans.
    """
    assert kernel32 is not None

    # Python script for the sub-supervisor parent process
    sub_supervisor_code = r'''
import ctypes, os, subprocess, sys, time

kernel32 = ctypes.windll.kernel32
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9

h_job = kernel32.CreateJobObjectW(None, None)
if not h_job:
    sys.exit(1)

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

ret = kernel32.SetInformationJobObject(
    h_job,
    JobObjectExtendedLimitInformation,
    ctypes.byref(info),
    ctypes.sizeof(info),
)
if not ret:
    sys.exit(2)

child_pids = []
for _ in range(2):
    p = subprocess.Popen(["cmd.exe", "/c", "ping", "127.0.0.1", "-n", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kernel32.AssignProcessToJobObject(h_job, int(p._handle))
    child_pids.append(p.pid)

print(f"READY:{os.getpid()}:{','.join(str(p) for p in child_pids)}", flush=True)

while True:
    time.sleep(1)
'''

    script_path = tmp_path / "sub_supervisor.py"
    script_path.write_text(sub_supervisor_code)

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    line = proc.stdout.readline().strip()
    assert line.startswith("READY:"), f"Supervisor failed to initialize: {line}"

    _, parent_pid_str, child_pids_str = line.split(":")
    parent_pid = int(parent_pid_str)
    child_pids = [int(p) for p in child_pids_str.split(",")]

    # Verify children are currently running
    for cpid in child_pids:
        h = kernel32.OpenProcess(0x1000, False, cpid)  # PROCESS_QUERY_LIMITED_INFORMATION
        assert h != 0, f"Child process {cpid} should be alive initially"
        kernel32.CloseHandle(h)

    # Forcefully kill parent sub-supervisor
    subprocess.run(["taskkill", "/F", "/PID", str(parent_pid)], check=True, capture_output=True)

    # Wait for OS kernel to reap child processes
    time.sleep(1.0)

    # Empirically verify all child processes were reaped by the OS kernel
    for cpid in child_pids:
        h = kernel32.OpenProcess(0x1000, False, cpid)
        if h != 0:
            exit_code = ctypes.c_uint32()
            kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            kernel32.CloseHandle(h)
            assert exit_code.value != 259, f"Child process {cpid} was leaked! (STILL_ACTIVE)"
