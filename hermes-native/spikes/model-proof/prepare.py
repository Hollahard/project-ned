"""Prepare a reviewed runtime snapshot; never import or launch an inference engine."""

import argparse
import hashlib
import importlib.util
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from inventory import inventory

PIN = "2fd6cc76203a66e13042daf7d76e5898b21c1ad8"
HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
LOG = logging.getLogger(__name__)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(source: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout


def runtime_interpreter(source: Path):
    """Bypass the Windows venv redirector, which injects PYTHONHOME despite -I."""
    config = source / ".venv" / "pyvenv.cfg"
    homes = [
        line.partition("=")[2].strip()
        for line in config.read_text().splitlines()
        if line.partition("=")[0].strip() == "home"
    ]
    if len(homes) != 1 or not Path(homes[0]).is_absolute():
        raise ValueError("Expected exactly one absolute runtime Python home")
    executable = Path(homes[0]) / "python.exe"
    if not executable.is_file():
        raise ValueError("Recorded base interpreter does not exist")
    return config, executable


def prepare(args) -> None:
    source, output, model = (p.resolve() for p in (args.source, args.output, args.model))
    if output.exists() or output.is_relative_to(source) or output.is_relative_to(model):
        raise ValueError("Output must be new and outside the installed source and model")
    if git(source, "rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("Installed Tabby commit differs from the reviewed pin")
    if git(source, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Installed tracked Tabby files are modified")
    model_inventory = inventory(model)
    if not model_inventory["shards_present_and_headers_consistent"]:
        raise ValueError("Selected model shards are incomplete or inconsistent")
    if model_inventory["tabby_override_exists"]:
        raise ValueError("Model-folder override is not allowed in this proof")
    output.mkdir(parents=True)
    runtime = output / "runtime"
    runtime.mkdir()
    archive = git(source, "archive", "--format=tar", PIN)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
        for member in source_tar.getmembers():
            relative = Path(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not (member.isfile() or member.isdir())
                or str(relative) in {"config.yml", "api_tokens.yml", ".env"}
            ):
                raise ValueError("Source archive contains a forbidden member")
        source_tar.extractall(runtime, filter="data")
    source_files = {
        str(p.relative_to(runtime)).replace("\\", "/"): sha256(p)
        for p in sorted(runtime.rglob("*"))
        if p.is_file()
    }
    builder = args.auth_stage.resolve() / "build_overlay.py"
    spec = importlib.util.spec_from_file_location("hermes_proof_overlay_builder", builder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    overlay_dir = output / "overlay"
    overlay = module.build_overlay(source, overlay_dir)
    if overlay.get("managed_contract_version") != "hermes-native-observation-v1":
        raise ValueError("Managed observation contract missing")
    for relative, expected in overlay["overlay_sha256"].items():
        origin = overlay_dir / relative
        if sha256(origin) != expected:
            raise ValueError("Overlay file hash mismatch")
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)
    shutil.copyfile(HERE / "bootstrap.py", output / "bootstrap.py")
    template = args.auth_stage.resolve() / "config" / "managed-tabby-v3.yml"
    shutil.copyfile(template, output / "managed-template.yml")
    site = source / ".venv" / "Lib" / "site-packages"
    extension = site / "exllamav3_ext.cp312-win_amd64.pyd"
    if not extension.is_file():
        raise ValueError("Required precompiled extension missing; JIT fallback forbidden")
    compiler = site / "triton" / "runtime" / "tcc" / "tcc.exe"
    cuda_toolkit = site / "triton" / "backends" / "nvidia"
    toolchain = [
        compiler,
        cuda_toolkit / "bin" / "ptxas.exe",
        cuda_toolkit / "include" / "cuda.h",
        cuda_toolkit / "lib" / "x64" / "cuda.lib",
    ]
    if not all(path.is_file() for path in toolchain):
        raise ValueError("Bundled Triton toolchain is incomplete")
    venv_config, interpreter = runtime_interpreter(source)
    model_files = {
        p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
        for p in model.iterdir()
        if p.is_file()
    }
    required_names = {item["name"] for item in model_inventory["shards"]}
    required_names.update(model_inventory["metadata_sha256"])
    for name in (
        "tokenizer.json",
        "quantization_config.json",
        "generation_config.json",
        "preprocessor_config.json",
        "processor_config.json",
        "tekken.json",
    ):
        if (model / name).is_file():
            required_names.add(name)
    model_hashes = {name: sha256(model / name) for name in sorted(required_names)}
    revision = hashlib.sha256(json.dumps(model_hashes, sort_keys=True).encode()).hexdigest()
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": PIN,
        "runtime_pack_id": overlay["runtime_pack_id"],
        "runtime": str(runtime),
        "source": str(source),
        "site_packages": str(site),
        "python": str(interpreter),
        "python_sha256": sha256(interpreter),
        "venv_config": {"path": str(venv_config), "sha256": sha256(venv_config)},
        "venv_redirector_used": False,
        "extension": {"path": str(extension), "sha256": sha256(extension)},
        "triton_toolchain": {
            "compiler": str(compiler),
            "cuda_path": str(cuda_toolkit),
            "files": {str(path): sha256(path) for path in toolchain},
        },
        "source_files": source_files,
        "runtime_files": {
            str(p.relative_to(runtime)).replace("\\", "/"): sha256(p)
            for p in sorted(runtime.rglob("*"))
            if p.is_file()
        },
        "overlay": overlay,
        "builder_sha256": sha256(builder),
        "bootstrap_sha256": sha256(output / "bootstrap.py"),
        "template_sha256": sha256(output / "managed-template.yml"),
        "model": str(model),
        "model_inventory": model_inventory,
        "model_files_before": model_files,
        "model_required_sha256": model_hashes,
        "model_revision_sha256": revision,
        "limitations": [
            "Dependency environment is reused read-only, not fully hashed",
            "Filesystem attestation does not enforce immutable weights",
        ],
    }
    (output / "prepared.json").write_text(json.dumps(manifest, indent=2) + "\n")
    LOG.info("Prepared verified snapshot and model receipt at %s", output)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate main project virtual environment")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--auth-stage", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
