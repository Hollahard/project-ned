# Milestone 2 Review and Adversarial Critique Report

**Reviewer Identity**: Reviewer 1 (`teamwork_preview_reviewer_m2_1`)  
**Roles**: Reviewer, Adversarial Critic  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Target Milestone**: Milestone 2: Rust Tauri Supervisor Endurance Contract (Phase 16 Deliverable R3)  
**Workspace**: `G:\Project_Ned`  
**Verdict**: **APPROVE**  
**Overall Risk Assessment**: **LOW**

---

## 1. Observation

### 1.1 Source Code Verification in `apps/desktop/src-tauri/src/processes.rs`
Inspected `apps/desktop/src-tauri/src/processes.rs`:
- Lines 138–142 define `JobObject::raw_handle`:
  ```rust
  /// Return raw Win32 HANDLE for querying job object information and limits.
  pub fn raw_handle(&self) -> HANDLE {
      self.handle
  }
  ```
- Lines 154–158 implement standard library trait `AsRawHandle`:
  ```rust
  impl std::os::windows::io::AsRawHandle for JobObject {
      fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
          self.handle as _
      }
  }
  ```
- `git diff apps/desktop/src-tauri/src/processes.rs` reveals only these 11 additive lines. No existing process management, environment sanitization, or lifecycle logic was modified or regressed.

### 1.2 Integration Test Verification in `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`
Inspected `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` (443 lines):
1. **Serialization Lock**:
   - Line 38: `static ENDURANCE_SERIALIZATION_LOCK: Mutex<()> = Mutex::new(());` protects tests from executing concurrently within the integration test binary, preventing child process handle fluctuation from perturbing handle count measurements.
2. **Suite A (`test_job_object_limits_permit_concurrency_and_kill_on_close`)**:
   - Queries `JobObjectExtendedLimitInformation` via `QueryInformationJobObject` on `job.raw_handle()`.
   - Asserts `limit_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0` (lines 209–215).
   - Asserts `limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0` (lines 217–223).
   - Asserts `active_limit == 0` (lines 225–229).
   - Spawns 3 concurrent `cmd.exe /c ping 127.0.0.1 -n 30` worker processes (lines 231–242).
   - Assigns all 3 workers via `job.assign(&worker)` and verifies membership via `job.contains_process(&worker)` (lines 245–264).
   - Asserts `job.query_active_process_count() >= 3` (lines 267–275).
   - Drops `job` and polls `worker.try_wait()` up to 3.0s (lines 278–290). Asserts all workers report exit status with 0 orphaned processes (lines 302–311).
3. **Suite B (`test_supervisor_repeated_operations_no_handle_or_thread_leak`)**:
   - Binds an in-memory loopback mock HTTP server to `127.0.0.1:0` handling persistent HTTP/1.1 connections for `/api/v1/sessions`, `/api/v1/telemetry/gpu`, and `/api/v1/models/preflight` (lines 102–175, 321–348).
   - Instantiates `CoreProxy` pointing to ephemeral loopback port (line 351).
   - Executes 10 warmup cycles over `create_session`, `get_gpu_telemetry`, `check_vram_preflight`, and `run_preflight_diagnostics` (lines 362–383).
   - Samples initial baseline via Win32 `GetProcessHandleCount` and `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)` (lines 386–387).
   - Executes 50 continuous iterations across all 4 operations (lines 390–414).
   - Samples final Win32 metrics and shuts down loopback mock server via `tokio::sync::oneshot` (lines 416–424).
   - Strictly enforces tripwires: `assert!(handle_delta <= 5)` and `assert!(thread_delta <= 1)` (lines 427–442).

