"""One-shot metadata inspector: finite pinned source modules and stdlib only."""

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

MODULES = ("__init__", "catalog", "common", "paths", "tensors")


class SourceOnly(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root, pins):
        if set(pins) != {f"{name}.py" for name in MODULES}:
            raise ValueError("Invalid source set")
        self.sources = {}
        for name in MODULES:
            path = root / "hermes_model_catalog" / f"{name}.py"
            for component in (path, *path.parents):
                if component.is_symlink() or component.is_junction():
                    raise ValueError("Redirected source")
            with path.open("rb") as stream:
                source = stream.read(1048577)
            if (
                len(source) > 1048576
                or hashlib.sha256(source).hexdigest() != pins[path.name]
            ):
                raise ValueError("Changed source")
            key = (
                "hermes_model_catalog"
                if name == "__init__"
                else f"hermes_model_catalog.{name}"
            )
            self.sources[key] = (path, source)

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.sources:
            if fullname.split(".")[0] == "hermes_model_catalog":
                raise ModuleNotFoundError("Outside source contract")
            return None
        source, _ = self.sources[fullname]
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
        path, source = self.sources[module.__name__]
        exec(compile(source, str(path), "exec", dont_inherit=True), module.__dict__)  # noqa: S102 - only the exact pinned source bytes


def compact(report):
    issues = report["issues"]
    return {
        "schema": 1,
        "model": report["model"],
        "status": report["status"],
        "format": report["format"],
        "declared_architectures": report["architecture"].get("declared", []),
        "declared_bits": report["quantization"].get("bits"),
        "observed_shard_count": len(report["shards"]),
        "observed_tensor_count": report["observed_tensor_count"],
        "index_tensor_count": report["index_tensor_count"],
        "missing_shards": report["missing_shards"],
        "metadata_fingerprint": report["metadata_fingerprint"],
        "fingerprint_partial": report["fingerprint_partial"],
        "fingerprint_scope": report["fingerprint_scope"],
        "issues": issues[:32],
        "issues_truncated": len(issues) > 32
        or any(item["code"] == "ISSUE_OUTPUT_LIMIT" for item in issues),
        "bytes_read": report["bytes_read"],
        "runtime_compatible": None,
        "load_certified": False,
        "weights_content_hashed": False,
        "weight_payload_bytes_read": 0,
    }


def encode_report(report):
    """Bound the frame without ever dropping a missing-shard name."""

    def encode():
        return (
            json.dumps(
                report, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )

    output = encode()
    while len(output) > 65536 and report["issues"]:
        report["issues"].pop()
        report["issues_truncated"] = True
        output = encode()
    if len(output) > 65536:
        raise ValueError("Output limit")
    return output


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr
    )
    try:
        if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
            raise ValueError("Isolation flags required")
        parser = argparse.ArgumentParser(allow_abbrev=False)
        parser.add_argument("--catalog-src", required=True)
        parser.add_argument("--source-pins", required=True)
        parser.add_argument("--root", required=True)
        parser.add_argument("--model", required=True)
        args = parser.parse_args()
        sys.meta_path.insert(
            0, SourceOnly(Path(args.catalog_src), json.loads(args.source_pins))
        )
        from hermes_model_catalog import inspect_model

        report = compact(inspect_model(Path(args.root), args.model).as_dict())
        output = encode_report(report)
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    except Exception:  # noqa: BLE001 - private child boundary emits only a static error
        LOGGER.error("Catalog inspection failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
