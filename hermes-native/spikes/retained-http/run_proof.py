"""Bounded outer watchdog for the Rust diagnostic; Rust owns the HTTP child Job."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


def main() -> None:
    if not os.environ.get("VIRTUAL_ENV") or sys.prefix == sys.base_prefix:
        raise RuntimeError("Activate the project virtual environment before automation")
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expect-failure-after-ready", action="store_true")
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    config = args.config.resolve(strict=True)
    if (config.parent / "state").exists() or (config.parent / "result.json").exists():
        raise ValueError("Prepared proof directory was already used")
    command = [str(executable), "--config", str(config)]
    if args.expect_failure_after_ready:
        command.append("--fixture-fail-after-ready")
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    # Popen owns this exact Rust process handle. A watchdog kill closes its private
    # non-inherited Job handle, containing its backend child. Timeout is a failed
    # proof: it does not claim verified child cleanup or retry the operation.
    process = subprocess.Popen(
        command,
        cwd=config.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    timed_out = False
    try:
        returncode = process.wait(timeout=150)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Owned Rust watchdog cleanup is unverified") from None
    if timed_out:
        raise RuntimeError("Rust diagnostic exceeded outer watchdog")
    report = json.loads((config.parent / "result.json").read_text(encoding="utf-8"))
    if not report["retirement"]["verified"] or not report["credential_scan_complete"]:
        raise RuntimeError("Owned cleanup or credential scan was not verified")
    if not report["source_pins_unchanged"]:
        raise RuntimeError("Source pins changed during diagnostic")
    if args.expect_failure_after_ready:
        if (
            returncode != 1
            or report["passed"]
            or report["application_error"] != "FIXTURE_FAILURE_AFTER_READY"
        ):
            raise RuntimeError("Expected failure cleanup evidence is missing")
        LOG.info("Expected post-readiness failure retired the owned backend and drained pipes")
    elif returncode != 0 or not report["passed"] or len(report["checks"]) != 12:
        raise RuntimeError("Rust retained HTTP diagnostic did not pass")
    else:
        LOG.info("Rust retained HTTP diagnostic passed 12 checks with verified owned cleanup")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        LOG.error("Proof failed: %s", type(exc).__name__)
        raise SystemExit(1) from None
