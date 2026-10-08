"""Bounded hidden Tauri fixture, owned through the existing Windows Job proof."""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

LOG = logging.getLogger(__name__)
EXPECTED = [
    "native-injection-before-entry",
    *[
        "honest-unavailable:" + method
        for method in [
            "api",
            "getConnection",
            "getConnectionFor",
            "getGatewayWsUrl",
            "getGatewayWsUrlFor",
            "revalidateConnection",
            "touchBackend",
            "getVersion",
        ]
    ],
    "native-unknown-method-rejected",
    "window-create-acl-denied",
    "event-emit-acl-denied",
    "native-event-payload-delivered",
    "native-event-unsubscribe",
]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate the project virtual environment")
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--backend-src", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--mode", choices=["binding", "retained"], default="binding")
    args = parser.parse_args()
    if args.state.exists():
        raise ValueError("Fixture state must be new")
    args.state.mkdir(parents=True)
    root = args.state.resolve(strict=True)
    profile = root / "webview"
    profile.mkdir()
    output = root / "native-result.json"
    sys.path.insert(0, str(args.backend_src.resolve(strict=True)))
    from hermes_backend_host.windows_process import OwnedProcess

    environment = {
        "SystemRoot": os.environ["SystemRoot"],
        "WINDIR": os.environ["SystemRoot"],
        "USERPROFILE": str(root),
        "HOME": str(root),
        "APPDATA": str(root / "roaming"),
        "LOCALAPPDATA": str(root / "local"),
        "TEMP": str(root),
        "TMP": str(root),
        "HERMES_NATIVE_WEBVIEW_PROFILE": str(profile),
        "HERMES_NATIVE_FIXTURE_RESULT": str(output),
        "HERMES_NATIVE_FIXTURE_MODE": args.mode,
    }
    executable = args.executable.resolve(strict=True)
    started = time.monotonic()
    process = OwnedProcess(executable, [], root, environment)
    try:
        while process.poll() is None:
            if time.monotonic() - started > 90:
                raise TimeoutError("Native fixture deadline exceeded")
            time.sleep(0.05)
        if process.poll() != 0 or not output.is_file() or output.stat().st_size > 8192:
            raise RuntimeError("Native fixture did not report success")
        report = json.loads(output.read_text())
        if report.get("mode") != "native-tauri-fixture":
            raise RuntimeError("Native fixture checks were incomplete")
        if args.mode == "binding" and report.get("checks") != EXPECTED:
            raise RuntimeError("Native bridge checks were incomplete")
        if args.mode == "retained" and not {
            "retained-wrapper-evaluated",
            "host-adapter-installed",
        }.issubset(report.get("checks", [])):
            raise RuntimeError("Retained wrapper did not evaluate")
    finally:
        process.close()
    report.update(
        {
            "owned_job_empty_root_exit_pipe_eof_verified": True,
            "seconds": round(time.monotonic() - started, 3),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "tauri_version": "2.12.1",
            "hidden_window": True,
            "retained_wrapper_runtime_observed": args.mode == "retained",
            "retained_ui_parity_verified": False,
            "llm_inference_or_agent_backend_started": False,
        }
    )
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    LOG.info(
        "Native %s fixture recorded %s checks; owned cleanup verified",
        args.mode,
        len(report["checks"]),
    )


if __name__ == "__main__":
    main()
