import ctypes
import gc
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Real Windows Job Object proof")
if os.name == "nt":
    from hermes_backend_host.windows_process import (
        OwnedProcess,
        ReadinessError,
        environment_block,
    )

FIXTURE = Path(__file__).with_name("fixture_backend.py")


def child_environment(root):
    return {
        "SystemRoot": os.environ["SystemRoot"],
        "USERPROFILE": str(root),
        "HOME": str(root),
        "HERMES_HOME": str(root),
        "TEMP": str(root),
        "TMP": str(root),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "FIXTURE_SESSION_TOKEN": secrets.token_urlsafe(32),
    }


def launch(root, mode="good", arguments=(), extra_env=None):
    env = child_environment(root)
    env.update(extra_env or {})
    process = OwnedProcess(
        Path(sys.executable), ["-B", str(FIXTURE), mode, *arguments], root, env
    )
    return process, env


def client(process, env):
    port = process.wait_ready(10)
    return httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        timeout=3,
        trust_env=False,
        headers={"X-Hermes-Session-Token": env["FIXTURE_SESSION_TOKEN"]},
    )


def test_real_http_port_zero_auth_identity_and_scoped_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", secrets.token_urlsafe(32))
    monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", secrets.token_urlsafe(32))
    arguments = ["", "two words", 'quote"here', "trailing\\", "雪😀", "$(literal)&;`"]
    process, env = launch(tmp_path, arguments=arguments)
    with process, client(process, env) as http:
        identity = http.get("/api/identity").json()
        assert process.contains_observed_pid(identity["pid"])
        assert not process.contains_observed_pid(os.getpid())
        assert Path(identity["cwd"]) == tmp_path
        assert Path(identity["home"]) == tmp_path
        assert identity["arguments"] == arguments
        assert identity["stdin_eof"]
        assert not {
            "OPENAI_API_KEY",
            "HERMES_DASHBOARD_SESSION_TOKEN",
            "PATH",
            "VIRTUAL_ENV",
        }.intersection(identity["environment_names"])
        assert process.active_count() >= 1
        assert http.get("/api/config").json()["model"]["default"] == "fixture-unloaded"
        assert http.get("/api/sessions").json() == {"sessions": [], "total": 0}
        assert http.get("/missing").status_code == 404
        assert (
            http.get(
                "/api/config", headers={"X-Hermes-Session-Token": "wrong"}
            ).status_code
            == 401
        )
        with httpx.Client(
            base_url=str(http.base_url), timeout=3, trust_env=False
        ) as anonymous:
            assert anonymous.get("/api/config").status_code == 401
    assert not list(tmp_path.iterdir()), (
        "Fixture credentials/config must never be persisted"
    )


def test_stderr_flood_cannot_deadlock_stdout_readiness(tmp_path):
    process, env = launch(tmp_path, "flood")
    with process, client(process, env) as http:
        assert http.get("/api/sessions").status_code == 200
        assert process.stderr_bytes == 262144


@pytest.mark.parametrize("mode", ["silent", "exit", "malformed", "oversize"])
def test_failure_deadlines_clean_up_only_owned_job(tmp_path, mode):
    process, _ = launch(tmp_path, mode)
    started = time.monotonic()
    with process, pytest.raises(ReadinessError):
        process.wait_ready(0.3)
    assert time.monotonic() - started < 8
    process.close()  # idempotent


def test_owned_descendants_and_independent_jobs(tmp_path):
    sibling, sibling_env = launch(tmp_path)
    with sibling, client(sibling, sibling_env) as other_http:
        process, env = launch(tmp_path, "descendant")
        with process, client(process, env) as http:
            # The Windows venv redirector can add an intermediate Python PID.
            assert process.active_count() >= 2
            assert http.get("/api/sessions").status_code == 200
        assert sibling.poll() is None
        assert other_http.get("/api/sessions").status_code == 200


def test_handle_list_excludes_other_inheritable_handles(tmp_path):
    from ctypes import wintypes

    from hermes_backend_host.windows_process import CloseHandle, SecurityAttributes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_event = kernel.CreateEventW
    create_event.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    create_event.restype = wintypes.HANDLE
    sa = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    event = create_event(ctypes.byref(sa), True, False, None)
    assert event
    try:
        process, env = launch(tmp_path, extra_env={"UNLISTED_HANDLE": str(event)})
        with process, client(process, env) as http:
            assert (
                http.get("/api/identity").json()["unlisted_handle_inherited"] is False
            )
    finally:
        CloseHandle(event)


def test_reject_bad_inputs_before_launch(tmp_path):
    with pytest.raises(ValueError):
        OwnedProcess(Path("python.exe"), [], tmp_path, {})
    with pytest.raises(ValueError):
        OwnedProcess(Path(sys.executable), ["bad\0argument"], tmp_path, {})
    for env in [
        {"Path": "one", "PATH": "two"},
        {"BAD=NAME": "value"},
        {"KEY": "bad\0value"},
    ]:
        with pytest.raises(ValueError):
            environment_block(env)


def handle_count():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    current = kernel.GetCurrentProcess
    current.argtypes, current.restype = [], wintypes.HANDLE
    count_handles = kernel.GetProcessHandleCount
    count_handles.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    count_handles.restype = wintypes.BOOL
    count = wintypes.DWORD()
    assert count_handles(current(), ctypes.byref(count))
    return count.value


@pytest.mark.parametrize("seam", ["attributes", "job-list", "create-process"])
def test_partial_constructor_failure_releases_native_handles(
    tmp_path, monkeypatch, seam
):
    import hermes_backend_host.windows_process as native

    original_initialize = native.InitializeAttributes
    original_update = native.UpdateAttribute

    def failed_create(*_):
        ctypes.set_last_error(5)
        return False

    def initialize(pointer, *args):
        if pointer is not None:
            return failed_create()
        return original_initialize(pointer, *args)

    def update(attributes, flags, kind, *args):
        if kind == 0x2000D:
            return failed_create()
        return original_update(attributes, flags, kind, *args)

    if seam == "attributes":
        monkeypatch.setattr(native, "InitializeAttributes", initialize)
    elif seam == "job-list":
        monkeypatch.setattr(native, "UpdateAttribute", update)
    else:
        monkeypatch.setattr(native, "CreateProcess", failed_create)
    gc.collect()
    before = handle_count()
    for _ in range(5):
        with pytest.raises(OSError):
            launch(tmp_path)
    gc.collect()
    # Collection can close earlier HTTP-client handles; it must not grow after
    # repeated failures at any native constructor stage.
    assert handle_count() <= before


def test_cleanup_verification_failure_still_closes_job_and_pipes(tmp_path, monkeypatch):
    import hermes_backend_host.windows_process as native

    process, env = launch(tmp_path)
    with client(process, env) as http:
        assert http.get("/api/sessions").status_code == 200

    def failed_query(*_):
        ctypes.set_last_error(5)
        return False

    monkeypatch.setattr(native, "QueryInformationJobObject", failed_query)
    with pytest.raises(RuntimeError, match="could not be verified"):
        process.close()
    assert all(not thread.is_alive() for thread in process._threads)
    with pytest.raises(RuntimeError, match="closed"):
        process.poll()
    process.close()
