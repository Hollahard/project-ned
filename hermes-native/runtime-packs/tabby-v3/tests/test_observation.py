"""Execute selected hash-verified upstream AST nodes, never engine imports or CUDA."""

import ast
import hashlib
import os
from pathlib import Path, PureWindowsPath
from time import time
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from pydantic import BaseModel, Field

import build_overlay as builder


@pytest.fixture
def upstream(tmp_path):
    location = os.environ.get("HERMES_TABBY_SOURCE")
    if not location:
        pytest.skip("Set HERMES_TABBY_SOURCE for pinned upstream AST characterization")
    source = Path(location)
    output = tmp_path / "managed-overlay"
    manifest = builder.build_overlay(source, output)
    for relative, expected in manifest["source_sha256"].items():
        assert hashlib.sha256((source / relative).read_bytes()).hexdigest() == expected
    return source, output


def selected_model_info(root):
    namespace = {
        "BaseModel": BaseModel,
        "Field": Field,
        "Optional": Optional,
        "time": time,
        "LoggingConfig": Any,
    }
    path = root / "endpoints/core/types/model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for name in ("ModelCardParameters", "ModelCardMeta", "ModelCard"):
        node = next(
            item
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == name
        )
        # Hash-verified pinned declaration only; no upstream module imports execute.
        exec(compile(ast.Module([node], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    namespace["ModelCardParameters"].model_rebuild(_types_namespace=namespace)
    namespace["read_model_meta"] = lambda *args, **kwargs: None
    path = root / "backends/exllamav3/model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    container = next(
        item
        for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "ExllamaV3Container"
    )
    method = next(
        item
        for item in container.body
        if isinstance(item, ast.FunctionDef) and item.name == "model_info"
    )
    # Hash-verified model_info only, with filesystem metadata replaced by a harmless stub.
    exec(compile(ast.Module([method], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return namespace["model_info"]


@pytest.mark.parametrize(
    "draft,ngram,expected", [(False, 0, False), (True, 0, True), (False, 2, True)]
)
def test_actual_stock_card_hides_draft_state_but_managed_card_reports_it(
    upstream, draft, ngram, expected
):
    source, output = upstream
    fake = SimpleNamespace(
        max_seq_len=4096,
        cache_size=4096,
        max_batch_size=1,
        cache_mode="FP16",
        chunk_size=2048,
        use_vision=False,
        prompt_template=None,
        model_dir=PureWindowsPath(r"G:\resolved\Real-Model"),
        use_draft_model=draft,
        ngram_match_min=ngram,
    )
    stock = selected_model_info(source)(fake).model_dump()
    assert stock["parameters"]["draft"] is None
    assert "hermes_native_draft_enabled" not in stock["parameters"]
    managed = selected_model_info(output)(fake).model_dump()
    assert managed["parameters"]["hermes_native_draft_enabled"] is expected
    assert managed["id"] == "Real-Model"
    # The overlay adds an observation only; existing response fields retain their values.
    del managed["parameters"]["hermes_native_draft_enabled"]
    managed.pop("created")
    stock.pop("created")
    assert managed == stock
