"""Prepare an explicit source receipt and new empty working directory; never launch."""

import argparse
import ctypes
import hashlib
import json
import logging
from pathlib import Path, PureWindowsPath

LOGGER = logging.getLogger(__name__)

MODULES = ("__init__.py", "catalog.py", "common.py", "paths.py", "tensors.py")


def digest(path, maximum):
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError("Pinned file size is invalid")
    return hashlib.sha256(data).hexdigest()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--catalog-src", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--root-grant", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not 1 <= len(args.root_grant) <= 8:
            raise ValueError("One to eight roots required")
        # One DOS namespace avoids equivalent verbatim spelling bypasses in
        # planned-path containment comparisons before any helper writes.
        for path in [
            args.python,
            args.catalog_src,
            args.working_directory,
            args.output,
            *args.root_grant,
        ]:
            drive = PureWindowsPath(path).drive
            if len(drive) != 2 or drive[1] != ":" or not drive[0].isalpha():
                raise ValueError("Ordinary local DOS paths required")
            get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
            get_drive_type.argtypes = [ctypes.c_wchar_p]
            get_drive_type.restype = ctypes.c_uint
            if get_drive_type(drive + "\\") not in (2, 3):
                raise ValueError("Local storage required")
        paths = [args.python, args.catalog_src, *args.root_grant]
        for path in paths:
            if not path.is_absolute() or not path.exists():
                raise ValueError("Explicit existing paths required")
            for component in (path, *path.parents):
                if component.is_symlink() or component.is_junction():
                    raise ValueError("Redirected path")
        # Validate the planned parents before creating anything. A helper must
        # never write under a model grant or a source root even by mistake.
        bootstrap = Path(__file__).resolve().with_name("bootstrap.py")
        planned = [args.working_directory, args.output]
        protected = [*args.root_grant, args.catalog_src, bootstrap.parent]
        for path in planned:
            if not path.is_absolute() or path.exists() or not path.parent.is_dir():
                raise ValueError("Fresh absolute output with existing parent required")
            for component in (path.parent, *path.parent.parents):
                if component.is_symlink() or component.is_junction():
                    raise ValueError("Redirected output parent")
            resolved = path.resolve()
            if any(
                resolved.is_relative_to(root.resolve())
                or root.resolve().is_relative_to(resolved)
                for root in protected
            ):
                raise ValueError("Output overlaps protected input")
        if args.output.resolve().is_relative_to(args.working_directory.resolve()):
            raise ValueError("Receipt must be outside child working directory")
        config = {
            "schema_version": 1,
            "python": {
                "path": str(args.python.resolve()),
                "sha256": digest(args.python, 64 * 1024 * 1024),
            },
            "bootstrap": {"path": str(bootstrap), "sha256": digest(bootstrap, 1048576)},
            "catalog_src": str(args.catalog_src.resolve()),
            "working_directory": str(args.working_directory.absolute()),
            "root_grants": [str(path.resolve()) for path in args.root_grant],
            "sources": {
                name: digest(args.catalog_src / "hermes_model_catalog" / name, 1048576)
                for name in MODULES
            },
            "work_timeout_ms": 30000,
            "cleanup_timeout_ms": 5000,
        }
        args.working_directory.mkdir(parents=False, exist_ok=False)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2)
            stream.write("\n")
        LOGGER.info("Catalog launch receipt prepared; no process launched.")
        return 0
    except (OSError, ValueError):
        LOGGER.error("Catalog receipt preparation failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
