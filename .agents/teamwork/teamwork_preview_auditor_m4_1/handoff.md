# Forensic Audit Handoff Report: Milestone 4 Dual Track Acceptance & Final Qualification

**Auditor**: Forensic Auditor (`teamwork_preview_auditor_m4_1`)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Target Work Product**: Phase 16 Continuous Soak and Long-Run Endurance Harness  
**Workspace**: `G:\Project_Ned`  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_auditor_m4_1`  
**Date**: 2026-10-07  

---

## Forensic Audit Report

**Work Product**: Phase 16 Implementation & Verification Artifacts (`tests/soak/test_soak_endurance.py`, `apps/desktop/src-tauri/src/processes.rs`, `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`, `tests/soak/run_8hr_soak.py`, `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`)  
**Profile**: General Project (Integrity Mode: `development` per `ORIGINAL_REQUEST.md`)  
**Verdict**: **CLEAN**

### Phase Results
- **Source Code Forensic Analysis**: **PASS** — Zero hardcoded outputs, zero facade stubs, zero prohibited shortcuts.
- **Behavioral Test Suite Execution (`pytest -m soak`)**: **PASS** — 5 of 5 tests passed in 4.03s (< 180s requirement).
- **Supervisor Integration Suite Execution (`cargo test`)**: **PASS** — 15 of 15 tests (5 unit + 10 integration) passed in 0.88s.
- **Full Core Regression Suite Execution (`pytest regression`)**: **PASS** — 216 of 216 tests passed in 21.08s (exceeds 198+ target).
- **Process Lifecycle & Containment Audit**: **PASS** — Zero orphaned worker processes remaining (`tasklist | findstr /i ping.exe` returned exit code 1).
- **Mathematical & Telemetry Authenticity Check**: **PASS** — Real Win32 ctypes / kernel32 / psapi bindings, true OLS mathematical regression, real `perf_counter` and `asyncio.all_tasks()` inspections.
- **Artifact Consistency Check**: **PASS** — `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md` reflect authentic runner execution with identical timestamps, durations, and metrics.

---

## 1. Observation

### 1.1 Empirical Test Execution Results

1. **Fast Mocked Soak Test Suite (`tests/soak/test_soak_endurance.py`)**:
   - Executed:
     ```cmd
     cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > aud_m4_soak.txt 2>&1"
     ```
   - Verbatim captured output in `aud_m4_soak.txt`:
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

     ============================== 5 passed in 4.03s ==============================
     ```
   - Temporary log `aud_m4_soak.txt` immediately verified and deleted.

2. **Rust Tauri Supervisor Integration Suite (`apps/desktop/src-tauri`)**:
   - Executed:
     ```cmd
     cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > aud_m4_cargo.txt 2>&1"
     ```
   - Verbatim captured output in `aud_m4_cargo.txt`:
     ```text
     Finished `test` profile [unoptimized + debuginfo] target(s) in 0.31s
     Running unittests src\lib.rs (apps\desktop\src-tauri\target\debug\deps\friday_supervisor-2498de27c0661a58.exe)
     running 5 tests
     test first_launch::tests::test_validate_safe_windows_path_rejects_alternate_data_streams ... ok
     test first_launch::tests::test_validate_safe_windows_path_rejects_reserved_device_names ... ok
     test first_launch::tests::test_check_first_launch_status_for_nonexistent_dir ... ok
     test first_launch::tests::test_validate_safe_windows_path_rejects_trailing_dots_and_spaces ... ok
     test first_launch::tests::test_run_preflight_diagnostics_passes_with_rtx5090_and_job_object ... ok
     test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running tests\test_endurance_invariants.rs (apps\desktop\src-tauri\target\debug\deps\test_endurance_invariants-941ac4f1d843015c.exe)
     running 2 tests
     test test_job_object_limits_permit_concurrency_and_kill_on_close ... ok
     test test_supervisor_repeated_operations_no_handle_or_thread_leak ... ok
     test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.16s

     Running tests\test_job_object.rs (apps\desktop\src-tauri\target\debug\deps\test_job_object-1dfcf28576ea011b.exe)
     running 2 tests
     test test_job_object_creation_and_limits ... ok
     test test_job_object_assign_and_kill_on_drop ... ok
     test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.31s

     Running tests\test_sanitized_env.rs (apps\desktop\src-tauri\target\debug\deps\test_sanitized_env-b2de88075bdbaa2e.exe)
     running 1 test
     test test_sanitized_environment_strips_parent_secrets ... ok
     test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running tests\test_supervisor_soak.rs (apps\desktop\src-tauri\target\debug\deps\test_supervisor_soak-d1aed8428d8c3801.exe)
     running 3 tests
     test test_repeated_preflight_and_diagnostics_zero_handle_leak ... ok
     test test_job_object_membership_asserted_in_rust ... ok
     test test_supervisor_exit_reaps_core_and_tabby_sidecars ... ok
     test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.41s

     Running tests\test_tokens.rs (apps\desktop\src-tauri\target\debug\deps\test_tokens-09125e883425a11c.exe)
     running 2 tests
     test test_canonical_args_hash_is_order_independent ... ok
     test test_approval_manager_mint_and_single_use_consume ... ok
     test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
     ```
   - Total: 15 passed, 0 failed, 0 warnings. Temporary log `aud_m4_cargo.txt` immediately verified and deleted.

