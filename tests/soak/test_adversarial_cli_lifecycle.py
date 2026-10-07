"""Adversarial Verification Suite for Milestone 3 CLI Modes and Process Lifecycle.

Tests:
1. CLI parsing stress testing (smoke, gate, release, custom, aliases, overrides, edge cases).
2. Win32 Job Object limits: enforce KILL_ON_JOB_CLOSE, strictly omit ACTIVE_PROCESS (ActiveProcessLimit == 0).
3. Multi-worker concurrency under Job Object (5 concurrent ping.exe workers).
4. Process teardown and zero orphan enforcement (tasklist findstr ping.exe returns 1).
5. Lifecycle across target modes: mock, spawn, attach.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

# Ensure services/core/src and project root are on sys.path
project_root = Path(__file__).resolve().parents[2]
core_src = project_root / "services" / "core" / "src"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(core_src) not in sys.path:
    sys.path.insert(0, str(core_src))

from tests.soak.run_8hr_soak import (
    GracefulShutdownCoordinator,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JobObjectExtendedLimitInformation,
    SoakRunnerConfig,
    StandaloneSoakRunner,
    Win32JobSupervisor,
    kernel32,
    parse_soak_cli_args,
)

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008


# ==============================================================================
# 1. CLI Parsing Stress Tests
# ==============================================================================


@pytest.mark.parametrize(
    "mode_arg,expected_mode,expected_duration_s,expected_warmup_s,expected_interval_s",
    [
        ("smoke", "smoke", 15.0 * 60.0, 3.0 * 60.0, 10.0),
        ("15m", "smoke", 15.0 * 60.0, 3.0 * 60.0, 10.0),
        ("gate", "gate", 60.0 * 60.0, 15.0 * 60.0, 15.0),
        ("1h", "gate", 60.0 * 60.0, 15.0 * 60.0, 15.0),
        ("release", "release", 8.0 * 3600.0, 15.0 * 60.0, 60.0),
        ("8h", "release", 8.0 * 3600.0, 15.0 * 60.0, 60.0),
    ],
)
def test_cli_standard_modes_and_aliases(
    mode_arg: str,
    expected_mode: str,
    expected_duration_s: float,
    expected_warmup_s: float,
    expected_interval_s: float,
):
    """Verify that all standard modes and aliases parse with exact duration, warmup, and interval specs."""
    cfg = parse_soak_cli_args(["--mode", mode_arg])
    assert cfg.mode == expected_mode
    assert cfg.duration_seconds == expected_duration_s
    assert cfg.warmup_seconds == expected_warmup_s
    assert cfg.sample_interval_seconds == expected_interval_s


def test_cli_custom_duration_scalings():
    """Verify custom duration scalings: warmup is 20% capped at 15m, interval scaled between 1s and 10s."""
    # Short custom duration: 30s (0.5m) -> warmup=6s (20%), interval=1.0s
    cfg_short = parse_soak_cli_args(["--mode", "custom", "--duration-minutes", "0.5"])
    assert cfg_short.mode == "custom"
    assert cfg_short.duration_seconds == 30.0
    assert cfg_short.warmup_seconds == 6.0
    assert cfg_short.sample_interval_seconds == 1.0

    # Medium custom duration: 100m -> duration=6000s, warmup=min(900, 1200)=900s, interval=min(10, 120)=10s
    cfg_med = parse_soak_cli_args(["--duration-minutes", "100"])
    assert cfg_med.mode == "custom"
    assert cfg_med.duration_seconds == 6000.0
    assert cfg_med.warmup_seconds == 900.0
    assert cfg_med.sample_interval_seconds == 10.0


def test_cli_explicit_overrides_and_edge_cases():
    """Verify explicit flag overrides and boundary handling."""
    # Warmup minutes override
    cfg1 = parse_soak_cli_args(["--mode", "smoke", "--warmup-minutes", "5.5"])
    assert cfg1.warmup_seconds == 5.5 * 60.0

    # Negative warmup clamped to 0.0
    cfg2 = parse_soak_cli_args(["--mode", "gate", "--warmup-minutes", "-10"])
    assert cfg2.warmup_seconds == 0.0

    # Explicit sample interval override
    cfg3 = parse_soak_cli_args(["--mode", "release", "--sample-interval-seconds", "5.0"])
    assert cfg3.sample_interval_seconds == 5.0

    # Overriding duration overrides mode to custom
    cfg4 = parse_soak_cli_args(["--mode", "release", "--duration-minutes", "12"])
    assert cfg4.mode == "custom"
    assert cfg4.duration_seconds == 12 * 60.0


def test_cli_invalid_mode_rejected():
    """Verify invalid mode argument is rejected by argparse."""
    with pytest.raises(SystemExit):
        parse_soak_cli_args(["--mode", "nonexistent_mode"])


def test_cli_target_modes_parsing():
    """Verify target mode flags and attached PIDs parse cleanly."""
    for tm in ["mock", "spawn", "attach"]:
        cfg = parse_soak_cli_args(["--target-mode", tm])
        assert cfg.target_mode == tm

    cfg_attach = parse_soak_cli_args([
        "--target-mode", "attach",
        "--core-pid", "1234",
        "--tabby-pid", "5678",
        "--supervisor-pid", "9012",
    ])
    assert cfg_attach.core_pid == 1234
    assert cfg_attach.tabby_pid == 5678
    assert cfg_attach.supervisor_pid == 9012


# ==============================================================================
# 2. Process Lifecycle & Job Object Limit Tests
# ==============================================================================


def test_job_supervisor_enforces_kill_on_close_and_omits_active_process_limit():
    """Empirically query Win32 Job Object limit information to verify:
    1. JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is enabled (0x2000).
    2. JOB_OBJECT_LIMIT_ACTIVE_PROCESS is strictly omitted (0x0008 NOT set).
    3. ActiveProcessLimit == 0 (unlimited worker processes allowed).
    """
    if sys.platform != "win32" or kernel32 is None:
        pytest.skip("Windows platform required for Win32 Job Object test")

    supervisor = Win32JobSupervisor()
    assert supervisor._handle is not None, "Failed to create Win32 Job Object"

    try:
        ext_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ret_len = ctypes.c_ulong(0)
        res = kernel32.QueryInformationJobObject(
            supervisor._handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(ext_info),
            ctypes.sizeof(ext_info),
            ctypes.byref(ret_len),
        )
        assert res != 0, f"QueryInformationJobObject failed: {kernel32.GetLastError()}"

        flags = ext_info.BasicLimitInformation.LimitFlags
        active_limit = ext_info.BasicLimitInformation.ActiveProcessLimit

        # Assert KILL_ON_JOB_CLOSE is enabled
        assert (flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0, (
            f"Expected JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000), got flags 0x{flags:08X}"
        )

        # Assert ACTIVE_PROCESS limit is NOT set
        assert (flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS) == 0, (
            f"JOB_OBJECT_LIMIT_ACTIVE_PROCESS (0x0008) must NOT be set, got flags 0x{flags:08X}"
        )

        # Assert ActiveProcessLimit == 0
        assert active_limit == 0, f"ActiveProcessLimit must be 0, got {active_limit}"

    finally:
        supervisor.close()


def test_job_supervisor_multi_worker_concurrency_and_orphan_cleanup():
    """Empirically verify that Win32JobSupervisor:
    1. Concurrently supports 5 child processes (cmd.exe /c ping 127.0.0.1 -n 30).
    2. Reports active processes >= 5.
    3. Upon supervisor.close(), terminates all 5 processes cleanly.
    4. Confirms zero orphaned ping.exe processes remain.
    """
    if sys.platform != "win32" or kernel32 is None:
        pytest.skip("Windows platform required for Win32 Job Object test")

    supervisor = Win32JobSupervisor()
    assert supervisor._handle is not None

    num_workers = 5
    workers: list[subprocess.Popen] = []

    try:
        # Spawn 5 concurrent ping workers
        for _ in range(num_workers):
            proc = subprocess.Popen(
                ["cmd.exe", "/c", "ping", "127.0.0.1", "-n", "30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            workers.append(proc)
            assigned = supervisor.assign_process(proc.pid)
            assert assigned is True, f"Failed to assign worker PID {proc.pid} to Job Object"

        # Query active count
        active_count = supervisor.query_active_processes()
        assert active_count >= num_workers, (
            f"Expected at least {num_workers} active processes in Job Object, found {active_count}"
        )

    finally:
        # Close the supervisor handle to trigger kernel-level KILL_ON_JOB_CLOSE
        supervisor.terminate_all(0)
        supervisor.close()

    # Poll workers for clean termination
    deadline = time.time() + 3.0
    all_terminated = False
    while time.time() < deadline:
        if all(w.poll() is not None for w in workers):
            all_terminated = True
            break
        time.sleep(0.05)

    assert all_terminated is True, "One or more child workers failed to terminate after Job Object close"

    # Verify zero orphaned ping.exe processes exist via tasklist
    res = subprocess.run(
        "tasklist | findstr /i ping.exe",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert res.returncode == 1, "Orphaned ping.exe process detected in system tasklist!"


def test_runner_target_modes_process_lifecycle():
    """Verify StandaloneSoakRunner initialization across target modes:
    - 'spawn': initializes an active Win32JobSupervisor with KILL_ON_JOB_CLOSE.
    - 'mock': in-process mode; runner.job_supervisor is None.
    - 'attach': external monitoring mode; runner.job_supervisor is None.
    """
    cfg_spawn = parse_soak_cli_args(["--target-mode", "spawn", "--duration-minutes", "1"])
    runner_spawn = StandaloneSoakRunner(cfg_spawn)
    assert runner_spawn.job_supervisor is not None
    assert runner_spawn.job_supervisor._handle is not None
    runner_spawn.job_supervisor.close()

    cfg_mock = parse_soak_cli_args(["--target-mode", "mock", "--duration-minutes", "1"])
    runner_mock = StandaloneSoakRunner(cfg_mock)
    assert runner_mock.job_supervisor is None

    cfg_attach = parse_soak_cli_args(["--target-mode", "attach", "--duration-minutes", "1"])
    runner_attach = StandaloneSoakRunner(cfg_attach)
    assert runner_attach.job_supervisor is None


# ==============================================================================
# 3. Teardown Coordination & Orphan Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_graceful_shutdown_coordinator_terminates_job_processes():
    """Verify that GracefulShutdownCoordinator terminates all assigned processes in phase 2."""
    if sys.platform != "win32" or kernel32 is None:
        pytest.skip("Windows platform required for Win32 Job Object test")

    supervisor = Win32JobSupervisor()
    coord = GracefulShutdownCoordinator(job_supervisor=supervisor)

    # Spawn 2 long-running workers
    proc1 = subprocess.Popen(["cmd.exe", "/c", "ping", "127.0.0.1", "-n", "30"])
    proc2 = subprocess.Popen(["cmd.exe", "/c", "ping", "127.0.0.1", "-n", "30"])

    supervisor.assign_process(proc1.pid)
    supervisor.assign_process(proc2.pid)

    assert supervisor.query_active_processes() >= 2

    # Execute teardown
    await coord.execute_teardown()

    # Wait for processes to exit
    time.sleep(0.5)
    assert proc1.poll() is not None, f"Proc1 PID {proc1.pid} survived teardown"
    assert proc2.poll() is not None, f"Proc2 PID {proc2.pid} survived teardown"

    # Verify zero ping.exe processes remain
    res = subprocess.run(
        "tasklist | findstr /i ping.exe",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert res.returncode == 1, "Orphaned ping.exe process detected after teardown!"
