"""Verify exact vendor inventory and optionally reconstruct both reviewed revisions."""

import argparse
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)
LIMIT = 1048576
LOG_COUNTS = {
    "src/client.rs": 2,
    "src/handshake/client.rs": 1,
    "src/protocol/mod.rs": 4,
    "src/protocol/frame/mod.rs": 2,
    "src/protocol/frame/frame.rs": 5,
}
PROGRESS_PATHS = {"src/protocol/mod.rs", "src/protocol/frame/mod.rs"}
ADDED_PATH = "src/protocol/progress.rs"


def read_bytes(path):
    if path.is_symlink() or path.is_junction():
        raise ValueError("Redirected vendor input")
    with path.open("rb") as stream:
        value = stream.read(LIMIT + 1)
    if len(value) > LIMIT:
        raise ValueError("Vendor file size limit")
    return value


def digest(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()


def text_digest(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > LIMIT:
        raise ValueError("Invalid patch text")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate receipt key")
        result[key] = value
    return result


def load_json(path):
    return json.loads(read_bytes(path), object_pairs_hook=unique_object)


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("Invalid receipt path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or any(part in (".", "..") for part in value.split("/"))
        or "\\" in value
        or ":" in value
        or relative.as_posix() != value
    ):
        raise ValueError("Invalid receipt path")
    return relative


def checked_path(root, value):
    path = root
    if path.is_symlink() or path.is_junction():
        raise ValueError("Redirected vendor root")
    for part in relative_path(value).parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError("Redirected vendor input")
    return path


def indexed(items, expected_count):
    if not isinstance(items, list) or len(items) != expected_count:
        raise ValueError("Receipt entry count differs")
    result = {}
    for item in items:
        key = relative_path(item["path"]).as_posix()
        if key in result:
            raise ValueError("Duplicate receipt path")
        result[key] = item
    return result


def verify(upstream=None):
    root = Path(__file__).resolve().parent
    vendor = root / "vendor/tungstenite"
    receipt = load_json(root / "vendor-patch-receipt.json")
    if (
        receipt["version"] != "0.30.0"
        or receipt["pack_revision"] != "hermes-progress-2"
    ):
        raise ValueError("Unexpected vendor identity")
    if receipt["log_revision_newline_mode"] != "lf_to_crlf_for_log_patch_files":
        raise ValueError("Unexpected log-safe1 byte transform")
    entries = indexed(receipt["files"], 28)
    observed = set()
    for path in vendor.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Redirected vendor inventory")
        if path.is_file():
            observed.add(path.relative_to(vendor).as_posix())
    if set(entries) != observed:
        raise ValueError("Vendor inventory differs")
    for relative, entry in entries.items():
        if digest(checked_path(vendor, relative)) != entry["output_sha256"]:
            raise ValueError("Vendor output differs")
        if relative == ADDED_PATH:
            if entry["input_sha256"] is not None:
                raise ValueError("Added file has an upstream preimage")
            if upstream is not None and checked_path(upstream, relative).exists():
                raise ValueError("Upstream unexpectedly contains added file")
        elif upstream is not None:
            if digest(checked_path(upstream, relative)) != entry["input_sha256"]:
                raise ValueError("Upstream input differs")
    logs = indexed(receipt["patches"], 5)
    if set(logs) != set(LOG_COUNTS):
        raise ValueError("Log patch scope differs")
    changed = {
        name
        for name, item in entries.items()
        if item["input_sha256"] != item["output_sha256"]
    }
    if changed != set(LOG_COUNTS) | {ADDED_PATH}:
        raise ValueError("Changed-file patch scope differs")
    for name, item in logs.items():
        calls = item["replaced_log_calls"]
        if not isinstance(calls, list) or len(calls) != LOG_COUNTS[name]:
            raise ValueError("Log patch count differs")
        if len(set(calls)) != len(calls):
            raise ValueError("Duplicate log patch")
        if item["input_sha256"] != entries[name]["input_sha256"]:
            raise ValueError("Log preimage differs")
    patch_path = root / "vendor-progress-patch.json"
    if digest(patch_path) != receipt["progress_patch_sha256"]:
        raise ValueError("Progress receipt differs")
    progress = load_json(patch_path)
    if (
        progress["schema"] != 1
        or progress["base_revision"] != "hermes-logsafe-1"
        or progress["revision"] != "hermes-progress-2"
        or progress["input_newline_mode"] != "crlf_to_lf_for_replacement_files"
    ):
        raise ValueError("Unexpected progress patch identity")
    replacements = progress["replacements"]
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 64:
        raise ValueError("Progress replacement count differs")
    paths = set()
    for item in replacements:
        name = relative_path(item["path"]).as_posix()
        paths.add(name)
        if (
            item["occurrences"] != 1
            or not item["before"]
            or text_digest(item["before"]) != item["before_sha256"]
            or text_digest(item["after"]) != item["after_sha256"]
        ):
            raise ValueError("Progress preimage differs")
    if paths != PROGRESS_PATHS:
        raise ValueError("Progress symbol-file scope differs")
    added = indexed(progress["added_files"], 1)
    if set(added) != {ADDED_PATH}:
        raise ValueError("Added progress scope differs")
    item = added[ADDED_PATH]
    if (
        text_digest(item["content"]) != item["sha256"]
        or item["sha256"] != entries[ADDED_PATH]["output_sha256"]
    ):
        raise ValueError("Added progress source differs")
    if upstream is not None:
        for name in LOG_COUNTS:
            value = read_bytes(checked_path(upstream, name)).decode("utf-8")
            for before in logs[name]["replaced_log_calls"]:
                if value.count(before) != 1:
                    raise ValueError("Log patch match differs")
                macro = before.split("!", 1)[0]
                if macro not in ("trace", "debug"):
                    raise ValueError("Unexpected log macro")
                value = value.replace(
                    before, macro + '!("WebSocket protocol event.");', 1
                )
            # Revision1 recorded its five edited outputs with CRLF bytes.
            # This historical transform is explicit, not text-reader normalization.
            if "\r" in value:
                raise ValueError("Unexpected upstream newline bytes")
            value = value.replace("\n", "\r\n")
            if text_digest(value) != logs[name]["output_sha256"]:
                raise ValueError("Log-safe1 reconstruction differs")
            if name in PROGRESS_PATHS:
                value = value.replace("\r\n", "\n")
            for replacement in replacements:
                if replacement["path"] != name:
                    continue
                if value.count(replacement["before"]) != 1:
                    raise ValueError("Progress symbol preimage match differs")
                value = value.replace(replacement["before"], replacement["after"], 1)
            if value.encode("utf-8") != read_bytes(checked_path(vendor, name)):
                raise ValueError("Progress reconstruction differs")
    return len(entries)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    try:
        count = verify(args.upstream)
        LOGGER.info("Vendor source receipt verified (%d files).", count)
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        LOGGER.error("Vendor source verification failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
