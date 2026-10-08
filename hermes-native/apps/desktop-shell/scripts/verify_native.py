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
CONTROL_EXPECTED = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "control-expected.json"
    ).read_text()
)
PROFILES_EXPECTED = {
    "profiles-retained-bootstrap-resolved",
    "profiles-retained-contribution-registered",
    "profiles-truthful-backend-unavailable",
    "profiles-real-boot-dialog-dismissed",
    "profiles-native-runtime-detached",
    "profiles-fresh-store-confirmed",
    "profiles-retained-settings-route-mounted",
    "profiles-control-service-connected",
    "profiles-react-form-input-applied",
    "profiles-form-validation-confirmed",
    "profiles-form-create-confirmed",
    "profiles-form-list-confirmed",
    "profiles-form-read-confirmed",
    "profiles-form-update-confirmed",
    "profiles-delete-requires-confirmation",
    "profiles-form-delete-confirmed",
    "profiles-fixture-record-cleaned",
    "profiles-retained-state-stable",
    "profiles-crud-complete",
    "profiles-react-crash-absent",
    "profiles-uncaught-errors-absent",
    "profiles-unhandled-rejections-absent",
}
RELOAD_EXPECTED = [
    "preview-reload-real-file-event-before-navigation",
    "preview-hash-navigation-preserves-owner",
    "preview-hash-route-still-receives-real-changes",
    "preview-document-reload-retires-same-native-owner",
    "preview-reloaded-document-cannot-reuse-old-native-owner",
    "preview-new-document-rejects-old-native-queued-envelope",
]
PREVIEW_EXPECTED = [
    "preview-adversarial-any-listener-ready",
    "preview-adversarial-any-listener-positive-control",
    "preview-file-watch-real-receipt",
    "preview-directory-watch-real-receipt",
    "preview-registration-does-not-fabricate-change",
    "preview-real-native-file-change-payload",
    "preview-real-native-directory-change-payload",
    "preview-native-stop-owned-watch",
    "preview-native-stop-idempotent",
    "preview-native-stop-directory",
    "preview-stop-prevents-late-native-dispatch",
    "preview-no-hidden-native-watch-faults",
    "preview-native-events-do-not-reach-other-window-any-listener",
    "preview-native-owner-retirement-permanent",
]
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
            "getBootProgress",
            "getRecentLogs",
            "getBootstrapState",
            "resetBootstrap",
            "revealLogs",
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
    parser.add_argument("--control-config", type=Path)
    parser.add_argument(
        "--mode",
        choices=[
            "binding",
            "retained",
            "preview",
            "preview-reload",
            "control-create",
            "control-reopen",
            "control-unavailable",
            "profiles",
        ],
        default="binding",
    )
    args = parser.parse_args()
    if (
        args.mode in {"control-create", "control-reopen", "profiles"}
        and not args.control_config
    ):
        raise ValueError("This fixture requires an explicit control configuration")
    if args.mode == "control-unavailable" and args.control_config:
        raise ValueError("The unavailable fixture forbids control configuration")
    if args.control_config:
        if (
            not args.control_config.is_absolute()
            or not args.control_config.is_file()
            or args.control_config.stat().st_size > 65_536
        ):
            raise ValueError("Control configuration must be an absolute bounded file")
        if args.mode in {"control-create", "profiles"}:
            config = json.loads(args.control_config.read_text())
            control_state = Path(config["state_dir"])
            if (
                not control_state.is_absolute()
                or not control_state.is_dir()
                or any(control_state.iterdir())
            ):
                raise ValueError(
                    "The mutating fixture requires explicitly fresh empty control state"
                )
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
    if args.mode.startswith("preview"):
        preview_root = root / "preview"
        preview_root.mkdir()
        environment["HERMES_NATIVE_PREVIEW_FIXTURE_ROOT"] = str(preview_root)
    if args.control_config:
        environment["HERMES_NATIVE_CONTROL_CONFIG"] = str(
            args.control_config.resolve(strict=True)
        )
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
        checks = report.get("checks")
        if not isinstance(checks, list) or not all(
            isinstance(check, str) for check in checks
        ):
            raise RuntimeError("Native fixture check labels were malformed")
        cleanup = report.get("control_cleanup", {})
        if cleanup.get("verified") is not True:
            raise RuntimeError("Native control cleanup was not verified")
        if args.control_config:
            detail = cleanup.get("report") or {}
            if (
                report.get("control_worker_started") is not True
                or not all(
                    detail.get(key) is True
                    for key in ("job_empty", "stdout_eof", "stderr_eof", "cooperative")
                )
                or detail.get("root_exit_code") != 0
            ):
                raise RuntimeError(
                    "Owned control worker did not stop cooperatively and completely"
                )
        elif (
            report.get("control_worker_started") is not False
            or cleanup.get("report") is not None
        ):
            raise RuntimeError(
                "Unexpected control worker startup without configuration"
            )
        if args.mode == "binding" and report.get("checks") != EXPECTED:
            raise RuntimeError("Native bridge checks were incomplete")
        if args.mode == "preview" and report.get("checks") != PREVIEW_EXPECTED:
            raise RuntimeError("Native preview checks were incomplete")
        if args.mode == "preview-reload" and report.get("checks") != RELOAD_EXPECTED:
            raise RuntimeError(
                "Native preview document retirement checks were incomplete"
            )
        if args.mode in CONTROL_EXPECTED and checks != CONTROL_EXPECTED[args.mode]:
            raise RuntimeError("Native control fixture checks were incomplete")
        if args.mode == "profiles" and (
            not PROFILES_EXPECTED.issubset(checks)
            or any("failed" in check or "failure" in check for check in checks)
            or set(checks) - PROFILES_EXPECTED - {"profiles-connection-retry-used"}
        ):
            raise RuntimeError("Retained native profile CRUD checks were incomplete")
        if args.mode == "retained" and not {
            "retained-wrapper-evaluated",
            "host-adapter-installed",
            "retained-bootstrap-resolved",
            "retained-root-mounted",
            "retained-contrib-shell-mounted",
            "retained-boot-failure-dialog",
            "readable-backend-unavailable-message",
            "react-crash-absent",
            "uncaught-errors-absent",
            "unhandled-rejections-absent",
            "retained-state-stable",
        }.issubset(report.get("checks", [])):
            raise RuntimeError(
                "Retained backend-unavailable view did not stabilize; see native-result.json"
            )
    finally:
        process.close()
    report.update(
        {
            "owned_job_empty_root_exit_pipe_eof_verified": True,
            "seconds": round(time.monotonic() - started, 3),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "tauri_version": "2.12.1",
            "hidden_window": True,
            "retained_wrapper_runtime_observed": args.mode in {"retained", "profiles"},
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
