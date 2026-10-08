import os

import pytest

from hermes_backend_host.diagnostic_policy import (
    DiagnosticPolicy,
    PolicyViolation,
    valid_token,
)


def test_state_writes_and_source_reads(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    policy = DiagnosticPolicy(state, [tmp_path])
    policy.check("open", (tmp_path / "source.py", "r", 0))
    policy.check("open", (state / "state.db", "w", os.O_CREAT))
    with pytest.raises(PolicyViolation, match="write_outside_state"):
        policy.check("open", (tmp_path / "source.py", "w", os.O_WRONLY))


@pytest.mark.parametrize(
    "event,args",
    [
        ("subprocess.Popen", ("program",)),
        ("os.kill", (1, 9)),
        ("socket.connect", (None, ("127.0.0.1", 1234))),
        ("socket.bind", (None, ("0.0.0.0", 0))),
        ("import", ("hermes_bootstrap",)),
        ("import", ("tui_gateway.server",)),
        ("import", ("torch",)),
        ("sqlite3.load_extension", (None, "file")),
    ],
)
def test_forbidden_capabilities(tmp_path, event, args):
    policy = DiagnosticPolicy(tmp_path, [])
    with pytest.raises(PolicyViolation):
        policy.check(event, args)
    assert len(policy.violations) == 1


@pytest.mark.parametrize(
    "name", [".env", ".env.local", "auth.json", "host-serve.token"]
)
def test_credential_files_cannot_be_read_or_written(tmp_path, name):
    policy = DiagnosticPolicy(tmp_path, [])
    with pytest.raises(PolicyViolation, match="credential_file"):
        policy.check("open", (tmp_path / name, "r", 0))


@pytest.mark.parametrize(
    "token,expected",
    [
        ("a" * 32, True),
        ("a" * 31, False),
        ("a" * 4097, False),
        ("a" * 31 + "\x01", False),
        ("a" * 31 + " ", False),
    ],
)
def test_token_validation(token, expected):
    assert valid_token(token) is expected


def test_path_escape_and_sqlite_uri_are_checked(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    policy = DiagnosticPolicy(state, [tmp_path])
    policy.check("sqlite3.connect", ((state / "state.db").as_uri() + "?mode=ro",))
    policy.check("socket.bind", (None, ("127.0.0.1", 0)))
    with pytest.raises(PolicyViolation, match="write_outside_state"):
        policy.check("sqlite3.connect", ((tmp_path / "outside.db").as_uri(),))
    with pytest.raises(PolicyViolation, match="write_outside_state"):
        policy.check("os.mkdir", (state / ".." / "outside",))
    assert all("trace" in item for item in policy.violation_locations)
