"""Opt-in, model-independent proof against a separately copied Hermes source candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hermes_backend_host.diagnostic_source import verify  # noqa: E402
from hermes_backend_host.owned_http import OwnedHTTPClient  # noqa: E402
from hermes_backend_host.windows_process import OwnedProcess  # noqa: E402


def main():
    if sys.flags.optimize:
        raise RuntimeError("Proof assertions require non-optimized Python")
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--interpreter", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    if args.state.exists():
        raise ValueError("Proof state must not already exist")
    manifest = verify(args.candidate)
    manifest_hash = hashlib.sha256(
        (args.candidate / "source-manifest.json").read_bytes()
    ).hexdigest()
    args.state.mkdir(parents=True)
    root = args.state.resolve(strict=True)
    token = secrets.token_urlsafe(48)
    env = {
        "SystemRoot": os.environ["SystemRoot"],
        "WINDIR": os.environ["SystemRoot"],
        "USERPROFILE": str(root),
        "HOME": str(root),
        "APPDATA": str(root / "roaming"),
        "LOCALAPPDATA": str(root / "local"),
        "TEMP": str(root),
        "TMP": str(root),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_STATE_HOME": str(root / "state"),
        "HERMES_HOME": str(root),
        "HERMES_MANAGED_DIR": str(root / "managed"),
        "HERMES_GATEWAY_LOCK_DIR": str(root / "locks"),
        "HERMES_SAFE_MODE": "1",
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
        # Public upstream override: this synthetic Windows home needs no Unix chmod.
        "HERMES_SKIP_CHMOD": "1",
        "HERMES_DIAGNOSTIC_SESSION_TOKEN": token,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    arguments = [
        "-I",
        "-S",
        "-B",
        str(Path(__file__).with_name("bootstrap.py")),
        "--candidate",
        str(args.candidate.resolve()),
        "--state",
        str(root),
        "--site-packages",
        str(args.site_packages.resolve()),
    ]
    process = OwnedProcess(args.interpreter.resolve(strict=True), arguments, root, env)
    summary = {
        "mode": "diagnostic-http-subset-v1",
        "stock_server_started": False,
        "gpu_used": False,
        "upstream_handlers_modified": False,
    }
    try:
        port = process.wait_ready(45)
        with OwnedHTTPClient(process, port) as http:
            headers = {"X-Hermes-Session-Token": token}
            assert http.get("/api/config").status_code == 401
            assert (
                http.get(
                    "/api/config",
                    headers={"X-Hermes-Session-Token": secrets.token_urlsafe(48)},
                ).status_code
                == 401
            )
            assert (
                http.get(
                    "/api/config", headers=[("X-Hermes-Session-Token", token)] * 2
                ).status_code
                == 401
            )
            assert http.post("/api/config", headers=headers, json={}).status_code == 403
            assert (
                http.get("/api/config?profile=default", headers=headers).status_code
                == 403
            )
            assert http.get("/api/env", headers=headers).status_code == 403
            config_response = http.get("/api/config", headers=headers)
            if config_response.status_code != 200:
                raise RuntimeError(f"config_status:{config_response.status_code}")
            config = config_response.json()
            assert isinstance(config["model"], str) and isinstance(
                config["model_context_length"], int
            )
            assert not any(k.startswith("_") for k in config)
            assert (
                http.get(
                    "/api/config?include_defaults=invalid", headers=headers
                ).status_code
                == 422
            )
            sessions_response = http.get(
                "/api/sessions?limit=20&order=recent", headers=headers
            )
            if sessions_response.status_code != 200:
                raise RuntimeError(f"sessions_status:{sessions_response.status_code}")
            sessions = sessions_response.json()
            assert (
                sessions["total"] == 1
                and sessions["offset"] == 0
                and sessions["limit"] == 20
            )
            row = sessions["sessions"][0]
            assert row["id"] == "managed-diagnostic-session"
            assert isinstance(row["archived"], bool) and isinstance(row["pinned"], bool)
            assert "system_prompt" not in row and "model_config" not in row
            assert (
                http.get("/api/sessions?order=invalid", headers=headers).status_code
                == 400
            )
            assert (
                http.get("/api/sessions?limit=101", headers=headers).status_code == 422
            )
            identity_response = http.get("/diagnostic/identity", headers=headers)
            assert identity_response.status_code == 200
            identity = identity_response.json()
            assert identity["mode"] == manifest["mode"]
            assert identity["source_manifest_sha256"] == manifest_hash
            assert identity["retained_handlers"] == manifest["retained_handlers"]
            assert process.contains_observed_pid(identity["pid"])
            assert not identity["policy_violations"]
            assert (
                "HERMES_DIAGNOSTIC_SESSION_TOKEN" not in identity["environment_names"]
            )
            summary.update(
                {
                    "identity": identity,
                    "config_keys": sorted(config),
                    "session_response_keys": sorted(sessions),
                    "session_row_keys": sorted(row),
                    "port_zero_ready": True,
                    "auth_and_rejection_checks": 9,
                    "established_socket_ownership_verified_before_credentials": True,
                }
            )
    except BaseException as exc:
        summary["failure_type"] = type(exc).__name__
        failure = root / "diagnostic-failure.json"
        if failure.is_file():
            summary["child_failure"] = json.loads(failure.read_text(encoding="utf-8"))
        raise
    finally:
        try:
            process.close()
            summary["job_cleanup_confirmed"] = True
        finally:
            summary["stdout_bytes"] = process.stdout_bytes
            summary["stderr_bytes"] = process.stderr_bytes
            files = [p for p in root.rglob("*") if p.is_file()]
            assert not any(token.encode("ascii") in p.read_bytes() for p in files)
            summary["credential_bytes_persisted"] = False
            summary["state_files"] = sorted(
                p.relative_to(root).as_posix() for p in files
            )
            (root.parent / f"{root.name}-result.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
    print(
        json.dumps(
            {
                "verified": True,
                "job_cleanup_confirmed": True,
                "result": str(root.parent / f"{root.name}-result.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