3. **Full Core Regression Suite Execution**:
   - Executed:
     ```cmd
     cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > aud_regression.txt 2>&1"
     ```
   - Verbatim captured output in `aud_regression.txt`:
     ```text
     ........................................................................ [ 33%]
     ........................................................................ [ 66%]
     ........................................................................ [100%]
     216 passed in 21.08s
     ```
   - Total: 216 passed in 21.08s without regression. Temporary log `aud_regression.txt` immediately verified and deleted.

4. **Orphaned Process Audit**:
   - Executed:
     ```cmd
     cmd.exe /c "tasklist | findstr /i ping.exe > aud_tasklist.txt 2>&1"
     ```
   - Command exited with code `1` (0 processes matched). Temporary log `aud_tasklist.txt` verified and deleted.

---

### 1.2 Detailed Source Inspection Observations

1. **`tests/soak/test_soak_endurance.py`**:
   - Line 78-95: `SoakMockInference.generate` implements an asynchronous generator yielding `InferenceEvent` tokens with cooperative `await asyncio.sleep(0.001)`.
   - Line 171-212: `test_50_turn_agent_loop_with_cancellations` executes a real `for i in range(1, 51)` loop calling `agent_loop.run_turn()`. Turns where `i % 7 == 0` (turns 7, 14, 21, 28, 35, 42, 49) trigger cancellations via `cancel_event.set()` or `agent_loop.cancel_turn(session_id)`. Verifies 43 completed, 7 cancelled turns, `len(agent_loop._active_cancels) == 0`, and `asyncio.all_tasks()` shows 0 leaked background tasks. Memory drift is asserted using `tracemalloc.take_snapshot()` with `< 25600.0 KB` threshold.
   - Line 240-400: `test_memory_churn_and_fts5_integrity` performs real SQLite operations on `DatabaseManager` across all 4 tiers: Working (50 scratchpad notes), Episodic (50 messages inserted into real `messages` table with FTS5 `messages_fts` indexing, 25 deleted), Semantic (50 entries saved into `semantic_memory` and FTS5 `semantic_memory_fts`, 10 updated, 25 deleted), Procedural (20 entries saved, 3 approved, 5 deleted). Runs `PRAGMA integrity_check`, `PRAGMA quick_check`, `PRAGMA foreign_key_check`, and `PRAGMA wal_checkpoint(TRUNCATE)`. WAL size is verified `< 64.0 MB`.
   - Line 404-582: `test_concurrent_scheduler_soak_and_frozen_snapshot` creates 10 scheduled jobs with frozen `JobPermissionSnapshot`, verifies idempotency suppression, triggers 10 concurrent claim attempts across 4 workers with `asyncio.gather`, verifies zero double-claims, verifies lease heartbeat extension and stale owner rejection, recovers expired leases, completes runs with `RunState.SUCCESS`, and validates `ScheduledExecutionGuard` policy enforcement.
   - Line 585-742: `test_subagent_depth1_delegation_and_grandchild_rejection` verifies monotonic capability containment on `SubagentSpec`: depth=1 permitted, depth=2 rejected with `ValueError`, caller depth=1 rejected with `SubagentPolicyDeniedError`, tool and token budget escalations rejected, identical privileges rejected (strict reduction), dynamic anti-recursion verified in `SubagentExecutionGuard`.
   - Line 745-816: `test_high_risk_auto_denial_in_soak_mode` verifies headless auto-denial for Risk >= 2 tools without token, authorization with minted HMAC-SHA256 test token, refusal of replayed token, refusal of tampered arguments, and refusal of spoofed tool names.

