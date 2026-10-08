import os

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Windows socket and Job ownership"
)

if os.name == "nt":
    from test_windows_process import launch

    from hermes_backend_host.owned_http import OwnedHTTPClient


def test_auth_sent_only_after_established_socket_is_in_owned_job(tmp_path):
    process, env = launch(tmp_path)
    with process, OwnedHTTPClient(process, process.wait_ready(10)) as http:
        assert http.get("/api/config").status_code == 401
        response = http.get(
            "/api/config",
            headers={"X-Hermes-Session-Token": env["FIXTURE_SESSION_TOKEN"]},
        )
        assert response.status_code == 200


def test_other_job_listener_rejected_before_any_http_header(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    own, _ = launch(first)
    other, env = launch(second)
    with own, other:
        own.wait_ready(10)
        with OwnedHTTPClient(own, other.wait_ready(10)) as http:
            called = []
            monkeypatch.setattr(
                http.connection, "putheader", lambda *args: called.append(True)
            )
            with pytest.raises(RuntimeError, match="not owned"):
                http.get(
                    "/api/config",
                    headers={"X-Hermes-Session-Token": env["FIXTURE_SESSION_TOKEN"]},
                )
            assert not called
        assert other.poll() is None
