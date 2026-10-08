import asyncio
import json
import os
import secrets
import socket
import sys
from pathlib import Path

import httpx
import pytest

import run_live
from prepare import runtime_interpreter


def test_environment_does_not_inherit_credentials_or_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TABBY_NETWORK_DISABLE_AUTH", "true")
    monkeypatch.setenv("PYTHONPATH", "unreviewed")
    monkeypatch.setenv("UNRELATED_TOKEN", "must-never-be-inherited")
    environment = run_live.build_environment(
        tmp_path, Path(r"C:\trusted\python.exe"), "a" * 64, "b" * 64
    )
    assert not any(name.startswith(("TABBY_", "PYTHON")) for name in environment)
    assert "UNRELATED_TOKEN" not in environment
    assert environment["HERMES_TABBY_API_KEY"] == "a" * 64
    for key in (
        "APPDATA",
        "LOCALAPPDATA",
        "HOME",
        "TEMP",
        "TMP",
        "CUDA_CACHE_PATH",
        "TRITON_CACHE_DIR",
        "TORCH_EXTENSIONS_DIR",
        "HF_MODULES_CACHE",
    ):
        assert Path(environment[key]).is_relative_to(tmp_path)
        assert Path(environment[key]).is_dir()
    assert environment["HF_HUB_OFFLINE"] == "1"


def test_triton_toolchain_is_explicit_and_does_not_inherit_ambient_compiler(tmp_path, monkeypatch):
    monkeypatch.setenv("CC", "unreviewed-compiler")
    monkeypatch.setenv("CUDA_PATH", "unreviewed-toolkit")
    compiler = tmp_path / "toolchain" / "tcc.exe"
    compiler.parent.mkdir()
    compiler.write_bytes(b"synthetic compiler fixture")
    cuda = tmp_path / "cuda"
    cuda.mkdir()
    environment = run_live.build_environment(
        tmp_path,
        Path(r"C:\trusted\python.exe"),
        "a" * 64,
        "b" * 64,
        {"compiler": str(compiler), "cuda_path": str(cuda)},
    )
    assert environment["CC"] == str(compiler)
    assert environment["CUDA_PATH"] == str(cuda)
    with pytest.raises(ValueError, match="absolute"):
        run_live.build_environment(
            tmp_path,
            Path(r"C:\trusted\python.exe"),
            "a" * 64,
            "b" * 64,
            {"compiler": "untrusted.exe", "cuda_path": str(cuda)},
        )


def test_config_policy_rejects_auth_off_and_preserves_empty_startup(tmp_path):
    template = json.loads(json.dumps(run_live.POLICY))
    target = tmp_path / "managed-template.yml"
    target.write_text(json.dumps(template))
    receipt = {"model": str(tmp_path / "models" / "model")}
    result = run_live.make_config(tmp_path, receipt, 32123)
    assert result["network"]["port"] == 32123
    assert result["model"]["model_name"] == ""
    assert result["draft_model"]["draft_model_name"] == ""
    assert result["embeddings"]["embedding_model_name"] == ""
    template["network"]["disable_auth"] = True
    target.write_text(json.dumps(template))
    with pytest.raises(ValueError, match="policy"):
        run_live.make_config(tmp_path, receipt, 32123)


def test_bounded_http_refuses_large_response_without_disclosing_body():
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 32))
        async with httpx.AsyncClient(base_url="http://127.0.0.1", transport=transport) as client:
            with pytest.raises(ValueError, match="Response exceeds proof bound"):
                await run_live.bounded_request(client, "GET", "/fixture", limit=16)

    asyncio.run(run())


def test_bounded_http_preserves_duplicate_headers_for_negative_probe():
    def handler(request):
        assert len([k for k, _ in request.headers.raw if k.lower() == b"authorization"]) == 2
        return httpx.Response(401, content=b"{}")

    async def run():
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)
        ) as client:
            status, raw = await run_live.bounded_request(
                client, "GET", "/fixture", headers=[("Authorization", "a"), ("Authorization", "b")]
            )
            assert status == 401 and raw == b"{}"

    asyncio.run(run())


