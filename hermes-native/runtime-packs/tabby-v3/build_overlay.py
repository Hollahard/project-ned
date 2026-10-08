"""Build a reviewable overlay in a NEW directory; never modify the source pack."""

import argparse
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "2fd6cc76203a66e13042daf7d76e5898b21c1ad8"
MANAGED_CONTRACT_VERSION = "hermes-native-observation-v1"
RUNTIME_PACK_ID = f"tabby-v3:{UPSTREAM_COMMIT}:{MANAGED_CONTRACT_VERSION}"
SOURCE_HASHES = {
    "common/auth.py": "1c8e3bc8ed3cb30546792ce452108f63c88d65f402c4ad8e276e1e8b96585812",
    "common/networking.py": "aab6ded86e036fdede6768aaa468579da4549c20d8f0b7bd52bbf3ffb3311450",
    "endpoints/core/types/model.py": "df617ef10f3eddcfa9ca7f1abd0db47220d9ff547f60cf62c96de96b2f683eeb",
    "backends/exllamav3/model.py": "a41a2b2a692132f0b4fb503e4281430e93895b3e270904c37f39c842b68e5c48",
    "LICENSE": "6f1e622c82a380075843bb084a7ec3b1f1d12a4a02526d75e78b0924a860aa75",
}
SAFE_REQUEST_LOG = '''async def log_request(request: Request):
    """Managed pack: record method only, never credentials or request content."""
    # Header dictionaries, URL queries, route parameters and bodies can contain
    # secrets. Do not hand the raw ASGI request to structured logging either.
    method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
    xlogger.info("Request", {"method": method}, details=f"HTTP {method} request")


'''


def add_observation_field(contents: bytes, *, backend: bool) -> bytes:
    """Insert the managed field only at the verified upstream declaration/call."""
    source = contents.decode("utf-8")
    newline = "\r\n" if "\r\n" in source else "\n"
    if backend:
        anchor = "            use_vision=self.use_vision," + newline
        addition = (
            "            hermes_native_draft_enabled=bool("
            "self.use_draft_model or self.ngram_match_min > 0)," + newline
        )
    else:
        anchor = '    draft: Optional["ModelCard"] = None' + newline
        addition = (
            "    # Managed observation: stock draft=None is not proof drafting is disabled."
            + newline
            + "    hermes_native_draft_enabled: Optional[bool] = None"
            + newline
        )
    if source.count(anchor) != 1:
        raise ValueError("Pinned managed-observation insertion point changed")
    return source.replace(anchor, anchor + addition, 1).encode("utf-8")


def build_overlay(source: Path, output: Path) -> dict:
    source, output = source.resolve(strict=True), output.resolve()
    if (
        output.exists()
        or output.is_relative_to(source)
        or source.is_relative_to(output)
    ):
        raise ValueError("Output must be a new directory outside the source runtime")
    contents = {}
    for relative, expected in SOURCE_HASHES.items():
        value = (source / relative).read_bytes()
        if hashlib.sha256(value).hexdigest() != expected:
            raise ValueError(f"Pinned upstream file changed: {relative}")
        contents[relative] = value
    networking = contents["common/networking.py"].decode("utf-8")
    begin = networking.index("async def log_request(request: Request):")
    end = networking.index("def get_global_depends():", begin)
    networking = networking[:begin] + SAFE_REQUEST_LOG + networking[end:]
    files = {
        "common/auth.py": (HERE / "overlay/common/auth.py").read_bytes(),
        "common/networking.py": networking.encode("utf-8"),
        "endpoints/core/types/model.py": add_observation_field(
            contents["endpoints/core/types/model.py"], backend=False
        ),
        "backends/exllamav3/model.py": add_observation_field(
            contents["backends/exllamav3/model.py"], backend=True
        ),
        "UPSTREAM-LICENSE.txt": contents["LICENSE"],
    }
    # Compile modules without importing any inference/runtime dependency.
    for relative, contents in files.items():
        if relative.endswith(".py"):
            compile(contents, relative, "exec")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "upstream_commit": UPSTREAM_COMMIT,
        "managed_contract_version": MANAGED_CONTRACT_VERSION,
        "runtime_pack_id": RUNTIME_PACK_ID,
        "effective_observation_fields": ["parameters.hermes_native_draft_enabled"],
        "source_sha256": SOURCE_HASHES,
        "overlay_sha256": {
            key: hashlib.sha256(value).hexdigest() for key, value in files.items()
        },
    }
    for relative, value in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)
    (output / "overlay-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "Built pinned authentication/observation overlay containing %d files",
        len(files),
    )
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_overlay(args.source, args.output)
    except (OSError, ValueError) as error:
        logger.error("Overlay build failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