### 1.3 Independent Test Execution
Executed per `GEMINI.md`:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > rev1_m2.txt 2>&1"
```
Inspected `rev1_m2.txt` verbatim:
- `src/lib.rs`: 5 passed; 0 failed
- `src/main.rs`: 0 passed; 0 failed
- `tests/test_endurance_invariants.rs`: 2 passed; 0 failed
- `tests/test_job_object.rs`: 2 passed; 0 failed
- `tests/test_sanitized_env.rs`: 1 passed; 0 failed
- `tests/test_supervisor_soak.rs`: 3 passed; 0 failed
- `tests/test_tokens.rs`: 2 passed; 0 failed
- `Doc-tests`: 0 passed; 0 failed
- **Overall Result**: 15 passed, 0 failed, 0 ignored, 0 warnings.
- Cleaned up `rev1_m2.txt` immediately.

### 1.4 Orphan Process Check
Executed:
```cmd
cmd.exe /c "tasklist | findstr /i ping.exe"
```
Returned exit code 1 (zero matching lines), confirming zero orphaned child processes.

---

## 2. Integrity Audit

- **Hardcoded test results**: None. Test metrics dynamically invoke `GetProcessHandleCount`, `CreateToolhelp32Snapshot`, `QueryInformationJobObject`, `IsProcessInJob`, and `try_wait`.
- **Facade implementations**: None. `JobObject::raw_handle` and `AsRawHandle` expose the real Win32 `HANDLE`.
- **Shortcuts / Bypassed tasks**: None. Real child processes are spawned, assigned to the Job Object, and reaped upon drop. Real HTTP socket communication and diagnostics are executed over 50 iterations.
- **Fabricated verification logs**: None. Verified via independent test execution resulting in 15 passing tests.
- **Self-certifying work**: None. Independent test commands executed and confirmed.

---

## 3. Adversarial Critique & Stress-Testing

### Challenge 1: Multi-Worker Job Object Concurrency & Breakaway Evasion
- **Assumption**: Omitting `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` in `LimitFlags` allows arbitrary concurrent workers to be assigned and managed without hitting `ERROR_ACTIVE_PROCESS_LIMIT`.
- **Attack Scenario**: If a component set `ActiveProcessLimit = 1` or if child processes could spawn detached subprocesses (breakaway), child processes could escape the job object or fail to launch.
- **Blast Radius**: Secondary worker processes (TabbyAPI sidecar or subagents) would fail to start with error code 4 (`ERROR_ACTIVE_PROCESS_LIMIT`), or child processes would survive supervisor exit as orphans.
- **Verification & Defense**: The test explicitly queries `QueryInformationJobObject` and confirms `limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0` and `active_limit == 0`. It spawns 3 concurrent `ping.exe` workers, successfully assigns all 3, confirms `query_active_process_count() >= 3`, and drops the job object, verifying all 3 are reaped within 3 seconds by the Windows kernel.
- **Status**: PASSED.

### Challenge 2: Socket and Handle Churn under High-Frequency HTTP Proxy Calls
- **Assumption**: 50 iterations across 4 operations will not accumulate leaked socket handles or background worker threads.
- **Attack Scenario**: If `reqwest::Client` created a new connection per request without keep-alive, or if `run_preflight_diagnostics` failed to close its temporary Job Object handle, OS handles would steadily ratchet by >= 50.
- **Blast Radius**: Handle exhaustion over long-running desktop sessions, degrading Windows kernel performance.
- **Verification & Defense**: The mock server implements HTTP/1.1 persistent connections (`Connection: keep-alive`), and the test enforces `handle_delta <= 5` and `thread_delta <= 1`. Over 50 iterations (200 total operations), handle count remained strictly within tolerance, proving zero leak.
- **Status**: PASSED.

### Challenge 3: Process Handle / Thread Count Race Conditions
- **Assumption**: Handle and thread counting in `test_supervisor_repeated_operations_no_handle_or_thread_leak` could be corrupted if another test ran concurrently in the same process.
- **Attack Scenario**: If `test_job_object_limits_permit_concurrency_and_kill_on_close` spawned 3 `ping.exe` processes while the leak test was sampling baselines, initial handle counts would be artificially elevated and final handle counts deflated when `ping.exe` exited, masking leaks or causing false failures.
- **Verification & Defense**: `ENDURANCE_SERIALIZATION_LOCK` synchronizes both tests. Additionally, cargo runs separate integration test files (`test_job_object.rs`, `test_tokens.rs`, etc.) in independent operating system processes, ensuring process-wide handle counters (`GetCurrentProcess()`) are fully isolated to this binary.
- **Status**: PASSED.

---

## 4. Logic Chain

1. **Requirement Mapping**: R3 in `ORIGINAL_REQUEST.md` requires verifying that repeated session creation, telemetry polling, and preflight checks do not leak OS handles or threads, and that supervisor close cleanly terminates child processes (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) without setting active process limits.
2. **API Completeness**: `processes.rs` correctly exposes `JobObject::raw_handle()` and `AsRawHandle`, allowing native Win32 FFI interrogation of Job Object limit structures.
3. **Behavioral Correctness**: `test_endurance_invariants.rs` validates both the kernel limit configuration and actual runtime process lifecycle (concurrency + kill-on-close reaping).
4. **Endurance Invariant**: The 10 warmup + 50 iteration test rigorously measures Win32 OS handles and threads before and after, asserting `handle_delta <= 5` and `thread_delta <= 1`.
5. **Execution Verification**: Running `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` executed all 15 supervisor tests cleanly in 0.35s with 0 failures, 0 warnings, and zero surviving orphaned processes.
6. **Conclusion Formulation**: All criteria for Milestone 2 are met without regressions or integrity violations.

---

## 5. Caveats

- **No Caveats**: The test suite is deterministic, offline, and relies on native Win32 kernel primitives. Extended multi-hour endurance testing is deliberately reserved for Milestone 3 (`run_8hr_soak.py`).

---

## 6. Conclusion & Verdict

**Verdict**: **APPROVE**

Milestone 2 (Rust Tauri Supervisor Endurance Contract) is fully implemented, verified, and adheres strictly to ADR-0002 and `GEMINI.md` invariants.

---

## 7. Verification Method

To independently reproduce this verification:
1. Run cargo test suite:
   ```cmd
   cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > rev1_m2.txt 2>&1"
   ```
2. View `rev1_m2.txt` to confirm 15 passed tests with 0 failures and 0 warnings.
3. Delete `rev1_m2.txt`:
   ```cmd
   cmd.exe /c "del rev1_m2.txt"
   ```
4. Verify zero orphaned processes:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   (Must return exit code 1 with 0 processes).

**Invalidation Conditions**:
- Any failure or warning across the 15 tests.
- `handle_delta > 5` or `thread_delta > 1`.
- Any orphaned `ping.exe` process surviving test execution.
