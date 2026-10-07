# Forensic Audit Report: Milestone 3 Standalone Long-Run Endurance Runner

**Agent**: `teamwork_preview_auditor_m3_1`  
**Role**: auditor, critic, specialist  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_auditor_m3_1`  
**Parent Agent**: `orchestrator_1` (Conversation ID: `3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Target**: Milestone 3 - Standalone Long-Run Endurance Runner (`tests/soak/run_8hr_soak.py`, `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`)  
**Integrity Mode**: `development` (per `G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md:8`)  
**Profile**: General Project  
**Verdict**: **CLEAN**

---

## 1. Observation

1. **Win32 Job Object Supervision (`Win32JobSupervisor`)**:
   - In `tests/soak/run_8hr_soak.py:213-308`, `Win32JobSupervisor` directly imports `kernel32` and `psapi` via `ctypes.windll`.
   - Lines 222–245: Calls `kernel32.CreateJobObjectW(None, None)` and `kernel32.SetInformationJobObject` with `JobObjectExtendedLimitInformation`. Explicitly sets `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and `ActiveProcessLimit = 0` (strictly omitting `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, satisfying ADR-0002 §4).
   - Lines 248–269: Calls `kernel32.OpenProcess` and `kernel32.AssignProcessToJobObject`.
   - Lines 270–288: Calls `kernel32.QueryInformationJobObject` with `JobObjectBasicAccountingInformation` reading `acct_info.ActiveProcesses`.
   - Lines 289–301: Calls `kernel32.TerminateJobObject` and `kernel32.CloseHandle`.
   - Empirical run log confirmed live execution:
     ```text
     13:39:41 [INFO] friday.soak: Initialized Windows Job Object (handle=1192) with KILL_ON_JOB_CLOSE
     13:39:41 [INFO] friday.soak: Successfully assigned PID 20424 to Windows Job Object
     13:39:41 [INFO] friday.soak: Successfully assigned PID 37176 to Windows Job Object
     13:39:41 [INFO] friday.soak: Job Object Sidecar Restart Complete: init=1, killed=0, restarted=1 in 0.002s, success=True
     13:39:41 [INFO] friday.soak: Terminated all processes in Job Object with exit code 0
     13:39:41 [INFO] friday.soak: Closed Windows Job Object handle 1192
     ```

2. **Telemetry Sampling (`MultiProcessTelemetrySampler`)**:
   - In `tests/soak/run_8hr_soak.py:520-808`, operates with zero `psutil` dependency.
   - Lines 561–566: Genuinely asserts `tracemalloc.is_tracing() is False` on every sample.
   - Lines 597–638: Directly queries `psapi.GetProcessMemoryInfo` for `counters.PrivateUsage`, `kernel32.GetProcessHandleCount` for open handle counts, and `kernel32.CreateToolhelp32Snapshot` / `Process32FirstW` / `Process32NextW` for thread counts.
   - Lines 640–653: Runs `netstat -ano -p tcp` to count loopback `127.0.0.1` sockets mapped to the process PID.
   - Lines 655–740: Queries `pynvml.nvmlDeviceGetComputeRunningProcesses` and `nvidia-smi --query-compute-apps=pid,used_gpu_memory` to attribute VRAM to the Tabby sidecar PID.

3. **OLS Regression Math (`SoakTripwireEvaluator`)**:
   - In `tests/soak/run_8hr_soak.py:878-901`, `calculate_ols_slope` implements standard analytical Ordinary Least Squares:
     $$\text{slope} = \frac{n \sum xy - \sum x \sum y}{n \sum x^2 - (\sum x)^2}, \quad \text{intercept} = \frac{\sum y - \text{slope} \sum x}{n}, \quad R^2 = \frac{(n \sum xy - \sum x \sum y)^2}{[n \sum x^2 - (\sum x)^2][n \sum y^2 - (\sum y)^2]}$$
   - No mock arrays or hardcoded coefficients are present; calculations are computed from live arrays of time (in hours) vs Private Bytes and OS handle counts.
   - Lines 860, 977, 984: Employs `min_drift_mb_for_slope = 10.0` and `min_drift_handles_for_slope = 10` as a noise-floor gate to prevent micro-second garbage collection fluctuations from creating false tripwires during sub-minute test runs.

4. **Scripted Fault Injections**:
   - **Gaming Mode Evacuation** (`lines 1289–1350`): Invokes `GamingModeController.activate()`, measures evacuation duration with `time.perf_counter()`, verifies turn blocking while unloaded, calls `deactivate()`, reloads model, and records `evacuation_deadline_passed = t_evac <= 2.0`.
   - **Mid-Turn Cancel** (`lines 1351–1432`): Obtains baseline `{t for t in asyncio.all_tasks() if not t.done()}`, issues cancellation event during token delta, verifies emission of `turn.canceled` and suppression of `turn.completed`, diffs active tasks to confirm `leaked_tasks == 0`, asserts `len(agent_loop._active_cancels) == 0`, and executes a follow-up recovery turn.
   - **Job Object Sidecar Restart** (`lines 1433–1493`): Spawns sacrificial child process inside `Win32JobSupervisor`, verifies `ActiveProcesses == 1`, kills child, verifies `ActiveProcesses == 0`, restarts another process in the job object, confirms `ActiveProcesses == 1`, and tears down cleanly.
   - **Host APM Sleep & Winlogon Lock** (`lines 2100–2110`): Transparently marked as `skipped` with clear rationale regarding headless execution boundaries rather than faking execution.

