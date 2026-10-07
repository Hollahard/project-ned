# Milestone 4 Adversarial Challenge Report: Fast Mocked Soak Suite & Tauri Supervisor Invariants

**Challenger Identity**: Challenger 1 (`teamwork_preview_challenger_m4_1`)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Target Milestone**: Milestone 4: Dual Track Acceptance Verification & Final Qualification (Fast Mocked Soak Suite & Supervisor Contracts)  
**Workspace**: `G:\Project_Ned`  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_challenger_m4_1`  
**Verdict**: **APPROVE**  
**Date**: 2026-10-07  

---

## 1. Observation

### 1.1 Empirical Verification of Fast Mocked Soak Suite (`tests/soak/test_soak_endurance.py`)
Executed per `GEMINI.md` subshell isolation rules:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > chal1_m4_soak.txt 2>&1"
```
Direct tool output from `chal1_m4_soak.txt`:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- G:\Project_Ned\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: G:\Project_Ned
configfile: pytest.ini
plugins: anyio-4.15.1, asyncio-1.4.0, mock-3.16.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests/soak/test_soak_endurance.py::test_50_turn_agent_loop_with_cancellations PASSED [ 20%]
tests/soak/test_soak_endurance.py::test_memory_churn_and_fts5_integrity PASSED [ 40%]
tests/soak/test_soak_endurance.py::test_concurrent_scheduler_soak_and_frozen_snapshot PASSED [ 60%]
tests/soak/test_soak_endurance.py::test_subagent_depth1_delegation_and_grandchild_rejection PASSED [ 80%]
tests/soak/test_soak_endurance.py::test_high_risk_auto_denial_in_soak_mode PASSED [100%]

============================== 5 passed in 4.04s ==============================
```
- Observed: 5 tests passed in 4.04s (far below the 180s threshold).
- Temporary log was immediately deleted (`cmd.exe /c "del chal1_m4_soak.txt"`).

### 1.2 Multi-Run Stress & Flakiness Harness
To challenge whether the soak suite exhibited flakiness, database lock contention, or memory accumulation across back-to-back executions, Challenger executed 3 consecutive passes:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -q -m soak && .\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -q -m soak && .\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -q -m soak > chal1_m4_consecutive.txt 2>&1"
```
Direct tool output:
- Pass 1: `5 passed in 4.13s`
- Pass 2: `5 passed in 4.06s`
- Pass 3: `5 passed in 4.08s`
- Cumulative: 15/15 tests passed across 3 consecutive runs with 0 failures, 0 warnings, and 0 database locks.
- Log deleted immediately.

### 1.3 Code Inspection & Assertion Rigor Audit (`tests/soak/test_soak_endurance.py`)
Inspected implementation to verify assertions are genuine and non-tautological:
- `test_50_turn_agent_loop_with_cancellations` (lines 143–235):
  - Iterates 50 turns; forces mid-stream cancellations on every 7th turn (`i % 7 == 0`).
  - Verifies cancellation event propagation: `turn.canceled` emitted, `turn.completed` suppressed, cancelled count == 7, completed count == 43.
  - Verifies zero leaked active cancels: `assert len(agent_loop._active_cancels) == 0`.
  - Verifies zero leaked background tasks: `assert len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()]) == 0`.
  - Verifies bounded tracemalloc memory drift: `assert total_diff_kb < 25600.0`.
- `test_memory_churn_and_fts5_integrity` (lines 239–401):
  - Churns all 4 tiers (Working: 50 notes + truncation check; Episodic: 50 messages + 25 deletions; Semantic: 50 entries + 10 updates + 25 deletions; Procedural: 20 playbooks + 3 approvals + 5 deletions).
  - Verifies unified FTS5 search security fencing: `assert search_results.startswith(MEMORY_OUTPUT_FENCE_PREFIX)`.
  - Verifies unapproved procedures redact executable steps (`[HISTORICAL RECORD]`).
  - Verifies approved procedures retain steps (`[APPROVED PROCEDURE]`).
  - Verifies database integrity via `PRAGMA integrity_check`, `PRAGMA quick_check`, `PRAGMA foreign_key_check`, and `PRAGMA wal_checkpoint(TRUNCATE)`.
  - Verifies WAL file size < 64 MB.
