# Orchestration Plan — Phase 16: Continuous Soak and Long-Run Endurance Harness

## Objective
Implement and verify all requirements (R1, R2, R3, R4) and acceptance criteria from ORIGINAL_REQUEST.md adhering strictly to ADR-0002 and GEMINI.md workspace rules.

## Step-by-Step Execution Plan

### Step 0: Survey & Scope Mapping (Parallel Explorers)
- Dispatch 3 parallel agents:
  1. `teamwork_preview_spec_miner_survey`: Deep-dive ADR-0002 and ORIGINAL_REQUEST.md requirements, tripwires, metrics, and invariant bounds.
  2. `teamwork_preview_explorer_core_survey`: Investigate Python core services (`services/core`), existing test harness, mock inference backend, database manager, scheduler, and memory modules.
  3. `teamwork_preview_explorer_tauri_survey`: Investigate Rust Tauri supervisor (`apps/desktop/src-tauri`), Windows Job Object implementation, handle management, child process spawning.
- Aggregate findings into `PROJECT.md` with full Architecture, Feature Inventory, Milestones, and Interface Contracts.

### Step 1: Milestone 1 — Fast Mocked Soak Test Suite (R1)
- Target: `tests/soak/test_soak_endurance.py`
- Iterate: Explorer -> Worker -> Reviewers (2) -> Challengers (2) -> Forensic Auditor (`teamwork_preview_auditor`).
- Pass gate criteria:
  - 50 continuous turns under 3 minutes using `MockInferenceBackend`.
  - Mid-turn cancellations, 4-tier memory churn (insert, FTS5 search, soft delete).
  - SQLite scheduler concurrent claims, timeouts, suppression.
  - Depth-1 subagent monotonic permission containment & grandchild delegation refusal.
  - Zero database locked errors, WAL growth <= 64 MB, SQLite checkpoint stalls.
  - Clean audit and unanimous approval.

### Step 2: Milestone 2 — Rust Tauri Supervisor Endurance Contract (R3)
- Target: `apps/desktop/src-tauri`
- Iterate: Explorer -> Worker -> Reviewers (2) -> Challengers (2) -> Forensic Auditor.
- Pass gate criteria:
  - Integration tests verifying repeated session creation, telemetry polling, preflight checks leak zero handles or thread pools.
  - Window close cleanly terminates child processes via `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` without active process limit = 1.
  - Passes `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`.

### Step 3: Milestone 3 — Standalone Long-Run Endurance Runner (R2, R4)
- Target: `tests/soak/run_8hr_soak.py`
- Iterate: Explorer -> Worker -> Reviewers (2) -> Challengers (2) -> Forensic Auditor.
- Pass gate criteria:
  - CLI runner with `--mode smoke`, `--mode gate`, `--mode release`.
  - VRAM attribution to TabbyAPI PID; baseline recovery within 512 MB.
  - Private Bytes, handle counts, thread counts, loopback TCP connections telemetry & tripwires (50 MB/hr, 50 handles/hr, monotonic thread ratchet, GPU temp > 83°C).
  - Scripted fault injections (Gaming Mode evacuation, turn cancel, Job Object restart).
  - Dual-sink telemetry, `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`.
  - Headless invariants, Risk >= 2 auto-denial, capability HMAC-SHA256 test stub.

### Step 4: Final Milestone — Acceptance Verification & Dual Track E2E Hardening
- Run acceptance test commands:
  - `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"`
  - `cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"`
  - `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke"`
  - Run regression test suites (`services/core/tests/`, `tests/security/`, `tests/e2e/`) verifying all 198+ tests pass.
- Final forensic audit across entire implementation.
- Generate completion handoff report to parent.