5. **Artifact Generation & Authenticity**:
   - Independent verification command executed:
     `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode custom --duration-minutes 0.5 --warmup-minutes 0.1 --sample-interval-seconds 2 > aud_m3.txt 2>&1"`
   - Output log confirmed 211 turns executed in 30.0s, 15 telemetry snapshots taken, all invariants satisfied, and exit code 0.
   - Inspecting `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md` revealed dynamic, real-time overwrite with matching timestamps (`2026-10-07T17:39:51.814615+00:00`), 211 turns, and authentic ASCII sparklines.
   - `tasklist | findstr /i ping.exe` returned exit code 1 (zero orphaned processes).
   - `pytest tests/soak/test_soak_endurance.py -v -m soak` passed 5/5 in 4.16s.
   - `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` passed 13/13 in 0.9s.

---

## 2. Logic Chain

1. **Integrity Mode Conformance**:
   - Ground truth constraint from `ORIGINAL_REQUEST.md:8` is `Integrity mode: development`.
   - Development mode allows library usage, modular code structures, and mock profiles for offline hardware testing, but strictly prohibits hardcoded outputs, dummy facades with fake returns, and fabricated verification artifacts.
   - Phase 1 mode-agnostic analysis and Phase 2 development-mode flagging both confirm zero integrity violations.

2. **Authenticity of OS & Kernel Operations**:
   - `Win32JobSupervisor` is not a facade: it makes genuine Win32 system calls to `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, and `QueryInformationJobObject`. Real OS handle IDs (e.g., `handle=1192`) and real PIDs (e.g., `PID 20424`, `PID 37176`) are passed and managed.
   - Process termination via `TerminateJobObject` and `CloseHandle` cleanly reaps all assigned child processes without leaving orphans.

3. **Telemetry & Statistical Rigor**:
   - Telemetry queries genuine Windows kernel memory structures (`PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`), process handles, and toolhelp thread snapshots without external dependencies.
   - `SoakTripwireEvaluator` executes mathematically exact OLS linear regression slope and $R^2$ calculations. The 10 MB noise floor gate is appropriate systems engineering practice to avoid dividing microsecond GC noise by near-zero time denominators while ensuring true multi-hour drift (>50 MB/h) is caught.

4. **Fault Injections & Lifecycle Verification**:
   - Fault injections actually exercise the code under test: `GamingModeFaultInjector` runs `time.perf_counter()` against 2.0s; `MidTurnCancelFaultInjector` audits `asyncio.all_tasks()`; `JobObjectSidecarFaultInjector` verifies kernel accounting transitions ($1 \to 0 \to 1$); and `VramRecoveryOracle` checks 4 stages of VRAM memory delta.
   - Artifacts in `logs/` and `docs/benchmarks/` are real outputs produced by runner execution, not pre-fabricated static files.

---

## 3. Caveats

- **Host Sleep/Resume & Session Lock**:
  In accordance with ADR-0002 §5, programmatic APM suspend and Winlogon lock/unlock cannot be executed headlessly without interactive desktop sessions or dedicated hardware driver hooks. The runner explicitly and honestly logs these two faults as `status: skipped` with reasons documented in `soak_results.json` and `soak_test_report.md`. This is genuine, honest engineering rather than a facade.
- **Offline GPU Mode**:
  When invoked without `--gpu`, the runner utilizes mock VRAM state tracking and nominal 32°C thermals to permit deterministic, offline CI execution while preserving all tripwire evaluation logic.

---

## 4. Conclusion

**Verdict: CLEAN**.

Milestone 3 (`tests/soak/run_8hr_soak.py`) demonstrates full integrity:
- Zero hardcoded outputs, zero facade implementations, and zero fabricated logs.
- Native Win32 Job Object kernel calls and OS telemetry functions are authentically implemented and verified.
- Ordinary Least Squares regression math is mathematically sound and derived from live data.
- Fault injections enforce real deadlines, task sets, and kernel accounting counters.
- Benchmark artifacts are dynamically and cleanly generated by the runner.
- Zero regressions exist across M1 Python soak tests (5/5 passed) and M2 Tauri supervisor integration tests (13/13 passed).

---

## 5. Verification Method

To independently reproduce the forensic verification:

1. **Verify Win32 Job Object & Short Endurance Run**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode custom --duration-minutes 0.5 --warmup-minutes 0.1 --sample-interval-seconds 2 > aud_m3.txt 2>&1"
   ```
   Inspect `aud_m3.txt`, verify exit code 0 and `SOAK TEST COMPLETED SUCCESSFULLY: ALL INVARIANTS GREEN`, then delete `aud_m3.txt`.

2. **Verify Dynamic Generation of Artifacts**:
   - Check `logs/soak_results.json`: verify `timestamp_utc`, `total_turns`, and `samples_count` match the run.
   - Check `docs/benchmarks/soak_test_report.md`: verify summary metrics, fault matrix, and ASCII sparklines match the run.

3. **Verify Zero Orphaned Processes**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   Confirm exit code 1 (no ping processes found).

4. **Verify Milestone 1 & Milestone 2 Suites**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"
   cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"
   ```
   Confirm 5/5 pytest soak tests and 13/13 cargo tests pass cleanly.
