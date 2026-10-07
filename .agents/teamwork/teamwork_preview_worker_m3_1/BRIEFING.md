# BRIEFING — 2026-10-07T17:34:00Z

## Mission
Implement the complete, production-grade standalone long-run endurance runner in `tests/soak/run_8hr_soak.py` with Win32 Job Object supervision, zero-dependency ctypes telemetry, mathematical tripwires, scripted fault injectors, dual-sink streaming, and benchmark report generation.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa
- Working directory: G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m3_1
- Original parent: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 (orchestrator_1)
- Milestone: Milestone 3 - Standalone Long-Run Endurance Runner

## 🔒 Key Constraints
- Production-grade implementation in `tests/soak/run_8hr_soak.py`.
- No cheating, no facade, no hardcoded results. All real logic and measurement.
- Exclusive write ownership: `tests/soak/run_8hr_soak.py`, `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`.
- Win32 Job Object supervision (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` without `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`).
- Zero-dependency ctypes fallback for Win32 (kernel32, psapi, iphlpapi) because psutil is not in `.venv`.
- Disable tracemalloc (`tracemalloc.is_tracing() is False`).
- OLS regression tripwires, quartile thread ratchet, thermal tripwire (83°C), SQLite WAL tripwire (64MB).
- Scripted fault injections: Gaming mode evacuation (<2.0s), mid-turn cancel, Job Object sidecar restart, VRAM recovery oracle.
- Command routing per GEMINI.md: `cmd.exe /c` with output redirection to file, inspect and delete. BypassSandbox: true for G: drive. Zero orphaned processes.

## Current Parent
- Conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Updated: 2026-10-07T17:34:00Z

## Task Summary
- **What to build**: Production-grade standalone endurance runner `tests/soak/run_8hr_soak.py`.
- **Success criteria**:
  1. CLI parsing for modes (smoke, gate, release, custom) and all flags. [PASS]
  2. Native ctypes Job Object supervisor and graceful shutdown coordinator. [PASS]
  3. Telemetry collector (Private Bytes, handles, threads, TCP sockets, NVML/smi GPU VRAM/temp) with tracemalloc disabled. [PASS]
  4. Mathematical tripwires (warmup discard, OLS slope for memory & handles, quartile thread ratchet, GPU temp, WAL file size). [PASS]
  5. Scripted fault injectors (Gaming mode <2s, mid-turn cancel, sidecar restart, VRAM recovery oracle). [PASS]
  6. Dual-sink logging (`logs/traces/soak_<timestamp>.jsonl` + Langfuse fallback) & artifacts (`logs/soak_results.json`, `docs/benchmarks/soak_test_report.md` with ASCII sparklines). [PASS]
  7. Passes verification commands with 0 orphaned processes. [PASS]

## Change Tracker
- **Files modified**: `tests/soak/run_8hr_soak.py` (complete production implementation), `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`
- **Build status**: PASS (smoke qualification test and cargo supervisor tests pass)
- **Pending issues**: None

## Quality Status
- **Build/test result**: All tests passed cleanly (pytest soak 5/5, cargo test 13/13, soak endurance runner exit code 0)
- **Lint status**: Clean
- **Tests added/modified**: `tests/soak/run_8hr_soak.py`

## Loaded Skills
- None.

## Key Decisions Made
- Implemented `Win32JobSupervisor` using pure ctypes with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` without `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` per ADR-0002 §4.
- Telemetry uses zero-dependency Win32 ctypes fallback with psutil optional enhancement.
- Dual-sink streams to `logs/traces/soak_<timestamp>.jsonl` and mirrors to Langfuse Cloud with offline fallback.
- VRAM Recovery Oracle tracks all 4 lifecycle stages with <= 512 MB residual delta and monotonic leak detection.

## Artifact Index
- `G:\Project_Ned\tests\soak\run_8hr_soak.py` — Complete standalone runner implementation
- `G:\Project_Ned\logs\soak_results.json` — Verified output JSON
- `G:\Project_Ned\docs\benchmarks\soak_test_report.md` — Verified benchmark markdown report
- `G:\Project_Ned\logs\traces\soak_*.jsonl` — Local streaming JSONL traces
