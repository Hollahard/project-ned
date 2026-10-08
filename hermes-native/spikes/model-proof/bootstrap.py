"""Owned child entry. Runtime imports happen only after isolation and native preflight."""

import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import runpy
import sys
from pathlib import Path

STAGE = "start"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    global STAGE
    STAGE = "receipt"
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / "prepared.json").read_text())
    runtime = Path(receipt["runtime"])
    site = Path(receipt["site_packages"])
    STAGE = "python_interpreter"
    if Path(sys.executable).resolve() != Path(receipt["python"]).resolve():
        raise RuntimeError("Unexpected base interpreter")
    if digest(Path(sys.executable)) != receipt["python_sha256"]:
        raise RuntimeError("Base interpreter hash mismatch")
    STAGE = "python_flags"
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        raise RuntimeError("Required isolated Python flags missing")
    STAGE = "working_directory"
    if Path.cwd() != runtime or (runtime / "config.yml").exists():
        raise RuntimeError("Unreviewed working-directory configuration")
    STAGE = "environment_policy"
    if any(name.startswith(("TABBY_", "PYTHON")) for name in os.environ):
        raise RuntimeError("Ambient configuration variables forbidden")
    STAGE = "arguments"
    preflight_only = len(sys.argv) == 4 and sys.argv[-1] == "--preflight-only"
    if (
        len(sys.argv) not in (3, 4)
        or sys.argv[1] != "--config"
        or (len(sys.argv) == 4 and not preflight_only)
    ):
        raise RuntimeError("Unexpected bootstrap arguments")
    config = Path(sys.argv[2]).resolve()
    if config != root / "managed.json":
        raise RuntimeError("Unexpected config location")
    STAGE = "source_hashes"
    for relative, expected in receipt["runtime_files"].items():
        if digest(runtime / relative) != expected:
            raise RuntimeError("Managed runtime hash changed")
    # Do not call site.main or addsitedir: both execute installed .pth hooks.
    sys.path.insert(0, str(runtime))
    sys.path.append(str(site))
    STAGE = "triton_toolchain"
    toolchain = receipt["triton_toolchain"]
    if (
        os.environ.get("CC") != toolchain["compiler"]
        or os.environ.get("CUDA_PATH") != toolchain["cuda_path"]
    ):
        raise RuntimeError("Unexpected Triton toolchain environment")
    for name, expected in toolchain["files"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("Triton toolchain hash mismatch")
    STAGE = "native_extension_resolution"
    extension = Path(receipt["extension"]["path"])
    spec = importlib.util.find_spec("exllamav3_ext")
    if (
        spec is None
        or spec.origin is None
        or Path(spec.origin).resolve() != extension
        or not any(spec.origin.endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES)
        or digest(extension) != receipt["extension"]["sha256"]
    ):
        raise RuntimeError("Precompiled extension mismatch; JIT fallback forbidden")
    STAGE = "metadata_receipt"
    (root / "bootstrap-proof.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "preflight_only": preflight_only,
                "engine_imported_at_preflight": False,
                "python_executable": sys.executable,
                "python_version": sys.version.split()[0],
                "installed_versions": {
                    item.metadata["Name"]: item.version
                    for item in importlib.metadata.distributions(path=[str(site)])
                    if item.metadata["Name"].lower()
                    in {
                        "torch",
                        "exllamav3",
                        "triton-windows",
                        "transformers",
                        "fastapi",
                        "uvicorn",
                    }
                },
                "native_extension_preflight": True,
                "runtime_source_verified": True,
                "isolated": True,
                "bytecode_disabled": True,
                "site_hooks_disabled": True,
            },
            indent=2,
        )
    )
    if preflight_only:
        return
    STAGE = "runtime_entry"
    sys.argv = [str(runtime / "main.py"), "--config", str(config)]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        # No exception values/traceback or environment values in the public report.
        frames = []
        frame = error.__traceback__
        while frame is not None:
            if Path(frame.tb_frame.f_code.co_filename).name == "bootstrap.py":
                frames.append(frame.tb_lineno)
            frame = frame.tb_next
        (Path(__file__).resolve().parent / "bootstrap-exit.json").write_text(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "fixed_stage": STAGE,
                    "bootstrap_line_numbers": frames,
                }
            )
        )
        raise
