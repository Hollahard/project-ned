"""VRAM Preflight Calculator and Model Sizing Guard for Project Friday.

Invariants:
1. Prevents driver OOM crashes by calculating weight + KV cache footprints prior to load.
2. Supports KV cache quantization modes: FP16, Q8, Q6, Q4.
3. Provides actionable fallback recommendations (e.g. reduced context length or Q6/Q8 cache)
   if a requested profile exceeds available VRAM.
"""

import re
import logging
from typing import Dict, Any, Tuple
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Bytes per element for KV cache quantization presets
KV_CACHE_BYTES_PER_ELEMENT = {
    "fp16": 2.0,
    "q8": 1.125,
    "q6": 0.875,
    "q4": 0.5625,
}

# Known architecture profiles for resident EXL3 models
KNOWN_MODEL_SPECS = {
    "Mistral-Small-3.1-24B-Instruct-2503-exl3": {
        "params_b": 24.0,
        "default_bpw": 6.0,
        "num_layers": 56,
        "num_kv_heads": 8,
        "head_dim": 128,
    },
    "Qwen3-30B-A3B-Instruct-2507": {
        "params_b": 30.0,
        "default_bpw": 4.5,
        "num_layers": 48,
        "num_kv_heads": 8,
        "head_dim": 128,
    },
    "Qwen3.5-35B-A3B-exl3-clean": {
        "params_b": 35.0,
        "default_bpw": 4.5,
        "num_layers": 48,
        "num_kv_heads": 8,
        "head_dim": 128,
    },
}

DEFAULT_CUDA_OVERHEAD_MB = 1500.0  # Context, kernels, activations


class PreflightResult(BaseModel):
    fits: bool
    model_name: str
    context_length: int
    kv_cache_dtype: str
    estimated_weights_mb: float
    estimated_kv_cache_mb: float
    estimated_total_mb: float
    available_vram_mb: float
    headroom_mb: float
    recommended_context: int | None = None
    recommended_kv_cache: str | None = None
    message: str


def parse_model_params(model_name: str) -> Tuple[float, float, int, int, int]:
    """Extract or estimate (params_b, bpw, layers, kv_heads, head_dim) from model name."""
    if model_name in KNOWN_MODEL_SPECS:
        spec = KNOWN_MODEL_SPECS[model_name]
        return (
            spec["params_b"],
            spec["default_bpw"],
            spec["num_layers"],
            spec["num_kv_heads"],
            spec["head_dim"],
        )

    # Heuristic parsing (e.g. '70B', '24B', '14B', '7B')
    match = re.search(r"(\d+(?:\.\d+)?)[bB]", model_name)
    params_b = float(match.group(1)) if match else 24.0

    # Estimate layers and heads based on parameter class
    if params_b >= 60.0:
        layers, kv_heads, head_dim = 80, 8, 128
    elif params_b >= 30.0:
        layers, kv_heads, head_dim = 48, 8, 128
    elif params_b >= 20.0:
        layers, kv_heads, head_dim = 56, 8, 128
    else:
        layers, kv_heads, head_dim = 32, 8, 128

    return params_b, 5.0, layers, kv_heads, head_dim


def calculate_model_vram_mb(
    model_name: str,
    context_length: int = 32768,
    kv_cache_dtype: str = "q6",
    bpw: float | None = None,
) -> Tuple[float, float, float]:
    """Calculate (weights_mb, kv_cache_mb, total_mb) for given configuration."""
    params_b, default_bpw, layers, kv_heads, head_dim = parse_model_params(model_name)
    actual_bpw = bpw if bpw is not None else default_bpw

    # Model weights size in MB
    weights_bytes = (params_b * 1e9 * actual_bpw) / 8.0
    weights_mb = weights_bytes / (1024**2)

    # KV Cache size in MB: 2 * layers * kv_heads * head_dim * context * bytes_per_element
    bytes_per_elem = KV_CACHE_BYTES_PER_ELEMENT.get(kv_cache_dtype.lower(), 1.0)
    kv_elements = 2 * layers * kv_heads * head_dim * context_length
    kv_bytes = kv_elements * bytes_per_elem
    kv_cache_mb = kv_bytes / (1024**2)

    total_mb = weights_mb + kv_cache_mb + DEFAULT_CUDA_OVERHEAD_MB
    return round(weights_mb, 1), round(kv_cache_mb, 1), round(total_mb, 1)


def check_vram_preflight(
    model_name: str,
    context_length: int = 32768,
    kv_cache_dtype: str = "q6",
    available_vram_mb: float = 32000.0,
    safety_margin_mb: float = 1000.0,
    bpw: float | None = None,
) -> PreflightResult:
    """Preflight check determining whether configuration safely fits within VRAM."""
    weights_mb, kv_mb, total_mb = calculate_model_vram_mb(
        model_name, context_length, kv_cache_dtype, bpw
    )

    headroom_mb = available_vram_mb - total_mb
    fits = headroom_mb >= safety_margin_mb

    if fits:
        message = (
            f"Preflight PASSED: Model '{model_name}' requires ~{total_mb:.1f} MB "
            f"({weights_mb:.1f} MB weights + {kv_mb:.1f} MB {kv_cache_dtype.upper()} KV). "
            f"Headroom: {headroom_mb:.1f} MB."
        )
        return PreflightResult(
            fits=True,
            model_name=model_name,
            context_length=context_length,
            kv_cache_dtype=kv_cache_dtype,
            estimated_weights_mb=weights_mb,
            estimated_kv_cache_mb=kv_mb,
            estimated_total_mb=total_mb,
            available_vram_mb=available_vram_mb,
            headroom_mb=round(headroom_mb, 1),
            message=message,
        )

    # If it does not fit, search for the best fallback configuration
    rec_context = None
    rec_cache = None

    # Try smaller context or more aggressive quantization
    for candidate_cache in ["q6", "q4"]:
        for candidate_ctx in [32768, 16384, 8192]:
            _, cand_kv, cand_tot = calculate_model_vram_mb(
                model_name, candidate_ctx, candidate_cache, bpw
            )
            if (available_vram_mb - cand_tot) >= safety_margin_mb:
                rec_context = candidate_ctx
                rec_cache = candidate_cache
                break
        if rec_context:
            break

    message = (
        f"Preflight FAILED: Model requires ~{total_mb:.1f} MB which exceeds available "
        f"VRAM {available_vram_mb:.1f} MB with safety margin {safety_margin_mb:.1f} MB. "
        f"Deficit: {abs(headroom_mb):.1f} MB."
    )
    if rec_context and rec_cache:
        message += f" Recommendation: Reduce context to {rec_context // 1024}K and use {rec_cache.upper()} KV cache."
    else:
        message += " Recommendation: Base model weights exceed available VRAM budget. Select a smaller model or lower bpw quantization."

    return PreflightResult(
        fits=False,
        model_name=model_name,
        context_length=context_length,
        kv_cache_dtype=kv_cache_dtype,
        estimated_weights_mb=weights_mb,
        estimated_kv_cache_mb=kv_mb,
        estimated_total_mb=total_mb,
        available_vram_mb=available_vram_mb,
        headroom_mb=round(headroom_mb, 1),
        recommended_context=rec_context,
        recommended_kv_cache=rec_cache,
        message=message,
    )
