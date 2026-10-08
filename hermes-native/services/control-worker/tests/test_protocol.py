import io
import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_control_worker.protocol import MAX_FRAME, METHODS, serve
from hermes_control_worker.state import StateLease

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ["HERMES_CONTROL_INFERENCE_SRC"]).resolve(strict=True)


def frame(method, params=None, request_id="request-1"):
    return (
        json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n"
    ).encode()


def exchange(state, incoming):
    outgoing = io.BytesIO()
    code = serve(state, io.BytesIO(incoming), outgoing)
    return code, [json.loads(line) for line in outgoing.getvalue().splitlines()]


def test_detached_protocol_and_unknown_operations(tmp_path, profile):
    code, messages = exchange(
        tmp_path,
        frame("service.describe")
        + frame("runtime.status", request_id="2")
        + frame("profiles.validate", {"profile": profile}, "3")
        + frame("models.load", {"model": "never"}, "4")
        + frame("service.shutdown", request_id="5"),
    )
    assert code == 0
    assert messages[0] == {
        "type": "ready",
        "protocol": "hermes-control-v1",
        "service": "hermes-control-worker",
        "runtime_attached": False,
    }
    assert messages[1]["result"]["methods"] == list(METHODS)
    assert messages[2]["result"] == {
        "state": "detached",
        "runtime_attached": False,
        "admission_allowed": False,
        "active_profile": None,
        "engine_observed": False,
    }
    assert messages[3]["result"]["profile"]["cache_mode"] == "4,4"
    assert messages[3]["result"]["artifact_verified"] is False
    assert messages[4]["error"]["code"] == "METHOD_UNAVAILABLE"
    assert messages[5]["result"] == {"stopping": True}


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"x" * MAX_FRAME + b"\n", "FRAME_INVALID"),
        (b"{}", "FRAME_INVALID"),
        (b"{}\r\n", "FRAME_INVALID"),
        (b"\xff\n", "REQUEST_INVALID"),
        (b"[]\n", "REQUEST_INVALID"),
        (b'{"id":"x","id":"y","method":"profiles.list","params":{}}\n', "REQUEST_INVALID"),
        (b'{"id":"x","method":"profiles.list","params":{},"extra":0}\n', "REQUEST_INVALID"),
        (b'{"id":"x","method":"profiles.list","params":{"x":NaN}}\n', "REQUEST_INVALID"),
        (b'{"id":1,"method":"profiles.list","params":{}}\n', "REQUEST_INVALID"),
    ],
    ids=["large", "partial", "crlf", "utf8", "array", "duplicate", "extra", "nan", "id"],
)
def test_bad_envelope_fails_closed(tmp_path, payload, code):
    exit_code, messages = exchange(tmp_path, payload)
    assert exit_code == 2
    assert messages[-1]["error"]["code"] == code
    assert messages[-1]["id"] is None


def test_duplicate_id_does_not_repeat_mutation(tmp_path, profile):
    save = {"profile_id": "small", "name": "Small", "expected_revision": None, "profile": profile}
    exit_code, messages = exchange(
        tmp_path,
        frame("profiles.save", save)
        + frame("profiles.delete", {"profile_id": "small", "expected_revision": 1})
        + frame("profiles.list", request_id="new"),
    )
    assert exit_code == 0
    assert messages[2]["error"]["code"] == "DUPLICATE_ID"
    assert len(messages[3]["result"]["profiles"]) == 1


def test_invalid_shutdown_params_do_not_stop_worker(tmp_path):
    code, messages = exchange(
        tmp_path,
        frame("service.shutdown", {"ignored": True}) + frame("runtime.status", request_id="next"),
    )
    assert code == 0
    assert messages[1]["error"]["code"] == "INVALID_PARAMS"
    assert messages[2]["result"]["state"] == "detached"


def test_session_request_set_is_bounded(tmp_path, monkeypatch):
    import hermes_control_worker.protocol as protocol

    monkeypatch.setattr(protocol, "MAX_REQUESTS", 2)
    code, messages = exchange(
        tmp_path, b"".join(frame("runtime.status", request_id=str(i)) for i in range(3))
    )
    assert code == 2
    assert messages[-1]["error"]["code"] == "SESSION_LIMIT"


