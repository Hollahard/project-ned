"""Tests for VRAM Preflight sizing guard and recommendation engine."""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from friday.api.app import create_app
from friday.config import FridayConfig, ServerSettings, StorageSettings
from friday.inference.mock import MockInferenceBackend
from friday.inference.preflight import (
    parse_model_params,
    calculate_model_vram_mb,
    check_vram_preflight,
    PreflightResult,
)


def test_parse_model_params():
    params, bpw, layers, heads, dim = parse_model_params("Mistral-Small-3.1-24B-Instruct-2503-exl3")
    assert params == 24.0
    assert bpw == 6.0
    assert layers == 56

    params_qwen, bpw_qwen, _, _, _ = parse_model_params("Qwen3-30B-A3B-Instruct-2507")
    assert params_qwen == 30.0
    assert bpw_qwen == 4.5

    # Heuristic fallback for unknown model
    params_unk, _, layers_unk, _, _ = parse_model_params("DeepSeek-R1-Distill-Llama-70B-exl3")
    assert params_unk == 70.0
    assert layers_unk == 80


def test_calculate_model_vram_and_quantization_modes():
    # 24B model with 32K context
    w_mb, kv_fp16, tot_fp16 = calculate_model_vram_mb(
        "Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=32768,
        kv_cache_dtype="fp16",
    )
    _, kv_q8, tot_q8 = calculate_model_vram_mb(
        "Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=32768,
        kv_cache_dtype="q8",
    )
    _, kv_q6, tot_q6 = calculate_model_vram_mb(
        "Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=32768,
        kv_cache_dtype="q6",
    )
    _, kv_q4, tot_q4 = calculate_model_vram_mb(
        "Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=32768,
        kv_cache_dtype="q4",
    )

    assert w_mb > 15000.0
    # Higher precision KV cache requires more memory
    assert kv_fp16 > kv_q8 > kv_q6 > kv_q4
    assert tot_fp16 > tot_q8 > tot_q6 > tot_q4


def test_check_vram_preflight_fits_on_rtx_5090():
    result = check_vram_preflight(
        model_name="Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=32768,
        kv_cache_dtype="q6",
        available_vram_mb=32607.0,
    )
    assert isinstance(result, PreflightResult)
    assert result.fits is True
    assert result.headroom_mb > 0.0
    assert "PASSED" in result.message


def test_check_vram_preflight_fails_and_recommends_fallback():
    # 1. Base weights exceeding budget: 70B model on 24 GB card
    result_oversize = check_vram_preflight(
        model_name="Llama-3-70B-Instruct-exl3",
        context_length=65536,
        kv_cache_dtype="fp16",
        available_vram_mb=24000.0,
        safety_margin_mb=1000.0,
    )
    assert result_oversize.fits is False
    assert result_oversize.headroom_mb < 0.0
    assert "FAILED" in result_oversize.message
    assert "Recommendation" in result_oversize.message

    # 2. Context/cache exceeding budget: 24B model with 64K FP16 context on 24 GB card
    # Base weights (18 GB) fit, so reducing context/cache produces a recommended fallback
    result_context_rec = check_vram_preflight(
        model_name="Mistral-Small-3.1-24B-Instruct-2503-exl3",
        context_length=65536,
        kv_cache_dtype="fp16",
        available_vram_mb=24000.0,
        safety_margin_mb=1000.0,
    )
    assert result_context_rec.fits is False
    assert result_context_rec.recommended_context is not None
    assert result_context_rec.recommended_kv_cache in ["q6", "q4"]
    assert "Recommendation: Reduce context" in result_context_rec.message


@pytest.fixture
def test_app(tmp_path: Path):
    db_file = tmp_path / "test_state.db"
    config = FridayConfig(
        server=ServerSettings(host="127.0.0.1", port=8200),
        storage=StorageSettings(database_path=str(db_file)),
    )
    mock_inference = MockInferenceBackend()
    return create_app(config=config, inference=mock_inference)


@pytest.mark.asyncio
async def test_preflight_route(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8200") as client:
        resp = await client.post(
            "/api/v1/models/preflight",
            json={
                "model_name": "Mistral-Small-3.1-24B-Instruct-2503-exl3",
                "context_length": 32768,
                "kv_cache_dtype": "q6",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "fits" in data
        assert "estimated_weights_mb" in data
        assert "headroom_mb" in data
        assert "message" in data
