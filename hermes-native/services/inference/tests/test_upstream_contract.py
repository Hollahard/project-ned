"""Pinned upstream characterization using isolated AST functions, never runtime imports."""

import ast
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import ChunkStream
from pydantic import BaseModel, ConfigDict

from hermes_inference.sse import StreamLimits, events, validate_progress

PINNED = {
    "backends/exllamav3/model.py": "a41a2b2a692132f0b4fb503e4281430e93895b3e270904c37f39c842b68e5c48",
    "endpoints/core/types/model.py": "df617ef10f3eddcfa9ca7f1abd0db47220d9ff547f60cf62c96de96b2f683eeb",
    "endpoints/core/utils/model.py": "e906f02e99e202aa43bead8c0b70cd5eb46f2d061c84581157a8788f01baaab6",
}


@pytest.fixture
def upstream():
    location = os.environ.get("HERMES_TABBY_SOURCE")
    if not location:
        pytest.skip("Set HERMES_TABBY_SOURCE for pinned upstream AST characterization")
    root = Path(location)
    for relative, expected in PINNED.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    return root


def extract(root, relative, name, namespace, parent=None):
    path = root / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    candidates = tree.body
    if parent:
        candidates = next(
            item.body
            for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == parent
        )
    node = next(item for item in candidates if getattr(item, "name", None) == name)
    exec(compile(ast.Module([node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize(
    "requested,actual", [(1, 256), (255, 256), (257, 512), (2049, 2304), (256, 256), (2048, 2048)]
)
def test_actual_upstream_rounds_chunk_size(upstream, requested, actual):
    namespace = {"xlogger": SimpleNamespace(warning=lambda *args: None)}
    method = extract(
        upstream,
        "backends/exllamav3/model.py",
        "adjust_chunk_size",
        namespace,
        parent="ExllamaV3Container",
    )
    assert method(None, requested) == actual


@pytest.mark.parametrize(
    "raw,quantized",
    [("Q6", True), ("6,6", True), ("6, 6", True), ("q6", False), (" 6,6 ", False), ("FP16", False)],
)
def test_actual_cache_constructor_only_recognizes_exact_raw_modes(upstream, raw, quantized):
    layer_type = object()
    namespace = {
        "re": re,
        "Model": object,
        "CacheLayer_quant": layer_type,
        "Cache": lambda model, **kwargs: kwargs,
    }
    method = extract(
        upstream,
        "backends/exllamav3/model.py",
        "create_cache",
        namespace,
        parent="ExllamaV3Container",
    )
    fake = SimpleNamespace(
        draft_model=None,
        ngram_match_min=0,
        draft_num_tokens=None,
        max_batch_size=1,
        cache_size=4096,
    )
    arguments = method(fake, raw, object())
    assert (arguments.get("layer_type") is layer_type) is quantized
    if quantized:
        assert (arguments["k_bits"], arguments["v_bits"]) == (6, 6)


async def test_actual_stream_emits_processing_then_finished_for_each_component(upstream):
    namespace = {"BaseModel": BaseModel, "ConfigDict": ConfigDict}
    response_type = extract(
        upstream, "endpoints/core/types/model.py", "ModelLoadResponse", namespace
    )

    async def load_model_gen(*args, **kwargs):
        for component in ("vision", "draft", "model", "warmup"):
            yield 0, 2, component
            yield 1, 2, component
            yield 2, 2, component

    namespace = {
        "ModelLoadRequest": object,
        "ModelLoadResponse": response_type,
        "pathlib": SimpleNamespace(Path=Path),
        "asyncio": asyncio,
        "CancelledError": asyncio.CancelledError,
        "_load_tasks": set(),
        "config": SimpleNamespace(draft_model=SimpleNamespace(draft_model_dir="unused")),
        "model": SimpleNamespace(load_model_gen=load_model_gen),
        "get_generator_error": lambda message: json.dumps({"error": {"message": message}}),
        "handle_request_disconnect": lambda *args: None,
    }
    emitter = extract(upstream, "endpoints/core/utils/model.py", "stream_model_load", namespace)
    request = SimpleNamespace(model_dump=lambda **kwargs: {}, skip_queue=False)
    emitted = [value async for value in emitter(request, Path("unused"))]
    decoded = [json.loads(value) for value in emitted]
    assert [value["status"] for value in decoded] == ["processing", "processing", "finished"] * 4
    assert [value["model_type"] for value in decoded] == [
        component for component in ("vision", "draft", "model", "warmup") for _ in range(3)
    ]
    assert [value["module"] for value in decoded] == [1, 2, 2] * 4
    wire = b"".join(b"data: " + value.encode() + b"\r\n\r\n" for value in emitted)
    response = httpx.Response(200, stream=ChunkStream([bytes([value]) for value in wire]))
    parsed = [value async for value in events(response, StreamLimits())]
    assert parsed == decoded
    assert sum(validate_progress(value) for value in parsed) == 1
