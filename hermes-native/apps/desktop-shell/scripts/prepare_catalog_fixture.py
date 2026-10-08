"""Create only fresh synthetic model folders for the native catalog fixture."""

import argparse
import hashlib
import json
import logging
import os
import struct
from pathlib import Path

LOG = logging.getLogger(__name__)


def prepare(root: Path) -> None:
    if not root.is_absolute() or root.exists():
        raise ValueError("An absolute new synthetic fixture directory is required")
    root.mkdir(parents=True)
    models = root / "models"
    models.mkdir()
    config = {
        "architectures": ["LlamaForCausalLM"],
        "model_type": "llama",
        "quantization_config": {"quant_method": "exl3", "bits": 5},
    }
    header = json.dumps(
        {"layer.trellis": {"dtype": "I16", "shape": [2], "data_offsets": [0, 4]}}
    ).encode()
    shard = struct.pack("<Q", len(header)) + header + b"\0\0\0\0"
    for name in ("complete", "partial", "invalid"):
        model = models / name
        model.mkdir()
        (model / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (models / "complete/model.safetensors").write_bytes(shard)
    (models / "partial/model-00001-of-00002.safetensors").write_bytes(shard)
    (models / "partial/model.safetensors.index.json").write_text(
        json.dumps(
            {
                "metadata": {"total_size": 8},
                "weight_map": {
                    "layer.trellis": "model-00001-of-00002.safetensors",
                    "other.trellis": "model-00002-of-00002.safetensors",
                },
            }
        ),
        encoding="utf-8",
    )
    (models / "invalid/config.json").write_text(
        '{"duplicate":1,"duplicate":2}', encoding="utf-8"
    )
    (root / "outside").mkdir()
    receipt = {
        "kind": "synthetic-native-catalog-fixture-v1",
        "files": {
            path.relative_to(root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in models.rglob("*")
            if path.is_file()
        },
    }
    (root / "fixture-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate the project virtual environment")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.root)
    LOG.info("Created synthetic metadata fixtures; no runtime or model was loaded")


if __name__ == "__main__":
    main()
