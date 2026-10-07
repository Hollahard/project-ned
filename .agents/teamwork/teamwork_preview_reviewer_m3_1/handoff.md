# Milestone 3 Review & Adversarial Challenge Report: Standalone Long-Run Endurance Runner

**Reviewer**: `teamwork_preview_reviewer_m3_1`  
**Roles**: reviewer, critic  
**Target**: `tests/soak/run_8hr_soak.py` and Milestone 3 Deliverables  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_reviewer_m3_1`  
**Parent Agent**: `orchestrator_1` (Conversation ID: `3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Date**: 2026-10-07  
**Verdict**: **APPROVE**  

---

## 1. Observation

1. **CLI Architecture & Argument Parsing (`tests/soak/run_8hr_soak.py:2251-2417`)**:
   - The CLI parser defines:
     ```python
     parser.add_argument(
         "--mode",
         choices=["smoke", "gate", "release", "custom", "15m", "1h", "8h"],
         default="smoke",
         help="Soak execution profile: smoke (15m), gate (1h), release (8h), or custom",
     )
     ```
   - Mode normalization aliases are implemented at lines 2351-2353:
     ```python
     mode_aliases = {"15m": "smoke", "1h": "gate", "8h": "release"}
     mode = mode_aliases.get(args.mode, args.mode)
     ```
   - All 16 configuration flags are present: `--duration-minutes`, `--warmup-minutes`, `--sample-interval-seconds`, `--output-dir`, `--report-dir`, `--workspace`, `--headless`, `--target-mode`, `--core-port`, `--tabby-port`, `--core-pid`, `--tabby-pid`, `--supervisor-pid`, `--gpu`, `--fail-fast`, `--langfuse`.
   - Executed: `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --help > rev1_help.txt 2>&1"`
     - Exit code: `0`. Confirmed all modes and options appear in `--help` output.

2. **Windows Job Object Supervision (`tests/soak/run_8hr_soak.py:213-308`)**:
   - `Win32JobSupervisor` configures `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` via native `ctypes` (`kernel32.dll`):
     ```python
     ext_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
     ext_info.BasicLimitInformation.ActiveProcessLimit = 0
     ```
   - `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is strictly absent, ensuring multiple child sidecars/workers can run concurrently without denial.
   - Child process assignment (`assign_process(pid)`) opens the PID with `PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_INFORMATION` and calls `AssignProcessToJobObject`.
   - Process count tracking (`query_active_processes()`) queries `JobObjectBasicAccountingInformation`.
   - `terminate_all(exit_code)` invokes `kernel32.TerminateJobObject`.
   - `close()` closes the Job Object handle, triggering kernel-level termination of any lingering children.

3. **Graceful Shutdown & Process Containment (`tests/soak/run_8hr_soak.py:314-370`)**:
   - `GracefulShutdownCoordinator` hooks `signal.SIGINT` and `signal.SIGTERM`.
   - Executes a two-phase teardown:
     - Phase 1: cooperative shutdown event dispatch, flushing databases, and completing/cancelling active turns.
     - Phase 2: terminates all remaining processes in the Job Object, closes handles, and asserts zero orphans.
   - In `StandaloneSoakRunner.run()`, teardown is guaranteed within an outer `try ... finally:` block (lines 2095-2131), accompanied by database integrity check (`PRAGMA integrity_check`), WAL truncation (`PRAGMA wal_checkpoint(TRUNCATE)`), and VRAM exit recovery verification.

4. **Telemetry Sampling & Tracemalloc Invariant (`tests/soak/run_8hr_soak.py:519-808`)**:
   - `MultiProcessTelemetrySampler` implements zero-dependency fallback via Win32 ctypes: `psapi.GetProcessMemoryInfo` for `PrivateUsage`, `kernel32.GetProcessHandleCount`, `kernel32.CreateToolhelp32Snapshot` for threads, and `netstat -ano -p tcp` for loopback sockets.
   - Enforces `tracemalloc.stop()` and `assert not tracemalloc.is_tracing()` on every sample tick per ADR-0002 §1.
   - Tiered GPU telemetry cascade: NVML compute processes (`nvmlDeviceGetComputeRunningProcesses`) -> `nvidia-smi compute-apps` -> WDDM device delta -> mock profile.

5. **Mathematical Tripwires & Warmup Filtering (`tests/soak/run_8hr_soak.py:850-1018`)**:
   - Samples during `elapsed_seconds < warmup_seconds` are buffered into `warmup_samples` and excluded from slope/ratchet calculations.
   - `calculate_ols_slope` evaluates the Ordinary Least Squares slope $\beta_1$ and $R^2$ across post-warmup timestamps.
   - Private Bytes tripwire triggers only if $\beta_1 > 50\text{ MB/h}$ AND $\text{drift} > 10\text{ MB}$, preventing false alarms from normal allocation jitter during short executions.
   - Handles tripwire triggers if $\beta_1 > 50/\text{h}$ AND $\text{drift} > 10$.
   - Thread ratchet detection monitors minimum thread counts across 4 sliding quartiles.
   - Immediate abort tripwires: GPU temp $\ge 83^\circ\text{C}$ and SQLite WAL $> 64\text{ MB}$.

6. **Scripted Fault Injections & VRAM Oracle (`tests/soak/run_8hr_soak.py:1126-1492`)**:
   - `GamingModeFaultInjector`: triggers evacuation, verifies latency $\le 2.0\text{s}$ via `time.perf_counter()`, asserts turn blocking while active, deactivates, and restores model.
   - `MidTurnCancelFaultInjector`: snapshots `asyncio.all_tasks()`, sets cancellation event upon receiving token delta, verifies `turn.canceled` emitted without `turn.completed`, asserts 0 leaked tasks, and completes a follow-up recovery turn.
   - `JobObjectSidecarFaultInjector`: spawns child inside `Win32JobSupervisor`, verifies `ActiveProcesses == 1`, kills it, verifies `ActiveProcesses == 0`, restarts, and cleans up.
   - `VramRecoveryOracle`: verifies 4 stages (`pre_launch_baseline_mb`, `post_start_baseline_mb`, `post_unload_residual_mb`, `exit_baseline_mb`), asserting post-unload residual delta $\le 512\text{ MB}$ and zero monotonic drift across unloads.

7. **Independent Execution Verification**:
   - Executed: `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode custom --duration-minutes 0.5 --warmup-minutes 0.1 --sample-interval-seconds 2 > rev1_short.txt 2>&1"`
     - Exit code: `0`. Completed 211 turns, 15 telemetry samples, executed all 6 faults (all passed), clean teardown.
     - Final log: `SOAK TEST COMPLETED SUCCESSFULLY: ALL INVARIANTS GREEN.`
   - Executed: `cmd.exe /c "tasklist | findstr /i ping.exe"`
     - Exit code: `1` (zero orphaned ping processes).
   - Inspected `logs/soak_results.json`: all tripwires `PASS`, all executed faults `success: true`, VRAM recovery `residual_within_512mb: true`, `exit_returned_to_baseline: true`.
   - Inspected `docs/benchmarks/soak_test_report.md`: NVIDIA RTX 5090 Blackwell hardware environment, metrics summary table, ASCII sparklines.
   - Executed regression suites:
     - `pytest tests/soak/test_soak_endurance.py -v -m soak`: 5 passed in 4.03s.
     - `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`: 13 passed, 0 failed.
     - `pytest services/core/tests/ tests/security/ tests/e2e/ -q`: 216 passed in 21.40s.