2. **`apps/desktop/src-tauri/src/processes.rs` & `tests/test_endurance_invariants.rs`**:
   - `processes.rs` lines 139-158: `raw_handle()` returns the internal Win32 `HANDLE`, and `JobObject` implements `std::os::windows::io::AsRawHandle`.
   - Native Win32 APIs called: `CreateJobObjectW`, `SetInformationJobObject` (enforcing `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), `AssignProcessToJobObject`, `IsProcessInJob`, `QueryInformationJobObject`, `TerminateJobObject`, `CloseHandle`.
   - `test_endurance_invariants.rs` lines 41-78: `get_current_handle_count()` invokes `GetProcessHandleCount()`. `get_current_thread_count()` invokes `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)` and iterates via `Thread32First` / `Thread32Next`.
   - `test_endurance_invariants.rs` lines 182-311: `QueryInformationJobObject` asserts `LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0`, `LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`, and `ActiveProcessLimit == 0`. Spawns 3 concurrent `ping.exe` child workers, assigns all 3 to the job, drops the job, and verifies all 3 children terminate within 3 seconds.
   - Lines 318-442: Runs loopback HTTP mock server, executes 10 warmup cycles followed by 50 iterations of session creation, telemetry, VRAM preflight, and preflight diagnostics, asserting `handle_delta <= 5` and `thread_delta <= 1`.

3. **`tests/soak/run_8hr_soak.py`**:
   - Lines 213-308: `Win32JobSupervisor` uses ctypes to call `kernel32.CreateJobObjectW`, `SetInformationJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and `ActiveProcessLimit = 0` (omitting `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`).
   - Lines 520-654: `MultiProcessTelemetrySampler` samples `PROCESS_MEMORY_COUNTERS_EX` via `psapi.GetProcessMemoryInfo` for Private Bytes, `kernel32.GetProcessHandleCount` for handles, `CreateToolhelp32Snapshot` for thread counts, and `netstat -ano -p tcp` for loopback TCP.
   - Lines 877-901: `calculate_ols_slope` computes Ordinary Least Squares slope and R^2 mathematically using standard analytical formulas.
   - Lines 1289-1349: `GamingModeFaultInjector` measures `t_evac = time.perf_counter() - t_start` asserting `t_evac <= 2.0`.
   - Lines 1351-1431: `MidTurnCancelFaultInjector` audits `tasks_before` and `tasks_after` using `asyncio.all_tasks()`, asserting `leaked_tasks == 0` and `len(agent_loop._active_cancels) == 0`.

4. **`logs/soak_results.json` & `docs/benchmarks/soak_test_report.md`**:
   - Both files represent the latest qualification run with matching metrics:
     - Duration: 30.0s, total turns: 210, samples count: 15.
     - Private Bytes slope: `+49.09 MB/h` (threshold: `< 50.0 MB/h`).
     - OS Handles growth: `+0.0/h` (threshold: `< 50/h`).
     - Thread ratchet: Start 8 -> End 8 (ratchet = 0).
     - Peak GPU Temp: 32°C (threshold: `< 83°C`).
     - SQLite WAL max: 3.972 MB (threshold: `< 64.0 MB`).
     - VRAM residual delta: `+0.0 MB` (threshold: `≤ 512.0 MB`).
     - Exit card VRAM delta: `+76.7 MB` (threshold: `≤ 512.0 MB`).
     - All 6 executed fault injections passed (`success: true`).

---

## 2. Logic Chain

