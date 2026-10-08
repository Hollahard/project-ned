"""Verify the pinned local vendor inventory; optionally reconstruct from upstream."""

import argparse
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)


def digest(path):
    if path.is_symlink() or path.is_junction():
        raise ValueError("Redirected vendor input")
    with path.open("rb") as stream:
        value = stream.read(1048577)
    if len(value) > 1048576:
        raise ValueError("Vendor file size limit")
    return hashlib.sha256(value).hexdigest()


def verify(upstream=None):
    root = Path(__file__).resolve().parent
    vendor = root / "vendor/tungstenite"
    receipt = json.loads(
        (root / "vendor-patch-receipt.json").read_text(encoding="utf-8")
    )
    if receipt["version"] != "0.30.0" or receipt["pack_revision"] != "hermes-logsafe-1":
        raise ValueError("Unexpected vendor identity")
    expected = {entry["path"] for entry in receipt["files"]}
    observed = {
        path.relative_to(vendor).as_posix()
        for path in vendor.rglob("*")
        if path.is_file()
    }
    if expected != observed or len(expected) > 128:
        raise ValueError("Vendor inventory differs")
    for entry in receipt["files"]:
        relative = PurePosixPath(entry["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in str(relative)
            or ":" in str(relative)
        ):
            raise ValueError("Invalid receipt path")
        if digest(vendor / relative) != entry["output_sha256"]:
            raise ValueError("Vendor output differs")
        if (
            upstream is not None
            and digest(upstream / relative) != entry["input_sha256"]
        ):
            raise ValueError("Upstream input differs")
    changed = {
        item["path"]
        for item in receipt["files"]
        if item["input_sha256"] != item["output_sha256"]
    }
    if changed != {item["path"] for item in receipt["patches"]} or len(changed) != 5:
        raise ValueError("Patch scope differs")
    if upstream is not None:
        for item in receipt["patches"]:
            value = (upstream / item["path"]).read_text(encoding="utf-8")
            for before in item["replaced_log_calls"]:
                if value.count(before) != 1:
                    raise ValueError("Log patch match differs")
                macro = before.split("!", 1)[0]
                value = value.replace(
                    before, macro + '!("WebSocket protocol event.");', 1
                )
            if value != (vendor / item["path"]).read_text(encoding="utf-8"):
                raise ValueError("Protocol changed outside log replacements")
    return len(expected)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    try:
        count = verify(args.upstream)
        LOGGER.info("Vendor source receipt verified (%d files).", count)
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.error("Vendor source verification failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