def run_worker(state, data, *, extra_env=None, audit=False):
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR") if name in os.environ}
    env.update(extra_env or {})
    args = [sys._base_executable, "-I", "-S", "-B", "-X", "utf8"]
    if audit:
        # A test tripwire, not a claim of operating-system containment.
        code = """
import sys,runpy
def audit(event,args):
    if event in ('socket.__new__','socket.connect','subprocess.Popen','os.system'):
        raise RuntimeError('Forbidden network/process action')
    if event == 'import' and args[0].split('.')[0] in ('httpx','torch','triton','exllamav3'):
        raise RuntimeError('Forbidden inference dependency import')
sys.addaudithook(audit)
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
        args += ["-c", code]
    args += [str(ROOT / "bootstrap.py"), "--inference-src", str(SOURCE), "--state-dir", str(state)]
    return subprocess.run(args, cwd=state, env=env, input=data, capture_output=True, timeout=15)


def test_real_isolated_process_uses_no_site_network_or_engine(tmp_path, profile, monkeypatch):
    monkeypatch.setenv("AMBIENT_API_SECRET", "canary-should-not-be-inherited")
    request = frame("profiles.validate", {"profile": profile}) + frame(
        "service.shutdown", request_id="2"
    )
    result = run_worker(tmp_path, request, audit=True)
    assert result.returncode == 0, result.stderr
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert messages[1]["result"]["profile"]["cache_mode"] == "4,4"
    assert b"canary-should-not-be-inherited" not in result.stdout + result.stderr
    assert b"INFO Control worker ready" in result.stderr
    assert b"\r" not in result.stdout


def test_reopen_worker_retains_saved_profile(tmp_path, profile):
    save = {
        "profile_id": "retained",
        "name": "Retained",
        "expected_revision": None,
        "profile": profile,
    }
    assert run_worker(tmp_path, frame("profiles.save", save)).returncode == 0
    result = run_worker(tmp_path, frame("profiles.get", {"profile_id": "retained"}))
    assert result.returncode == 0
    assert json.loads(result.stdout.splitlines()[1])["result"]["profile_id"] == "retained"


def test_ambient_configuration_is_rejected(tmp_path):
    result = run_worker(tmp_path, b"", extra_env={"PYTHONHOME": "sensitive-canary-value"})
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"sensitive-canary-value" not in result.stderr


def test_unknown_state_files_are_untouched(tmp_path):
    extra = tmp_path / ".env"
    extra.write_text("secret-canary")
    result = run_worker(tmp_path, frame("service.describe"))
    assert result.returncode == 2
    assert result.stdout == b""
    assert extra.read_text() == "secret-canary"
    assert b"secret-canary" not in result.stderr


def test_concurrent_state_owner_is_rejected(tmp_path):
    with StateLease(tmp_path):
        result = run_worker(tmp_path, frame("service.describe"))
    assert result.returncode == 2
    assert result.stdout == b""
    assert run_worker(tmp_path, frame("service.describe")).returncode == 0


def test_profile_secret_fields_never_persist_or_echo(tmp_path, profile):
    result = run_worker(
        tmp_path, frame("profiles.validate", {"profile": profile | {"api_key": "unique-canary"}})
    )
    assert result.returncode == 0
    assert b"unique-canary" not in result.stdout + result.stderr
    assert all(b"unique-canary" not in file.read_bytes() for file in tmp_path.iterdir())


def test_source_loader_ignores_poisoned_bytecode_and_extension(tmp_path, monkeypatch):
    import importlib.machinery
    import importlib.util

    copied = tmp_path / "source"
    shutil.copytree(SOURCE / "hermes_inference", copied / "hermes_inference")
    package = copied / "hermes_inference"
    poison = tmp_path / "poison.py"
    poison.write_text("raise RuntimeError('cached-shadow-canary')\n")
    cache = Path(importlib.util.cache_from_source(str(package / "profiles.py")))
    cache.parent.mkdir(exist_ok=True)
    py_compile.compile(
        str(poison),
        cfile=str(cache),
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    (package / ("profiles" + importlib.machinery.EXTENSION_SUFFIXES[0])).write_bytes(
        b"invalid-shadow"
    )
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", copied)
    result = run_worker(state, frame("profiles.schema"), audit=True)
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout.splitlines()[1])["result"]["schema_source"]
        == "hermes_inference.LoadProfile"
    )
    assert b"cached-shadow-canary" not in result.stdout + result.stderr
