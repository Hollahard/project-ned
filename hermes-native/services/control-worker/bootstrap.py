"""Owned CPU worker entry: only explicit source roots and Python's stdlib."""

import argparse
import importlib.abc
import importlib.util
import logging
import os
import sys
from pathlib import Path


class SourceOnlyPackages(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Finite source modules only: -B alone does not prevent cached bytecode reads."""

    def __init__(self, own_source: Path, inference_source: Path):
        self.modules = {}
        groups = (
            ("hermes_control_worker", own_source, ("errors", "profiles", "state", "protocol")),
            ("hermes_inference", inference_source, ("admission", "profiles", "errors")),
        )
        for package, root, names in groups:
            for name in ("__init__", *names):
                key = package if name == "__init__" else f"{package}.{name}"
                path = root / package / f"{name}.py"
                checked_directory(str(path.parent))
                if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
                    raise ValueError("Required source-only module is unavailable")
                self.modules[key] = path

    def find_spec(self, fullname, path=None, target=None):
        source = self.modules.get(fullname)
        if source is None:
            if fullname.split(".")[0] in ("hermes_control_worker", "hermes_inference"):
                raise ModuleNotFoundError(
                    "Module is outside the pure control-worker import contract"
                )
            return None
        return importlib.util.spec_from_file_location(
            fullname,
            source,
            loader=self,
            submodule_search_locations=[str(source.parent)]
            if source.name == "__init__.py"
            else None,
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = self.modules[module.__name__]
        code = compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
        exec(code, module.__dict__)


def checked_directory(raw: str) -> Path:
    value = Path(raw)
    if not value.is_absolute() or not value.is_dir():
        raise ValueError("Explicit existing directory required")
    for component in (value, *value.parents):
        if component.is_symlink() or component.is_junction():
            raise ValueError("Redirected directory is not permitted")
    return value.resolve(strict=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
            raise ValueError("Isolated no-site no-bytecode flags required")
        if any(name.upper().startswith(("PYTHON", "TABBY_")) for name in os.environ):
            raise ValueError("Ambient interpreter/runtime configuration is forbidden")
        parser = argparse.ArgumentParser(allow_abbrev=False)
        parser.add_argument("--inference-src", required=True)
        parser.add_argument("--state-dir", required=True)
        args = parser.parse_args()
        source = checked_directory(args.inference_src)
        own_source = checked_directory(str(Path(__file__).resolve().parent / "src"))
        state = checked_directory(args.state_dir)
        if state != Path.cwd().resolve() or any(
            state.is_relative_to(root) or root.is_relative_to(state)
            for root in (source, own_source)
        ):
            raise ValueError("State must be a separate explicit working directory")
        for name in ("__init__.py", "profiles.py", "errors.py"):
            path = source / "hermes_inference" / name
            if not path.is_file() or path.is_symlink():
                raise ValueError("Inference source is incomplete")
        # -I -S starts with only the trusted standard-library paths. A finite
        # source-only finder keeps .pyc/.pyd shadows out of the two source roots.
        sys.meta_path.insert(0, SourceOnlyPackages(own_source, source))
        from hermes_control_worker.protocol import serve
        from hermes_control_worker.state import StateLease

        with StateLease(state):
            return serve(state, sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
        logging.error("Control worker startup or state failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
