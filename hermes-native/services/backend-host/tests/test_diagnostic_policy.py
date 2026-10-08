import os
from pathlib import Path

import pytest

from hermes_backend_host.diagnostic_policy import (
    DiagnosticPolicy,
    PolicyViolation,
    comparison_path,
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


@pytest.mark.skipif(os.name != "nt", reason="Windows path namespace compatibility")
@pytest.mark.parametrize("root_verbatim", [False, True])
@pytest.mark.parametrize("request_verbatim", [False, True])
def test_resolved_drive_aliases_preserve_allowed_and_denied_roots(
    tmp_path, root_verbatim, request_verbatim
):
    state = tmp_path / "state"
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    for directory in (state, source, outside):
        directory.mkdir()
    module = source / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")

    def spelling(path, verbatim):
        return Path("\\\\?\\" + str(path)) if verbatim else path

    policy = DiagnosticPolicy(
        spelling(state, root_verbatim), [spelling(source, root_verbatim)]
    )
    policy.path(spelling(module, request_verbatim))
    policy.path(spelling(state / "not-created.db", request_verbatim), write=True)
    with pytest.raises(PolicyViolation, match="read_outside_roots"):
        policy.path(spelling(outside / "not-created.py", request_verbatim))
    with pytest.raises(PolicyViolation, match="write_outside_state"):
        policy.path(spelling(source / "not-created.db", request_verbatim), write=True)
    with pytest.raises(PolicyViolation, match="credential_file"):
        policy.path(spelling(state / ".env.local", request_verbatim))


@pytest.mark.skipif(os.name != "nt", reason="Windows verbatim path semantics")
def test_comparison_preserves_verbatim_significant_names_and_long_paths(tmp_path):
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    significant = Path("\\\\?\\" + str(tmp_path / "significant. "))
    significant.mkdir()
    try:
        assert comparison_path(significant).name == "significant. "
        assert comparison_path(ordinary) == Path("\\\\?\\" + str(ordinary))
        long_future = ordinary.joinpath(
            *("segment" * 10 for _ in range(5)), "future.db"
        )
        assert len(str(long_future)) > 260
        assert comparison_path(long_future).is_relative_to(comparison_path(ordinary))
        assert comparison_path(significant) != comparison_path(tmp_path / "significant")
    finally:
        significant.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction target resolution")
def test_comparison_rejects_junction_escape_for_nonexistent_write(tmp_path):
    import _winapi

    state = tmp_path / "state"
    outside = tmp_path / "outside"
    state.mkdir()
    outside.mkdir()
    link = state / "redirect"
    _winapi.CreateJunction(str(outside), str(link))
    try:
        policy = DiagnosticPolicy(state, [])
        for target in (link / "future.db", Path("\\\\?\\" + str(link / "future.db"))):
            with pytest.raises(PolicyViolation, match="write_outside_state"):
                policy.path(target, write=True)
    finally:
        link.rmdir()
