# ADR 0001: Pinned Inference Runtime Qualification (RTX 5090 Blackwell)

## Status
Accepted (Phase 1 Qualified on 2026-10-06)

## Context
Project Friday requires a local inference sidecar running ExLlamaV3 via TabbyAPI on an NVIDIA GeForce RTX 5090 (32 GB GDDR7). The RTX 5090 uses NVIDIA Blackwell compute capability `sm_120`. To guarantee application stability, prevent VRAM leaks, and enforce zero unauthorized execution, we do not track `main` branches and instead qualify and pin the exact sidecar repository commit and compiled wheels.

## Decision
We pin the inference sidecar runtime to the following qualified build:
- **TabbyAPI Commit**: `2fd6cc76203a66e13042daf7d76e5898b21c1ad8`
- **ExLlamaV3 Wheel**: `1.5.4+cu132.torch2.11.0` (compiled for Python 3.12, Windows x86_64)
- **PyTorch Wheel**: `2.11.0+cu130`
- **Triton Windows**: `triton-windows==3.8.0.post29`
- **Target Architecture**: Compute capability `(12, 0)` (`sm_120`), CUDA 13.0/13.2 runtime
- **Host Binding**: Strictly loopback `127.0.0.1:5000` with authentication enabled.

## Qualification Benchmarks
On an NVIDIA GeForce RTX 5090 32 GB:
1. **Model Discovery**: Successfully identified 3 resident EXL3 models (`Mistral-Small-3.1-24B-Instruct-2503-exl3`, `Qwen3-30B-A3B-Instruct-2507`, `Qwen3.5-35B-A3B-exl3-clean`).
2. **Cold Load Time**:
   - `Mistral-Small-3.1-24B-Instruct-2503-exl3`: 19.94s (initial cold load), ~2.4s warm load.
   - `Qwen3-30B-A3B-Instruct-2507`: 7.88s.
3. **Generation Speed**: ~94.5 tokens/sec (streaming mode).
4. **Time to First Token (TTFT)**: 8.53s on cold prefill.
5. **Model Swapping**: Cleanly swapped from Model 1 -> Unload -> Model 2 -> Unload with zero errors.
6. **Stress Testing**: 20 consecutive load/unload cycles passed back-to-back with zero memory leaks, returning 100% of VRAM to Windows idle baseline (3.7 GB idle).
7. **Error Handling**: Failed load requests for missing models cleanly return HTTP 400 Bad Request.
