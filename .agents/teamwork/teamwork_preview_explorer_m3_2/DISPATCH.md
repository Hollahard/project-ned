## 2026-10-07T17:04:12Z
You are Explorer 2 for Milestone 3: Standalone Long-Run Endurance Runner.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md (Authoritative ADR-0002)
4. G:\Project_Ned\GEMINI.md
5. Existing telemetry in services/core/ and tests/soak/

Your objective:
Focus on Telemetry Metrics, Win32 / NVML Sampling, and Tripwire Evaluation for `tests/soak/run_8hr_soak.py`:
1. Detailed metrics sampling:
   - Private Bytes (`psutil.Process().memory_info().private` or Win32 `PROCESS_MEMORY_COUNTERS_EX`) across monitored processes.
   - OS Handle Count (`psutil.Process().num_handles()` or `GetProcessHandleCount`).
   - Thread Count (`psutil.Process().num_threads()`).
   - Loopback TCP connections (`psutil.net_connections`).
   - NVML TabbyAPI VRAM attribution: query TabbyAPI compute process VRAM specifically via `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits` or NVML Python bindings.
   - Temperature monitoring: NVML GPU temperature ceiling (83°C tripwire).
2. Mathematical Tripwire algorithms:
   - 15-minute warmup discard: only samples after warmup timestamp are evaluated for slopes.
   - Linear regression slope for Private Bytes (MB/hour): abort if slope > 50 MB/hr.
   - Linear regression slope for Handle Count (handles/hour): abort if slope > 50/hr.
   - Monotonic thread ratchet detection: algorithm across sliding windows.
   - Guarantee `tracemalloc.is_tracing()` is False / disabled.
3. Dual-sink telemetry streaming:
   - Streaming to local `logs/traces/soak_<timestamp>.jsonl`.
   - Streaming/mirroring to Langfuse Cloud (resilient fallback if offline/unconfigured).
Provide concrete Python classes / algorithms for `TelemetrySampler`, `TripwireEvaluator`, and `DualSinkLogger`.

Scope boundaries:
- Read-only analysis. Recommend implementation architecture and blueprints, do NOT modify code.
- Write your comprehensive report in G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_2\handoff.md.
- Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
