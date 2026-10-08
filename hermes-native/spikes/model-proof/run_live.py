"""Bounded, explicitly enabled GPU proof. Review prepared.json before --run-gpu-proof."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import logging
import os
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

sys.dont_write_bytecode = True
LOG = logging.getLogger(__name__)
POLICY = {
    "network": {
        "host": "127.0.0.1",
        "disable_auth": False,
        "allowed_origins": [],
        "access_log": False,
        "send_tracebacks": False,
    },
    "model": {
        "model_name": "",
        "inline_model_loading": False,
        "use_dummy_models": False,
        "use_as_default": [],
    },
    "draft_model": {"draft_mode": "disabled", "draft_model_name": ""},
    "embeddings": {"embedding_model_name": "", "embeddings_device": "cpu"},
    "logging": {
        "log_prompt": False,
        "log_generation_params": False,
        "log_requests": False,
        "log_chat_completion_requests": False,
        "log_live_status": False,
    },
    "developer": {"unsafe_launch": False, "seqlog": False},
}


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def model_snapshot(model):
    return {
        p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
        for p in model.iterdir()
        if p.is_file()
    }


def verify_prepared(root, receipt):
    runtime = Path(receipt["runtime"])
    if runtime != root / "runtime" or not runtime.is_dir():
        raise ValueError("Prepared runtime must be a direct child of the proof root")
    if receipt["overlay"].get("managed_contract_version") != "hermes-native-observation-v1":
        raise ValueError("Managed observation contract is absent")
    if digest(Path(receipt["python"])) != receipt["python_sha256"]:
        raise ValueError("Base Python interpreter changed after preparation")
    if digest(Path(receipt["venv_config"]["path"])) != receipt["venv_config"]["sha256"]:
        raise ValueError("Runtime Python configuration changed after preparation")
    for name, expected in receipt["triton_toolchain"]["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError("Bundled Triton toolchain changed after preparation")
    if digest(root / "bootstrap.py") != receipt["bootstrap_sha256"]:
        raise ValueError("Bootstrap changed after preparation")
    if digest(root / "managed-template.yml") != receipt["template_sha256"]:
        raise ValueError("Managed template changed after preparation")
    for relative, expected in receipt["runtime_files"].items():
        if digest(runtime / relative) != expected:
            raise ValueError("Runtime changed after preparation")
    if model_snapshot(Path(receipt["model"])) != receipt["model_files_before"]:
        raise ValueError("Model directory changed after preparation")
    if (Path(receipt["model"]) / "tabby_config.yml").exists():
        raise ValueError("Model-folder overrides are forbidden")
    if digest(Path(receipt["extension"]["path"])) != receipt["extension"]["sha256"]:
        raise ValueError("Precompiled extension changed after preparation")


def build_environment(root, executable, api_key, admin_key, toolchain=None):
    if not api_key or api_key == admin_key:
        raise ValueError("Distinct runtime credentials required")
    windows = Path(os.environ["SystemRoot"])
    env = {
        "SystemRoot": str(windows),
        "WINDIR": str(windows),
        "PATH": os.pathsep.join((str(executable.parent), str(windows / "System32"))),
        "CUDA_VISIBLE_DEVICES": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HERMES_TABBY_API_KEY": api_key,
        "HERMES_TABBY_ADMIN_KEY": admin_key,
    }
    if toolchain is not None:
        compiler = Path(toolchain["compiler"])
        cuda_path = Path(toolchain["cuda_path"])
        if not compiler.is_absolute() or not compiler.is_file() or not cuda_path.is_absolute():
            raise ValueError("Explicit absolute Triton toolchain required")
        env["CC"] = str(compiler)
        env["CUDA_PATH"] = str(cuda_path)
    for name in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CACHE_HOME",
        "TEMP",
        "TMP",
        "HF_HOME",
        "HF_HUB_CACHE",
        "HF_MODULES_CACHE",
        "TORCH_HOME",
        "TORCH_EXTENSIONS_DIR",
        "TORCHINDUCTOR_CACHE_DIR",
        "TRITON_HOME",
        "TRITON_CACHE_DIR",
        "TRITON_DUMP_DIR",
        "TRITON_OVERRIDE_DIR",
        "CUDA_CACHE_PATH",
    ):
        path = root / "scratch" / name.lower()
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    return env


def make_config(root, receipt, port):
    value = yaml.safe_load((root / "managed-template.yml").read_text())
    for section, settings in POLICY.items():
        for key, expected in settings.items():
            if value.get(section, {}).get(key) != expected:
                raise ValueError("Template differs from explicit managed policy")
    value["network"]["port"] = port
    value["model"]["model_dir"] = str(Path(receipt["model"]).parent)
    return value


def telemetry(stage):
    result = subprocess.run(
        [
            str(Path(os.environ["SystemRoot"]) / "System32" / "nvidia-smi.exe"),
            "--query-gpu=index,name,memory.total,memory.used,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    rows = []
    for line in result.stdout.strip().splitlines():
        index, name, total, used, free, driver = (part.strip() for part in line.split(","))
        rows.append(
            {
                "index": int(index),
                "name": name,
                "total_mib": int(total),
                "used_mib": int(used),
                "free_mib": int(free),
                "driver": driver,
            }
        )
    return {
        "stage": stage,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "gpus": rows,
        "scope": "whole GPU including unrelated desktop allocations",
    }


def listeners_ipv4(port):
    """Query TCP ownership only; never open process termination handles."""
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    api.restype = ctypes.c_ulong
    size = ctypes.c_ulong()
    if api(None, ctypes.byref(size), False, 2, 3, 0) not in (0, 122):
        raise RuntimeError("TCP owner table size query failed")
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), False, 2, 3, 0)
        if result == 122:
            continue
        if result:
            raise RuntimeError("TCP owner table query failed")
        count = struct.unpack_from("<I", buffer.raw)[0]
        if 4 + count * 24 > len(buffer):
            raise RuntimeError("Invalid TCP owner table length")
        values = []
        for index in range(count):
            state, address, local_port, _, _, pid = struct.unpack_from(
                "<6I", buffer.raw, 4 + index * 24
            )
            if state == 2 and socket.ntohs(local_port & 0xFFFF) == port:
                values.append((socket.inet_ntoa(struct.pack("<I", address)), pid))
        return values
    raise RuntimeError("TCP owner table changed repeatedly")


def listener_owned(process, port):
    listeners = listeners_ipv4(port)
    return bool(listeners) and all(
        address == "127.0.0.1" and process.contains_observed_pid(pid) for address, pid in listeners
    )


async def wait_owned_listener(process, port):
    while True:
        if process.poll() is not None:
            raise RuntimeError("Owned worker exited before listener readiness")
        observed = listeners_ipv4(port)
        if observed:
            if not all(
                address == "127.0.0.1" and process.contains_observed_pid(pid)
                for address, pid in observed
            ):
                raise RuntimeError("Unowned listener occupied the managed port")
            return
        await asyncio.sleep(0.1)


class OwnedTransport(httpx.AsyncBaseTransport):
    """Fence every request with the original Job. TCP snapshots are not TLS identity."""

    def __init__(self, process, port, inner=None):
        self.process, self.port = process, port
        self.inner = inner if inner is not None else httpx.AsyncHTTPTransport(retries=0)
        self.fenced = False

    async def handle_async_request(self, request):
        if (
            self.fenced
            or self.process.poll() is not None
            or not listener_owned(self.process, self.port)
        ):
            self.fenced = True
            raise RuntimeError("Owned endpoint changed; no request was sent")
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


def scan_owned_artifacts(root, credentials):
    """Bounded canary scan; never report tokens, matching lines, or file contents."""
    needles = [value.encode() for value in credentials]
    scanned = 0
    result = {"complete": True, "token_file_found": False, "credential_match_found": False}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "api_tokens.yml":
            result["token_file_found"] = True
        scanned += path.stat().st_size
        if scanned > 1024 * 1024 * 1024:
            result["complete"] = False
            break
        tail = b""
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                value = tail + block
                if any(needle in value for needle in needles):
                    result["credential_match_found"] = True
                tail = value[-max(map(len, needles)) :]
    result["bytes_scanned"] = scanned
    return result


async def bounded_request(client, method, path, *, headers=None, payload=None, limit=65536):
    async with client.stream(method, path, headers=headers, json=payload) as response:
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > limit:
                raise ValueError("Response exceeds proof bound")
        return response.status_code, bytes(raw)


async def exercise(root, receipt, process, port, api_key, admin_key, evidence):
    from hermes_inference import Credentials, LoadProfile, TabbyV3Control
    from hermes_inference.admission import InMemoryAdmissionGate

    origin = f"http://127.0.0.1:{port}"
    api_header = {"Authorization": f"Bearer {api_key}"}
    admin_header = {"Authorization": f"Bearer {admin_key}"}
    gate = InMemoryAdmissionGate()
    credentials = Credentials(api_key, admin_key)
    control = TabbyV3Control(
        base_url=origin,
        credentials=credentials,
        gate=gate,
        operation_timeout=600,
        transport=OwnedTransport(process, port),
    )
    profile = LoadProfile(
        artifact_id="local-mistral-proof",
        revision=receipt["model_revision_sha256"],
        model_name=Path(receipt["model"]).name,
        expected_model_path=receipt["model"],
        context_length=2048,
        cache_size=2048,
        cache_mode="FP16",
        max_batch_size=1,
        chunk_size=256,
        vision=False,
    )
    try:
        async with httpx.AsyncClient(
            base_url=origin,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5, connect=1),
            transport=OwnedTransport(process, port),
        ) as client:
            async with asyncio.timeout(180):
                await wait_owned_listener(process, port)
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Owned worker exited before authenticated readiness")
                    if not listener_owned(process, port):
                        raise RuntimeError(
                            "Owned listener vanished before credentials could be sent"
                        )
                    try:
                        status, raw = await bounded_request(
                            client, "GET", "/v1/auth/permission", headers=admin_header
                        )
                    except httpx.TransportError:
                        await asyncio.sleep(0.25)
                        continue
                    if status == 200 and json.loads(raw).get("permission") == "admin":
                        if not listener_owned(process, port):
                            raise RuntimeError("Authenticated listener is outside owned Job")
                        break
                    raise RuntimeError("Unexpected service answered the managed port")
            bootstrap = json.loads((root / "bootstrap-proof.json").read_text())
            if not process.contains_observed_pid(bootstrap["pid"]):
                raise RuntimeError("Bootstrap PID is outside the owned Job")
            evidence["ownership"] = {
                "listener_in_private_job": True,
                "bootstrap_pid_in_private_job": True,
                "root_pid": process.pid,
                "bootstrap_pid": bootstrap["pid"],
            }
            cases = [
                ({}, 401),
                ({"Authorization": "Bearer invalid"}, 401),
                ([("Authorization", f"Bearer {api_key}"), ("X-API-Key", api_key)], 401),
            ]
            for headers, expected in cases:
                status, _ = await bounded_request(
                    client, "GET", "/v1/auth/permission", headers=headers
                )
                if status != expected:
                    raise RuntimeError("Authentication negative test failed")
            status, raw = await bounded_request(
                client, "GET", "/v1/auth/permission", headers=api_header
            )
            if status != 200 or json.loads(raw).get("permission") != "api":
                raise RuntimeError("Inference role observation failed")
            status, _ = await bounded_request(
                client, "POST", "/v1/model/load", headers=api_header, payload=profile.payload()
            )
            if status != 401:
                raise RuntimeError("Inference role unexpectedly admitted admin load")
            status, _ = await bounded_request(client, "GET", "/v1/model", headers=api_header)
            if status != 503:
                raise RuntimeError("No-autoload policy failed")
            evidence["auth_and_no_autoload"] = True
            gate.open(expected_generation=gate.snapshot().generation)
            start = time.monotonic()
            await control.apply(profile)
            evidence["load_seconds"] = round(time.monotonic() - start, 3)
            evidence["control_ready"] = control.status().state.value == "ready"
            card_status, card_raw = await bounded_request(
                client, "GET", "/v1/model", headers=api_header
            )
            props_status, props_raw = await bounded_request(
                client, "GET", "/props", headers=api_header
            )
            if card_status != 200 or props_status != 200:
                raise RuntimeError("Effective observation capture failed")
            card, props = json.loads(card_raw), json.loads(props_raw)
            keys = (
                "max_seq_len",
                "cache_size",
                "cache_mode",
                "max_batch_size",
                "chunk_size",
                "use_vision",
                "hermes_native_draft_enabled",
            )
            evidence["effective_settings"] = {
                "id": card.get("id"),
                "parameters": {key: card["parameters"].get(key) for key in keys},
                "model_path": props.get("model_path"),
                "total_slots": props.get("total_slots"),
                "n_ctx": props.get("default_generation_settings", {}).get("n_ctx"),
                "vision": props.get("modalities", {}).get("vision"),
            }
            evidence["gpu_samples"].append(telemetry("loaded"))
            # The controller has verified /v1/model, /props, /v1/model in sequence.
            async with control.generation(profile) as lease:
                async with asyncio.timeout(60):
                    start = time.monotonic()
                    lease.ensure_valid()
                    async with client.stream(
                        "POST",
                        "/v1/completions",
                        headers=api_header,
                        timeout=60,
                        json={
                            "model": profile.model_name,
                            "prompt": "The capital of France is",
                            "temperature": 0,
                            "max_tokens": 16,
                            "stream": False,
                        },
                    ) as response:
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            lease.ensure_valid()
                            raw.extend(chunk)
                            if len(raw) > 65536:
                                raise RuntimeError("Generation response exceeds bound")
                        if response.status_code != 200:
                            raise RuntimeError("Generation HTTP failure")
                    data = json.loads(raw)
                    choice = data["choices"][0]
                    tokens = data["usage"]["completion_tokens"]
                    if (
                        not isinstance(choice.get("text"), str)
                        or not choice["text"].strip()
                        or not 0 < tokens <= 16
                    ):
                        raise RuntimeError("No bounded generated text was observed")
                    evidence["generation"] = {
                        "seconds": round(time.monotonic() - start, 3),
                        "completion_tokens": tokens,
                        "finish_reason": choice.get("finish_reason"),
                        "nonempty_text": True,
                    }
            gate.close()
            start = time.monotonic()
            async with asyncio.timeout(60):
                await control.unload()
            evidence["unload"] = {
                "seconds": round(time.monotonic() - start, 3),
                "model_absence_verified": control.status().state.value == "unloaded",
            }
            evidence["gpu_samples"].append(telemetry("unloaded_worker_still_alive"))
    finally:
        gate.close()
        await control.aclose()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate the main project venv")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--backend-src", type=Path, required=True)
    parser.add_argument("--inference-src", type=Path, required=True)
    parser.add_argument("--run-gpu-proof", action="store_true")
    args = parser.parse_args()
    if not args.run_gpu_proof:
        parser.error("GPU launch requires explicit --run-gpu-proof after review")
    root = args.prepared.resolve()
    if (root / "result.json").exists() or (root / "managed.json").exists():
        raise ValueError("Each prepared snapshot is single-use")
    receipt = json.loads((root / "prepared.json").read_text())
    verify_prepared(root, receipt)
    sys.path[:0] = [str(args.backend_src.resolve()), str(args.inference_src.resolve())]
    from hermes_backend_host.windows_process import OwnedProcess

    api_key, admin_key = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    executable = Path(receipt["python"])
    environment = build_environment(
        root, executable, api_key, admin_key, receipt["triton_toolchain"]
    )
    with socket.socket() as reservation:
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    # Tabby has no inherited socket option. The race fails closed through role+Job verification.
    config = make_config(root, receipt, port)
    (root / "managed.json").write_text(json.dumps(config, indent=2))
    evidence = {
        "status": "failed",
        "gpu_samples": [telemetry("before_worker")],
        "runtime_pack_id": receipt["runtime_pack_id"],
        "port": port,
        "model_revision_sha256": receipt["model_revision_sha256"],
        "limitations": receipt["limitations"],
        "instant_vram_release_claimed": False,
    }
    free = evidence["gpu_samples"][0]["gpus"][0]["free_mib"]
    required = receipt["model_inventory"]["available_shard_bytes"] / (1024 * 1024) + 4096
    if free < required:
        raise RuntimeError("Available GPU memory below conservative proof threshold")
    process = None
    watchdog = None
    watchdog_fired = threading.Event()
    cleanup_errors = []

    def retire():
        watchdog_fired.set()
        try:
            process.close()
        except Exception as error:  # noqa: BLE001 - boundary records sanitized cleanup failure
            cleanup_errors.append(type(error).__name__)

    try:
        process = OwnedProcess(
            executable,
            [
                "-I",
                "-S",
                "-B",
                "-X",
                "utf8",
                str(root / "bootstrap.py"),
                "--config",
                str(root / "managed.json"),
            ],
            Path(receipt["runtime"]),
            environment,
        )
        watchdog = threading.Timer(900, retire)
        watchdog.daemon = True
        watchdog.start()
        asyncio.run(exercise(root, receipt, process, port, api_key, admin_key, evidence))
        evidence["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - never expose upstream error bodies
        evidence["failure_type"] = type(error).__name__
        LOG.error("GPU proof failed: %s", type(error).__name__)
    finally:
        if watchdog:
            watchdog.cancel()
            watchdog.join(timeout=15)
            if watchdog.is_alive():
                cleanup_errors.append("WatchdogCleanupDidNotFinish")
        if process:
            try:
                process.close()
                evidence["cleanup"] = {
                    "owned_job_zero_processes_verified": not cleanup_errors,
                    "root_exit_and_pipe_eof_verified": not cleanup_errors,
                    "stdout_bytes": process.stdout_bytes,
                    "stderr_bytes": process.stderr_bytes,
                }
            except Exception as error:  # noqa: BLE001 - preserve cleanup evidence after errors
                cleanup_errors.append(type(error).__name__)
        if cleanup_errors or watchdog_fired.is_set():
            evidence["status"] = "failed"
            evidence["cleanup_errors"] = cleanup_errors
            evidence["watchdog_fired"] = watchdog_fired.is_set()
        for index in range(3):
            try:
                evidence["gpu_samples"].append(telemetry(f"after_owned_exit_{index}"))
            except Exception as error:  # noqa: BLE001 - sanitized telemetry failure
                evidence["telemetry_error"] = type(error).__name__
                evidence["status"] = "failed"
            if index < 2:
                time.sleep(1)
        unchanged = model_snapshot(Path(receipt["model"])) == receipt["model_files_before"]
        evidence["model_names_sizes_mtimes_unchanged"] = unchanged
        if not unchanged:
            evidence["status"] = "failed"
        small_hashes_match = all(
            digest(Path(receipt["model"]) / name) == expected
            for name, expected in receipt["model_required_sha256"].items()
            if not name.endswith(".safetensors")
        )
        source_hashes_match = all(
            digest(Path(receipt["runtime"]) / name) == expected
            for name, expected in receipt["runtime_files"].items()
        )
        evidence["model_small_hashes_unchanged"] = small_hashes_match
        evidence["managed_source_hashes_unchanged"] = source_hashes_match
        if not small_hashes_match or not source_hashes_match:
            evidence["status"] = "failed"
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                evidence["listener_closed"] = False
                evidence["status"] = "failed"
        except OSError:
            evidence["listener_closed"] = True
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        leak = scan_owned_artifacts(root, (api_key, admin_key))
        evidence["credential_artifact_scan"] = leak
        if leak["token_file_found"] or leak["credential_match_found"] or not leak["complete"]:
            evidence["status"] = "failed"
        serialized = json.dumps(evidence, indent=2) + "\n"
        if any(value in serialized for value in (api_key, admin_key)):
            serialized = json.dumps({"status": "failed", "failure_type": "ReportCanaryLeak"})
            evidence["status"] = "failed"
        (root / "result.json").write_text(serialized)
    LOG.info("GPU proof %s; sanitized result %s", evidence["status"], root / "result.json")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
