"""Read model metadata and bounded safetensors headers without importing a runtime."""

import argparse
import hashlib
import json
import logging
import os
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(model: Path) -> dict:
    config_path = model / "config.json"
    index_path = model / "model.safetensors.index.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))["weight_map"]
    shards = []
    for name in sorted(set(index.values())):
        path = model / name
        if path.parent != model or path.resolve().parent != model.resolve():
            raise ValueError("Inventory refuses nested or redirected shard paths")
        shard = {"name": name, "exists": path.is_file()}
        if path.is_file():
            size = path.stat().st_size
            with path.open("rb") as handle:
                header_length = struct.unpack("<Q", handle.read(8))[0]
                if not 2 <= header_length <= min(64 * 1024 * 1024, size - 8):
                    raise ValueError("Invalid or oversized safetensors header")
                header_bytes = handle.read(header_length)
            header = json.loads(header_bytes)
            tensors = {k: v for k, v in header.items() if k != "__metadata__"}
            expected = {k for k, v in index.items() if v == name}
            offsets_valid = all(
                0
                <= value["data_offsets"][0]
                <= value["data_offsets"][1]
                <= size - 8 - header_length
                for value in tensors.values()
            )
            shard.update(
                bytes=size,
                header_bytes=header_length,
                header_sha256=hashlib.sha256(header_bytes).hexdigest(),
                tensor_count=len(tensors),
                index_keys_match=expected == set(tensors),
                data_offsets_in_bounds=offsets_valid,
                dtype_counts=dict(Counter(v["dtype"] for v in tensors.values())),
            )
        shards.append(shard)
    complete = all(
        item["exists"] and item["index_keys_match"] and item["data_offsets_in_bounds"]
        for item in shards
    )
    immediate_files = [p for p in model.iterdir() if p.is_file()]
    return {
        "path": str(model),
        "architecture": config.get("architectures"),
        "model_type": config.get("model_type"),
        "quantization": config.get("quantization_config"),
        "immediate_file_bytes": sum(p.stat().st_size for p in immediate_files),
        "available_shard_bytes": sum(p.get("bytes", 0) for p in shards),
        "shards_present_and_headers_consistent": complete,
        "weight_payloads_hashed_or_verified": False,
        "tabby_override_exists": (model / "tabby_config.yml").exists(),
        "metadata_sha256": {
            path.name: digest(path)
            for path in (config_path, index_path, model / "tokenizer_config.json")
            if path.is_file()
        },
        "shards": shards,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("VIRTUAL_ENV"):
        raise RuntimeError("Activate the main project virtual environment first")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    models = [inventory(p) for p in sorted(args.models.iterdir()) if p.is_dir()]
    report = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Metadata and bounded headers only; no engine, GPU load, or weight hash",
        "models": models,
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    LOG.info("Inventoried %d model directories; report %s", len(models), args.output)


if __name__ == "__main__":
    main()
