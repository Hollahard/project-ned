"""Prepare a host-selected pinned launch manifest; never launch the worker."""

import argparse
import hashlib
import json
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)
SOURCE_FILES = {
    "worker": ("__init__.py", "errors.py", "profiles.py", "state.py", "protocol.py"),
    "inference": ("__init__.py", "admission.py", "errors.py", "profiles.py"),
}


def resolve_file(value: Path, limit: int) -> tuple[Path, str]:
    path = value.resolve(strict=True)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Invalid or oversized source file")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Source changed while hashing")
    return path, hashlib.sha256(content).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--worker-root", type=Path, required=True)
    parser.add_argument("--inference-src", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(path.is_absolute() for path in vars(args).values()):
        raise ValueError("All manifest inputs must be absolute")
    python, python_hash = resolve_file(args.python, 64 * 1024 * 1024)
    bootstrap, bootstrap_hash = resolve_file(
        args.worker_root / "bootstrap.py", 1_048_576
    )
    inference = args.inference_src.resolve(strict=True)
    worker_root = bootstrap.parent
    parent = args.state_dir.parent.resolve(strict=True)
    state = parent / args.state_dir.name
    if any(
        state.is_relative_to(root) or root.is_relative_to(state)
        for root in (worker_root, inference)
    ):
        raise ValueError("State must be separate from source roots")
    if (
        args.output.exists()
        or state.exists()
        or args.output.resolve().is_relative_to(state)
    ):
        raise ValueError(
            "Configuration and state must be new; config belongs outside state"
        )
    sources = {}
    for group, names in SOURCE_FILES.items():
        root = (
            worker_root / "src" / "hermes_control_worker"
            if group == "worker"
            else inference / "hermes_inference"
        )
        for name in names:
            _, digest = resolve_file(root / name, 1_048_576)
            sources[f"{group}/{name}"] = digest
    config = {
        "schema_version": 1,
        "python": {"path": str(python), "sha256": python_hash},
        "bootstrap": {"path": str(bootstrap), "sha256": bootstrap_hash},
        "inference_src": str(inference),
        "state_dir": str(state),
        "sources": sources,
        "startup_timeout_ms": 10_000,
        "request_timeout_ms": 5_000,
        "shutdown_timeout_ms": 3_000,
    }
    state.mkdir()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    LOG.info(
        "Prepared pinned control manifest and new state directory; no worker was launched."
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