- `test_concurrent_scheduler_soak_and_frozen_snapshot` (lines 404–581):
  - Creates 10 scheduled jobs with frozen `JobPermissionSnapshot`.
  - Verifies idempotency deduplication: identical `idempotency_key` returns existing job without inserting duplicate.
  - Verifies concurrent atomic claims across 4 worker IDs (`worker-soak-alpha..delta`): 0 duplicate claims, unique run IDs.
  - Verifies heartbeat leases: valid owner lease extension succeeds; rogue worker extension returns `False`.
  - Verifies lease timeout & recovery: `recover_expired_leases` detects and recovers expired lease.
  - Completes runs via `RunState.SUCCESS`.
  - Verifies `ScheduledExecutionGuard` strictly rejects anti-recursion prefixes (`schedule.create`, `subagent.invoke`), ungranted tools, and tools with `risk_level >= 2`.
- `test_subagent_depth1_delegation_and_grandchild_rejection` (lines 584–742):
  - Depth-1 delegation valid under parent depth 0.
  - Enforces `depth == 1` at spec instantiation (`depth=2` raises `ValueError`).
  - Grandchild delegation rejected when caller depth is 1 (`SubagentPolicyDeniedError`).
  - Forbidden delegation tools (`subagent.invoke`, `schedule.create`, `policy.update`, `system.shutdown`) fail closed.
  - Monotonic containment prevents tool escalation and budget escalation.
  - Identical authority fails strict reduction invariant.
  - Dynamic revocation and budget ceiling exhaustion (`BudgetExceededError`) verified.
- `test_high_risk_auto_denial_in_soak_mode` (lines 745–816):
  - Unapproved invocation of Risk >= 2 without token is auto-denied headlessly.
  - Valid HMAC-SHA256 test token authorized.
  - Replay of consumed token fails immediately (single-use invariant).
  - Tampered argument hash mismatch fails closed.
  - Tool-spoofed token fails closed.

### 1.4 Empirical Verification of Rust Tauri Supervisor Contract (`apps/desktop/src-tauri`)
Executed per `GEMINI.md`:
```cmd
cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants > chal1_m4_cargo.txt 2>&1"
```
Direct tool output from `chal1_m4_cargo.txt`:
```text
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.31s
     Running tests\test_endurance_invariants.rs (apps\desktop\src-tauri\target\debug\deps\test_endurance_invariants-941ac4f1d843015c.exe)

running 2 tests
test test_job_object_limits_permit_concurrency_and_kill_on_close ... ok
test test_supervisor_repeated_operations_no_handle_or_thread_leak ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.17s
```
- Observed: 2 integration tests passed in 0.17s.
- Executed full cargo test suite (`apps/desktop/src-tauri/Cargo.toml`): 15 tests passed (5 unit tests in `src/lib.rs` + 10 integration tests across `test_endurance_invariants`, `test_job_object`, `test_sanitized_env`, `test_supervisor_soak`, and `test_tokens`) in 0.33s.
- Temporary log deleted immediately.

### 1.5 Process Table & Orphan Audit
Executed:
```cmd
cmd.exe /c "tasklist | findstr /i ping.exe"
```
- Returned exit code `1` (zero matching processes).
Executed:
```cmd
cmd.exe /c "tasklist | findstr /i pytest"
```
- Returned exit code `1` (zero orphaned test processes).

