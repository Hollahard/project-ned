"""Package a verified retained build into a new private native asset directory."""

import argparse
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

PIN = "649d6c0391029f35959cfbc240eb3534a6667cf5"
SOURCE_HASH = "7a6c24f0b7dd1383baac61169eafedb7cb212229f1775b9eb667b6a167e7b968"
LOG = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate the project virtual environment")
    parser = argparse.ArgumentParser()
    parser.add_argument("--renderer-dist", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "frontend"
    )
    args = parser.parse_args()
    source = args.renderer_dist.resolve(strict=True)
    output = args.output.resolve()
    if (
        output.exists()
        or output.is_relative_to(source)
        or source.is_relative_to(output)
    ):
        raise ValueError(
            "Native assets must use a new directory outside the renderer build"
        )
    baseline = json.loads((source / "feasibility-report.json").read_text())
    if (
        baseline.get("revision") != PIN
        or baseline.get("sourceSha256") != SOURCE_HASH
        or baseline.get("upstreamInputsUnchanged") is not True
    ):
        raise ValueError("Renderer baseline differs from the verified source")
    inputs = []
    for path in source.rglob("*"):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError("Redirected renderer asset")
        if path.is_file():
            inputs.append((path.relative_to(source), path))
    if sum(path.stat().st_size for _, path in inputs) > 512 * 1024 * 1024:
        raise ValueError("Renderer assets exceed the bounded packaging size")
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    inputs += [
        (Path(name), fixtures / name)
        for name in (
            "binding-proof.html",
            "binding-proof.js",
            "preview-proof.html",
            "preview-proof-entry.js",
            "preview-watch-proof.js",
            "preview-observer.html",
            "preview-observer.js",
            "preview-reload-proof.html",
            "preview-reload-proof.js",
            "control-create-proof.html",
            "control-reopen-proof.html",
            "control-unavailable-proof.html",
            "control-proof.js",
            "control-expected.json",
        )
    ]
    hashes = {}
    output.mkdir(parents=True)
    for relative, origin in inputs:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = hashlib.sha256(origin.read_bytes()).hexdigest()
        shutil.copyfile(origin, destination)
        if (
            before != hashlib.sha256(destination.read_bytes()).hexdigest()
            or before != hashlib.sha256(origin.read_bytes()).hexdigest()
        ):
            raise RuntimeError("Renderer asset changed during packaging")
        hashes[relative.as_posix()] = before
    receipt = {
        "upstream_revision": PIN,
        "retained_source_sha256": SOURCE_HASH,
        "asset_sha256": hashes,
        "visual_parity_verified": False,
        "runtime_owner_connected": False,
    }
    (output / "native-asset-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    LOG.info("Packaged %s verified retained/native fixture assets", len(hashes))


if __name__ == "__main__":
    main()