1. **Absence of Prohibited Shortcuts (Observation 1.2)**:
   - Analysis of `tests/soak/test_soak_endurance.py`, `apps/desktop/src-tauri/src/processes.rs`, `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`, and `tests/soak/run_8hr_soak.py` shows genuine algorithmic implementations across all modules.
   - There are no hardcoded `assert True` bypasses, mock facades returning constant strings, or test result fabrications.
   - Real SQLite databases with FTS5 virtual tables and triggers are created, churned, and verified with `PRAGMA integrity_check`.

2. **Empirical Verification of Invariant Contracts (Observation 1.1)**:
   - Independent test execution of `pytest -m soak` confirmed that all 5 soak tests execute and pass in 4.03s, well under the 180s threshold.
   - Independent execution of `cargo test` proved that all 15 supervisor tests pass in 0.88s, verifying handle and thread stability alongside Windows Job Object concurrency.
   - Independent execution of the regression suite confirmed that all 216 tests pass in 21.08s without breaking changes.
   - Verification of the OS process table confirmed 0 orphaned child processes (`tasklist | findstr /i ping.exe` exit code 1).

3. **Authenticity of Telemetry & Reporting (Observation 1.2.3, 1.2.4)**:
   - `run_8hr_soak.py` implements true OS-level telemetry querying (`psapi.GetProcessMemoryInfo`, `GetProcessHandleCount`, `CreateToolhelp32Snapshot`, `netstat`) without depending on unverified external mocks.
   - Slope calculations utilize true OLS regression mathematics.
   - The generated artifacts (`logs/soak_results.json` and `docs/benchmarks/soak_test_report.md`) reflect real, synchronized telemetry outputs from the test runner.

4. **Integrity Mode Compliance**:
   - `ORIGINAL_REQUEST.md` specifies `Integrity mode: development`. Under Development mode, the threshold requires absence of dummy facades, fabricated outputs, and hardcoded test results.
   - Even under more stringent Demo or Benchmark modes, the code demonstrates genuine, independent implementation.

Therefore, the work product satisfies all forensic integrity criteria.

---

## 3. Caveats

- **Host Sleep/Resume and Lock/Unlock Faults**: In accordance with ADR-0002 §5 and headless execution constraints, programmatic OS sleep/resume and host session lock/unlock require interactive desktop hooks and are recorded as `skipped` with rationale in the benchmark artifacts.
- **Duration Calibrations**: The standalone runner was verified in custom calibrated duration mode (30.0s / 210 turns) to validate telemetry, tripwires, and fault injections on the physical workstation without running a full 8-hour soak, which ADR-0002 §Non-Goals explicitly reserves for release tagging.

---

## 4. Conclusion

**VERDICT: CLEAN**

The Phase 16 work product for Milestone 4 (Dual Track Acceptance Verification & Final Qualification) is fully genuine, authentic, and compliant with ADR-0002, GEMINI.md, and `ORIGINAL_REQUEST.md`. No integrity violations, hardcoded bypasses, or dummy facades were detected. The work product is approved.

---

## 5. Verification Method

To independently verify this audit:

1. **Execute Fast Soak Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > aud_check_soak.txt 2>&1"
   ```
   Inspect `aud_check_soak.txt` with `view_file` to confirm 5 passed in < 3m, then delete the file.

2. **Execute Rust Supervisor Suite**:
   ```cmd
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > aud_check_cargo.txt 2>&1"
   ```
   Inspect `aud_check_cargo.txt` with `view_file` to confirm 15 passed, then delete the file.

3. **Execute Full Core Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > aud_check_reg.txt 2>&1"
   ```
   Inspect `aud_check_reg.txt` with `view_file` to confirm 216 passed, then delete the file.

4. **Audit Orphaned Processes**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   Confirm return code is 1 (0 matching lines).

5. **Inspect Artifacts**:
   - `logs/soak_results.json`
   - `docs/benchmarks/soak_test_report.md`

**Invalidation Conditions**:
- Any test failure in `test_soak_endurance.py`, `cargo test`, or the 216 regression suite.
- Presence of any surviving `ping.exe` processes.
- Any discrepancy between `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md`.