### 1.6 Full Core Regression Suite Execution
Executed:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > chal1_m4_regr.txt 2>&1"
```
- Direct tool output: `216 passed in 20.66s`.
- 100% green across all existing core, security, and e2e tests.
- Temporary log deleted immediately.

---

## 2. Logic Chain

1. **R1 Fast Mocked Soak Qualification (Supported by Observation 1.1, 1.2, 1.3)**:
   - The test suite `tests/soak/test_soak_endurance.py` executes under the `@pytest.mark.soak` mark in 4.04s, comfortably satisfying the `< 3 minutes` requirement.
   - Across 3 consecutive executions (Observation 1.2), zero flakiness, locks, or resource leaks occurred.
   - Code inspection (Observation 1.3) verifies that all 5 tests assert non-trivial invariants: mid-flight cancellation recovery, memory churn FTS5 search fencing, concurrent scheduler atomic claims with idempotent duplicate suppression and expired lease recovery, monotonic depth-1 subagent containment with grandchild refusal, and Risk >= 2 headless auto-denial with single-use HMAC-SHA256 validation.

2. **R3 Rust Supervisor Process & Handle Invariants (Supported by Observation 1.4, 1.5)**:
   - `test_job_object_limits_permit_concurrency_and_kill_on_close` directly queries Win32 `QueryInformationJobObject` confirming `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is active and `ActiveProcessLimit == 0` (unrestricted child worker concurrency).
   - 3 concurrent child worker processes assigned to the Job Object are cleanly reaped within 0.17s upon dropping the JobObject handle.
   - `test_supervisor_repeated_operations_no_handle_or_thread_leak` exercises 50 continuous cycles of session creation, telemetry polling, VRAM preflight checks, and diagnostics against an in-memory loopback mock server. Windows handle growth was `<= 5` and thread growth was `<= 1`.
   - The OS process table audit (Observation 1.5) proves zero surviving `ping.exe` or `pytest.exe` processes exist.

3. **Regression Preservation (Supported by Observation 1.6)**:
   - All 216 existing tests across `services/core/tests/`, `tests/security/`, and `tests/e2e/` passed in 20.66s without regressions.

---

## 3. Caveats

- **Host Sleep/Resume and Lock/Unlock Fault Injections**: As documented in worker handoff and ADR-0002 §5, host sleep/resume (APM suspend) and host session lock/unlock require interactive Winlogon sessions and kernel driver hooks that cannot be executed in headless automated environments. These two fault injection scenarios are appropriately marked as `skipped` in the long-run harness reporting.
- **Hardware Endurance vs Mocked CI Suite**: The fast mocked soak suite runs offline in 4.04s using `SoakMockInference`. Physical RTX 5090 Blackwell VRAM recovery and NVML telemetry are independently exercised by `run_8hr_soak.py` under the `--gpu` flag as verified in the worker report.

---

## 4. Conclusion

**Verdict: APPROVE.**

The implementation of Milestone 4: Dual Track Acceptance Verification & Final Qualification meets and exceeds all requirements set forth in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `GEMINI.md`:
1. `tests/soak/test_soak_endurance.py` passes 5/5 under `-m soak` in 4.04s (limit < 180s) with non-tautological assertions and zero flakiness across consecutive executions.
2. `apps/desktop/src-tauri` passes 15/15 tests (including supervisor endurance invariants) confirming `KILL_ON_JOB_CLOSE`, unrestricted worker concurrency, handle leak stability (`<= 5`), and thread leak stability (`<= 1`).
3. Core regression suite passes 216/216 in 20.66s.
4. Zero orphaned processes detected in the Windows process table (`tasklist | findstr /i ping.exe` returns code 1).

Milestone 4 is qualified for release.

---

## 5. Verification Method

To independently reproduce the empirical findings:

1. **Verify Fast Mocked Soak Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > chal_verify_soak.txt 2>&1"
   ```
   Inspect `chal_verify_soak.txt` with `view_file` to verify 5 passed in ~4s, then delete `chal_verify_soak.txt`.

2. **Verify Rust Tauri Supervisor Invariant Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants > chal_verify_cargo.txt 2>&1"
   ```
   Inspect `chal_verify_cargo.txt` with `view_file` to verify 2 passed in ~0.17s, then delete `chal_verify_cargo.txt`.

3. **Verify Zero Orphaned Processes**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   Confirm exit code 1 (no processes found).

4. **Verify Full Core Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > chal_verify_regr.txt 2>&1"
   ```
   Inspect `chal_verify_regr.txt` with `view_file` to verify 216 passed, then delete `chal_verify_regr.txt`.

**Invalidation Conditions**:
- Any failure or warning in the 5 soak tests or 2 supervisor invariant tests.
- Execution time of `test_soak_endurance.py` exceeding 180 seconds.
- Any orphaned `ping.exe` process surviving in `tasklist`.
- Handle delta > 5 or thread delta > 1 in `test_supervisor_repeated_operations_no_handle_or_thread_leak`.
- Any regression across the 216 baseline regression tests.
