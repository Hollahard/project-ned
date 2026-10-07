# BRIEFING — 2026-10-07T17:20:00Z

## Mission
Investigate and design telemetry sampling (Win32/NVML), mathematical tripwire evaluation algorithms, and dual-sink logging architecture for `tests/soak/run_8hr_soak.py` (Milestone 3: Standalone Long-Run Endurance Runner).

## 🔒 My Identity
- Archetype: explorer
- Roles: telemetry analysis, mathematical tripwire design, dual-sink streaming architecture
- Working directory: G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2
- Original parent: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 (orchestrator_1)
- Milestone: Milestone 3 (Standalone Long-Run Endurance Runner)

## 🔒 Key Constraints
- Read-only investigation — do NOT modify codebase/production code.
- Write only to working directory: `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\`.
- Guarantee `tracemalloc.is_tracing()` is False/disabled during soak to eliminate profiling distortion.
- Provide concrete Python classes/algorithms: `TelemetrySampler`, `TripwireEvaluator`, and `DualSinkLogger`.
- Follow ADR-0002 and GEMINI.md rules (e.g. process guardian, Win32 Job Objects, environment sanitization, no direct ExLlamaV3 imports in Core).

## Current Parent
- Conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Updated: 2026-10-07T17:20:00Z

## Investigation State
- **Explored paths**:
  - `G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md`
  - `G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md`
  - `G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md`
  - `G:\Project_Ned\GEMINI.md`
  - `G:\Project_Ned\tests\soak\run_8hr_soak.py`
  - `G:\Project_Ned\tests\soak\test_soak_endurance.py`
  - `G:\Project_Ned\services\core\src\friday\telemetry\` (`tracer.py`, `langfuse.py`, `manager.py`)
  - `G:\Project_Ned\services\core\src\friday\inference\telemetry.py`
  - `G:\Project_Ned\services\core\pyproject.toml`
  - `G:\Project_Ned\runtime\tabbyAPI\`
- **Key findings**:
  - `pynvml` (13.0.0), `langfuse` (4.17.0), and `pywin32` are installed in `.venv`.
  - `psutil` is NOT installed in `.venv`; native Win32 `ctypes` (`kernel32`, `psapi`, `iphlpapi`) provides zero-dependency high-precision sampling.
  - On Windows WDDM, `nvidia-smi compute-apps` reports `[N/A]` for non-CUDA/WDDM processes. Designed multi-tiered attribution cascade: NVML compute processes -> nvidia-smi compute-apps -> WDDM device delta -> mock profile.
  - Existing `run_8hr_soak.py` only evaluated slopes post-run using 2-point endpoint diffs, lacked online fast-fail tripwires, lacked OLS linear regression, lacked sliding-window thread ratchet detection, lacked thermal ceiling tripwire (83°C), and lacked dual-sink JSONL/Langfuse streaming.
- **Unexplored areas**: None within Milestone 3 telemetry & tripwire scope.

## Key Decisions Made
- Architecture blueprint completed for `TelemetrySampler` (dual backend psutil + Win32 ctypes, multi-process aggregation, NVML VRAM attribution and thermal monitoring).
- Mathematical specification completed for `TripwireEvaluator` (15-min warmup discard, OLS linear regression slope $SS_{ty}/SS_{tt}$, sliding window minimum floor ratcheting, 83°C thermal ceiling, tracemalloc disabled assertion).
- Dual-sink architecture completed for `DualSinkLogger` (atomic partitioned JSONL streaming at `logs/traces/soak_<timestamp>.jsonl` + Langfuse Cloud mirroring with graceful offline fallback).

## Artifact Index
- G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\DISPATCH.md — Task instruction log
- G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\BRIEFING.md — Persistent working memory
- G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\progress.md — Liveness progress log
- G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\handoff.md — Comprehensive handoff report