def test_listener_proof_rejects_unowned_or_wildcard_bind(monkeypatch):
    class Owner:
        def contains_observed_pid(self, pid):
            return pid == 42

    def entry(ip, pid):
        return ip, pid

    for entries, expected in (
        ([entry("127.0.0.1", 42)], True),
        ([entry("0.0.0.0", 42)], False),
        ([entry("127.0.0.1", 43)], False),
        ([], False),
    ):
        monkeypatch.setattr(run_live, "listeners_ipv4", lambda port, current=entries: current)
        assert run_live.listener_owned(Owner(), 32123) is expected


def test_snapshot_detects_new_model_override(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    before = run_live.model_snapshot(tmp_path)
    (tmp_path / "tabby_config.yml").write_text("model: {}")
    assert run_live.model_snapshot(tmp_path) != before


def test_recorded_base_interpreter_bypasses_redirector_and_rejects_relative_home(tmp_path):
    source = tmp_path / "runtime"
    (source / ".venv").mkdir(parents=True)
    base = tmp_path / "base"
    base.mkdir()
    (base / "python.exe").write_bytes(b"test-only")
    config = source / ".venv" / "pyvenv.cfg"
    config.write_text(f"home = {base}\n")
    selected_config, executable = runtime_interpreter(source)
    assert selected_config == config and executable == base / "python.exe"
    config.write_text("home = relative\n")
    with pytest.raises(ValueError, match="absolute"):
        runtime_interpreter(source)


def test_unowned_listener_receives_zero_requests_or_credentials(monkeypatch):
    requests = []

    class Owner:
        def poll(self):
            return None

        def contains_observed_pid(self, pid):
            return False

    monkeypatch.setattr(run_live, "listeners_ipv4", lambda port: [("127.0.0.1", 1234)])
    inner = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200))

    async def run():
        transport = run_live.OwnedTransport(Owner(), 32123, inner)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RuntimeError, match="no request was sent"):
                await client.get(
                    "http://127.0.0.1:32123/v1/auth/permission",
                    headers={"Authorization": "Bearer synthetic-test-only"},
                )
        with pytest.raises(RuntimeError, match="Unowned listener"):
            await run_live.wait_owned_listener(Owner(), 32123)

    asyncio.run(run())
    assert requests == []


def test_canary_scan_catches_split_block_and_token_file(tmp_path):
    token = secrets.token_urlsafe(48)
    (tmp_path / "worker.log").write_bytes(b"x" * 65520 + token.encode() + b"tail")
    (tmp_path / "api_tokens.yml").write_text("synthetic-file")
    result = run_live.scan_owned_artifacts(tmp_path, (token, "second-canary"))
    assert result["complete"] and result["credential_match_found"] and result["token_file_found"]
    assert token not in json.dumps(result)


def test_native_owned_synthetic_protocol_cycle(tmp_path, monkeypatch):
    """Real private Job and HTTP transport, synthetic protocol, no GPU imports or telemetry."""
    backend_src = Path(os.environ["HERMES_PROOF_BACKEND_SRC"])
    inference_src = Path(os.environ["HERMES_PROOF_INFERENCE_SRC"])
    sys.path[:0] = [str(backend_src), str(inference_src)]
    from hermes_backend_host.windows_process import OwnedProcess

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    api_key, admin_key = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    env = run_live.build_environment(tmp_path, Path(sys.executable), api_key, admin_key)
    model = str(tmp_path / "synthetic-model")
    fixture = Path(__file__).with_name("fixture_runtime.py")
    evidence = {"gpu_samples": [], "fixture_only": True}
    monkeypatch.setattr(run_live, "telemetry", lambda stage: {"stage": stage, "fixture": True})
    with OwnedProcess(
        Path(sys.executable),
        [
            "-I",
            "-S",
            "-B",
            str(fixture),
            "--port",
            str(port),
            "--root",
            str(tmp_path),
            "--model",
            model,
        ],
        tmp_path,
        env,
    ) as process:
        asyncio.run(
            run_live.exercise(
                tmp_path,
                {"model": model, "model_revision_sha256": "fixture"},
                process,
                port,
                api_key,
                admin_key,
                evidence,
            )
        )
        assert evidence["control_ready"]
        assert evidence["unload"]["model_absence_verified"]
        assert evidence["generation"]["completion_tokens"] == 2
        assert evidence["effective_settings"]["n_ctx"] == 2048
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.3)
    assert (
        run_live.scan_owned_artifacts(tmp_path, (api_key, admin_key))["credential_match_found"]
        is False
    )