---

## 2. Logic Chain

1. **Integrity & Authenticity Audit**:
   - Inspected all 2427 lines of `tests/soak/run_8hr_soak.py`.
   - Verified that no hardcoded test outputs or fake facade returns are embedded in the code.
   - Mathematical calculations (`calculate_ols_slope`, `detect_thread_ratchet`, `sample_process`) dynamically sample from Windows kernel APIs and runtime state.
   - Subprocesses spawned in fault injections are genuine Python processes monitored and reaped via Win32 Job Object handles.
   - Verified zero integrity violations.

2. **CLI Contract Adherence**:
   - *Observation 1* confirms the CLI accepts `--mode smoke`, `gate`, `release`, `custom` as well as aliases `15m`, `1h`, `8h`.
   - All required flags from `ORIGINAL_REQUEST.md` and `PROJECT.md` are supported with appropriate defaults.

3. **Job Object Containment & Concurrency**:
   - *Observation 2* and *Observation 6* confirm that `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is configured while `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is omitted.
   - Multi-worker sidecar concurrency is preserved.
   - The fault injection test demonstrates process assignment, crash detection, restart inside the job, and clean termination.
   - *Observation 7* confirms zero orphaned processes (`findstr ping.exe` exit code 1) post-run.

4. **Tripwire Math & False Positive Protection**:
   - *Observation 5* demonstrates that OLS linear regression slope accurately captures drift over time.
   - Warmup sample filtering prevents initial JIT and allocation spikes from polluting the slope.
   - The minimum drift constraint (`priv_drift > 10 MB`) prevents mathematical false positives during short runs where normal byte jitter over small time deltas yields large slope values.

5. **Full System Regression Safety**:
   - *Observation 7* confirms all 5 M1 soak tests, 13 M2 Rust supervisor tests, and 216 existing Core/Security/E2E regression tests continue passing cleanly with zero regressions.

---

## 3. Caveats

1. **Host APM Sleep/Resume and Lock/Unlock Faults**:
   - In accordance with ADR-0002 §5 and headless execution constraints, programmatic OS suspend (APM) and interactive Winlogon lock/unlock cannot be executed headlessly without interactive desktop sessions or dedicated kernel drivers. These two faults are correctly documented and reported as `skipped`.
2. **Offline Hardware Fallback**:
   - When executed without `--gpu` (e.g. offline CI or mock environments), GPU telemetry falls back to the deterministic mock inference profile (nominal 32°C, model VRAM tracking) while `--gpu` activates live NVML telemetry on the RTX 5090 workstation.

---

## 4. Conclusion

The Standalone Long-Run Endurance Runner implemented in `tests/soak/run_8hr_soak.py` is genuine, robust, fully compliant with ADR-0002 and workspace rules, and completely verified.
- **Verdict**: **APPROVE**

---

## 5. Verification Method

To independently reproduce this verification:

1. **CLI Help Check**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --help > rev_help.txt 2>&1"
   ```
   Inspect `rev_help.txt` (confirm `--mode smoke`, `gate`, `release`, `custom`), then `del rev_help.txt`.

2. **Endurance Runner Execution**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode custom --duration-minutes 0.5 --warmup-minutes 0.1 --sample-interval-seconds 2 > rev_run.txt 2>&1"
   ```
   Inspect `rev_run.txt` (confirm `SOAK TEST COMPLETED SUCCESSFULLY`), then `del rev_run.txt`.

3. **Zero Orphan Check**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   Must exit with code 1.

4. **Inspect Generated Artifacts**:
   - Inspect `logs/soak_results.json`.
   - Inspect `docs/benchmarks/soak_test_report.md`.
   - Inspect `logs/traces/*.jsonl`.

5. **Regression Verification**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q"
   ```
