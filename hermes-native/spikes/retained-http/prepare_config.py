"""Prepare non-secret pins for an opt-in Rust-owned retained HTTP proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
import types
from pathlib import Path

LOG = logging.getLogger(__name__)
sys.dont_write_bytecode = True
BACKEND_FILES = (
    "diagnostics/bootstrap.py",
    "src/hermes_backend_host/__init__.py",
    "src/hermes_backend_host/readiness.py",
    "src/hermes_backend_host/diagnostic_source.py",
    "src/hermes_backend_host/diagnostic_policy.py",
)


def checked(path: Path, *, directory: bool) -> Path:
    path = path.absolute()
    for ancestor in (path, *path.parents):
        if (
            ancestor.stat(follow_symlinks=False).st_file_attributes
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Input paths may not traverse reparse points")
    path = path.resolve(strict=True)
    if path.is_dir() != directory or (not directory and not path.is_file()):
        raise ValueError("Input path type is invalid")
    return path


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def helper_bytes(path: Path) -> bytes:
    with path.open("rb") as source:
        data = source.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Backend helper input exceeds the 2 MiB source limit")
    return data


def main() -> None:
    if not os.environ.get("VIRTUAL_ENV") or sys.prefix == sys.base_prefix:
        raise RuntimeError("Activate the project virtual environment before preparation")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--interpreter", required=True, type=Path)
    parser.add_argument("--site-packages", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    backend = checked(args.backend_root, directory=True)
    candidate = checked(args.candidate, directory=True)
    site_packages = checked(args.site_packages, directory=True)
    interpreter = checked(args.interpreter, directory=False)
    output = args.output.absolute()
    if output.exists():
        raise ValueError("Use a new output directory for every proof")
    parent = checked(output.parent, directory=True)
    output = parent / output.name
    helper = output.with_name(output.name + "-helper")
    if helper.exists():
        raise ValueError("The sibling helper export directory already exists")
    for source in (backend, candidate, site_packages):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("Proof output must not overlap inputs")
    source_bytes = {
        name: helper_bytes(checked(backend / name, directory=False)) for name in BACKEND_FILES
    }
    source_pins = {name: hashlib.sha256(data).hexdigest() for name, data in source_bytes.items()}
    verifier_file = checked(
        backend / "src/hermes_backend_host/diagnostic_source.py", directory=False
    )
    verifier = types.ModuleType("retained_diagnostic_source")
    # Execute the explicit stdlib-only verifier source, never an import-loader
    # bytecode cache. The Rust preflight rejects source import shadows separately.
    exec(
        compile(
            source_bytes["src/hermes_backend_host/diagnostic_source.py"], str(verifier_file), "exec"
        ),
        verifier.__dict__,
    )
    verifier.verify(candidate)
    # Discover the exact base of the explicitly chosen retained dependency runtime.
    # This can differ from the development venv: installed Hermes currently uses
    # Python 3.11 while the separate CPU control worker requires Python 3.12+.
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    result = subprocess.run(
        [str(interpreter), "-I", "-S", "-B", "-c", "import sys; print(sys._base_executable)"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # uv may report a version-family junction. Pin and launch its resolved target,
    # then enforce no redirects on that final path; never store the mutable alias.
    python = checked(Path(result.stdout.strip()).resolve(strict=True), directory=False)
    helper.mkdir()
    for name, data in source_bytes.items():
        copied = helper / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(data)
        if sha256(copied) != source_pins[name] or sha256(backend / name) != source_pins[name]:
            raise ValueError("Backend helper source changed during export")
    config = {
        "schema_version": 1,
        "python": {"path": str(python), "sha256": sha256(python)},
        "helper_source_root": str(backend),
        "backend_root": str(helper),
        "backend_files": source_pins,
        "candidate": str(candidate),
        "candidate_manifest_sha256": sha256(candidate / "source-manifest.json"),
        "site_packages": str(site_packages),
    }
    output.mkdir()
    (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    LOG.info("Prepared pinned retained HTTP diagnostic configuration; no service launched")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        LOG.error("Preparation failed: %s", type(exc).__name__)
        raise SystemExit(1) from None
