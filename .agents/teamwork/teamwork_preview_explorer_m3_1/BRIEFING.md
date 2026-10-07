# BRIEFING — 2026-10-07T17:25:00Z

## Mission
Investigate and design the CLI, architecture, and process lifecycle for the standalone long-run endurance runner (`tests/soak/run_8hr_soak.py`).

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, synthesis
- Working directory: G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m3_1
- Original parent: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Milestone: Milestone 3: Standalone Long-Run Endurance Runner

## 🔒 Key Constraints
- Read-only investigation — do NOT implement or modify workspace code directly
- Focus strictly on CLI, architecture, process lifecycle, Job Object supervision, and shutdown semantics
- Strictly enforce Process Guardian & Sidecar Invariants (Windows Job Object `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, zero orphaned processes)
- Deliver findings in `handoff.md` and notify parent via `send_message`

## Current Parent
- Conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (R1-R4 requirements, acceptance criteria)
  - `G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md` (M3 scope, contracts)
  - `G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md` (ADR-0002 §1-5 invariants)
  - `G:\Project_Ned\GEMINI.md` (Workstation rules, Windows Job Object invariants)
  - `G:\Project_Ned\tests\soak\run_8hr_soak.py` (Current implementation and CLI parser)
  - `G:\Project_Ned\apps\desktop\src-tauri\src\processes.rs` (Rust Job Object and child supervisor)
  - `G:\Project_Ned\apps\desktop\src-tauri\tests\test_endurance_invariants.rs` & `test_supervisor_soak.rs`
  - `G:\Project_Ned\services\core\src\friday\skills\cage.py` (ctypes Job Object implementation)
  - `G:\Project_Ned\services\core\src\friday\inference\telemetry.py` (NVML telemetry provider)
- **Key findings**:
  - Current `run_8hr_soak.py` rejects `--mode smoke` because it only accepts `15m`, `1h`, `8h`, breaking Acceptance Criteria 54.
  - Current parser lacks `--warmup-minutes`, `--output-dir`, `--report-dir`, `--headless`, `--target-mode`, and process orchestration flags.
  - Current runner only runs embedded in `os.getpid()`; it does not support supervising child processes under Windows Job Object or attaching to running processes.
  - Job Object must have `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` without `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`.
  - Graceful shutdown requires two-phase cooperative drain followed by mass termination.
- **Unexplored areas**: None within the assigned scope. Investigation complete.

## Key Decisions Made
- Structured the blueprint into modular, production-ready classes: `SoakRunnerConfig`, `Win32JobSupervisor`, `GracefulShutdownCoordinator`, `MultiProcessTelemetrySampler`, `SoakTripwireEvaluator`, and `StandaloneSoakRunner`.
- Implemented mode normalization (`smoke`, `gate`, `release`, `custom` + backwards-compatible aliases `15m`, `1h`, `8h`).
- Completed 5-component handoff report in `handoff.md`.

## Artifact Index
- `DISPATCH.md` — Incoming dispatch log
- `BRIEFING.md` — Persistent situational awareness
- `progress.md` — Liveness heartbeat and milestone progress
- `handoff.md` — Final 5-component handoff report
