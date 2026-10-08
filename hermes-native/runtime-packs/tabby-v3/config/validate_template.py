"""Validate the inactive template using only the pinned, pure Pydantic schema."""

import argparse
import hashlib
import importlib.util
import logging
import sys
from pathlib import Path

import yaml

SCHEMA_SHA256 = "01d9716310462ca435abb2e0e218cc0774a594380c4ee9725fe2188a51facf68"
TEMPLATE = Path(__file__).with_name("managed-tabby-v3.yml")
logger = logging.getLogger(__name__)


def validate(schema_path: Path) -> None:
    contents = schema_path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != SCHEMA_SHA256:
        raise ValueError("The upstream configuration schema does not match its pin")
    # The exact pinned file imports only typing and Pydantic. Do not import
    # common.tabby_config, Torch, any engine, or the live application.
    name = "hermes_pinned_config_schema_validation"
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(contents, str(schema_path), "exec"), module.__dict__)  # noqa: S102
        values = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        defaults = module.TabbyConfigModel()
        for section, settings in values.items():
            if section not in type(defaults).model_fields:
                raise ValueError("Unknown template section")
            if set(settings) - set(type(getattr(defaults, section)).model_fields):
                raise ValueError("Unknown template field")
        effective = module.TabbyConfigModel.model_validate(values)
        expected = {
            "network": {
                "host": "127.0.0.1",
                "disable_auth": False,
                "allowed_origins": [],
                "access_log": False,
                "send_tracebacks": False,
            },
            "model": {"model_name": "", "inline_model_loading": False},
            "draft_model": {"draft_model_name": "", "draft_mode": "disabled"},
            "embeddings": {"embedding_model_name": "", "embeddings_device": "cpu"},
            "logging": {
                "log_prompt": False,
                "log_generation_params": False,
                "log_requests": False,
                "log_chat_completion_requests": False,
            },
            "developer": {"seqlog": False, "unsafe_launch": False},
        }
        for section, settings in expected.items():
            for field, value in settings.items():
                if values.get(section, {}).get(field) != value:
                    raise ValueError("Managed startup policy must be explicit")
                if getattr(getattr(effective, section), field) != value:
                    raise ValueError("Managed startup policy validation failed")
    finally:
        sys.modules.pop(name, None)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(args.schema)
    except (OSError, ValueError) as error:
        logger.error("Managed template validation failed: %s", error)
        return 1
    logger.info("Managed template matches the pinned V3 schema and startup policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
