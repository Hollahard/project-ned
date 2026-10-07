# Forensic Audit Report: Milestone 2 — Rust Tauri Supervisor Endurance Contract

**Work Product**: `apps/desktop/src-tauri/src/processes.rs`, `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`  
**Profile**: General Project / Project Friday  
**Integrity Mode**: Development Mode (per `ORIGINAL_REQUEST.md`)  
**Auditor Identity**: Forensic Auditor (`teamwork_preview_auditor_m2_1`)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Verdict**: **CLEAN**

---

## Forensic Audit Summary

| Check | Target | Status | Forensic Detail |
|---|---|---|---|
| **1. Genuine Win32 HANDLE** | `JobObject::raw_handle` | **PASS** | Returns actual `self.handle` allocated by `CreateJobObjectW`. Also implements `AsRawHandle`. |
| **2. Real Kernel Limit Queries** | `QueryInformationJobObject` | **PASS** | Queries real kernel `JobObjectExtendedLimitInformation`. Confirms `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is set and `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is 0. |
| **3. Multi-Process Concurrency** | 3 child workers | **PASS** | Spawns 3 real `ping.exe` child workers. `AssignProcessToJobObject` assigns them, `IsProcessInJob` validates containment, `QueryInformationJobObject` confirms `ActiveProcesses >= 3`. |
| **4. Kernel Kill-On-Close** | `drop(job)` | **PASS** | Dropping `job` closes the last handle. Windows kernel reaps all 3 workers within ~0.15s. Zero orphaned processes left. |
| **5. OS Resource Measurement** | Handle & Thread Tripwires | **PASS** | Uses real Win32 `GetProcessHandleCount` and `CreateToolhelp32Snapshot` to measure handles (`delta <= 5`) and threads (`delta <= 1`) across 50 iterations. |
| **6. Absence of Facades / Hardcoded Bypasses** | Full test suite | **PASS** | Zero dummy returns, zero mocked bypasses, zero pre-populated verification artifacts. |
| **7. Clean Test Execution** | `cargo test` suite | **PASS** | All 15 tests (5 unit + 10 integration) compile and pass with 0 warnings and 0 failures. |

---

## 1. Observation

### 1.1 Direct Inspection of `apps/desktop/src-tauri/src/processes.rs`
Examined lines 138–142 and 154–158:
```rust
    /// Return raw Win32 HANDLE for querying job object information and limits.
    pub fn raw_handle(&self) -> HANDLE {
        self.handle
    }
```
and:
```rust
impl std::os::windows::io::AsRawHandle for JobObject {
    fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
        self.handle as _
    }
}
```
- Line 56 initializes `self.handle = unsafe { CreateJobObjectW(null(), null()) }`.
- `raw_handle()` returns this exact native Win32 handle.
- No facade, dummy constant, or hardcoded mock handle is returned.

### 1.2 Direct Inspection of `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`
1. **Kernel limit verification (lines 194–229)**:
   - Invokes Win32 `QueryInformationJobObject(job.raw_handle(), JobObjectExtendedLimitInformation, ...)`
   - Asserts `limit_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0`
   - Asserts `limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`
   - Asserts `active_limit == 0`
2. **Process spawning and containment (lines 231–276)**:
   - Spawns 3 real child worker processes via `Command::new("cmd.exe").args(["/c", "ping", "127.0.0.1", "-n", "30"])`.
   - Calls `job.assign(worker)` which calls Win32 FFI `AssignProcessToJobObject`.
   - Calls `job.contains_process(worker)` which calls Win32 FFI `IsProcessInJob`.
   - Calls `job.query_active_process_count()` which queries `JobObjectBasicAccountingInformation`.
3. **Kernel teardown on drop (lines 278–311)**:
   - Executes `drop(job)`, triggering `CloseHandle(self.handle)`.
   - Polls `workers.iter_mut().all(|w| matches!(w.try_wait(), Ok(Some(_))))` for up to 3 seconds.
   - Asserts all 3 workers transitioned to `status.is_some()`.
4. **OS Resource measurement (lines 41–79 and 317–442)**:
   - `get_current_handle_count()` directly invokes Win32 `GetProcessHandleCount(GetCurrentProcess(), &mut count)`.
   - `get_current_thread_count()` directly invokes Win32 `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)` and iterates via `Thread32First`/`Thread32Next` filtering on `th32OwnerProcessID == GetCurrentProcessId()`.
   - Executes 10 warmup cycles followed by 50 full iterations of session creation, GPU telemetry, VRAM preflight, and preflight diagnostics.
   - Enforces `assert!(handle_delta <= 5)` and `assert!(thread_delta <= 1)`.

### 1.3 Independent Execution of Build & Test Suite
Executed the build and test command per `GEMINI.md`:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > aud_m2.txt 2>&1"
```
Inspected `aud_m2.txt`:
```text
     Finished `test` profile [unoptimized + debuginfo] target(s) in 0.32s
     Running unittests src\lib.rs (apps\desktop\src-tauri\target\debug\deps\friday_supervisor-2498de27c0661a58.exe)

running 5 tests
test first_launch::tests::test_validate_safe_windows_path_rejects_trailing_dots_and_spaces ... ok
test first_launch::tests::test_check_first_launch_status_for_nonexistent_dir ... ok
test first_launch::tests::test_validate_safe_windows_path_rejects_reserved_device_names ... ok
test first_launch::tests::test_validate_safe_windows_path_rejects_alternate_data_streams ... ok
test first_launch::tests::test_run_preflight_diagnostics_passes_with_rtx5090_and_job_object ... ok

test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running unittests src\main.rs (apps\desktop\src-tauri\target\debug\deps\friday-5fe69a2a89b48580.exe)

running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

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

   Doc-tests friday_supervisor

running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```
Output log `aud_m2.txt` was inspected and deleted immediately.

### 1.4 Post-Test Orphan Process Check
Command:
```cmd
cmd.exe /c "tasklist | findstr /i ping.exe"
```
Exited with return code 1 and 0 matching lines, proving that all spawned child workers were cleanly reaped by the Windows kernel.

---

## 2. Logic Chain

1. **Job Object Implementation Authenticity**:
   - `JobObject::raw_handle` returns `self.handle`. In `JobObject::new()`, `self.handle` is created using the real Win32 kernel API `CreateJobObjectW`.
   - `JobObject` implements `std::os::windows::io::AsRawHandle` returning `self.handle as _`.
   - Therefore, there is no facade or dummy handle.
2. **Win32 Kernel Invariant Verification**:
   - `test_job_object_limits_permit_concurrency_and_kill_on_close` directly queries the Windows kernel via `QueryInformationJobObject`. It verifies that `LimitFlags` has `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` enabled and does NOT have `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`.
   - 3 real `ping.exe` child processes are assigned to the Job Object via `AssignProcessToJobObject`.
   - `IsProcessInJob` confirms membership for all 3 processes.
   - When `JobObject` is dropped, `CloseHandle(self.handle)` closes the Job Object, triggering kernel termination. `worker.try_wait()` verifies that all 3 child processes terminate, and `tasklist` confirms 0 surviving processes.
3. **OS Resource Leak Measurement**:
   - `test_supervisor_repeated_operations_no_handle_or_thread_leak` uses real Win32 APIs `GetProcessHandleCount` and `CreateToolhelp32Snapshot`.
   - The test warms up Tokio and socket pools over 10 iterations, takes baseline counts, performs 50 iterations of 4 supervisor operations (create session, telemetry polling, preflight check, environment diagnostics), and computes handle and thread deltas.
   - The thresholds `handle_delta <= 5` and `thread_delta <= 1` are satisfied.
4. **Integrity Mode Assessment**:
   - Under `Development Mode` (per `ORIGINAL_REQUEST.md`), hardcoded test results, facade implementations, and fabricated verification outputs are strictly prohibited.
   - None of these prohibited patterns exist.
   - Therefore, the verdict is **CLEAN**.

---

## 3. Caveats

- **No Caveats**: All tests executed on the native Windows 11 host environment using real Win32 kernel APIs and loopback networking. No external mocks or emulators were required.

---

## 4. Conclusion

Milestone 2 (Rust Tauri Supervisor Endurance Contract) passes all forensic checks with zero integrity violations.
The implementation in `apps/desktop/src-tauri/src/processes.rs` and tests in `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` are genuine, complete, robust, and adhere to all project and workspace rules.

Verdict: **CLEAN**

---

## 5. Verification Method

To independently reproduce the forensic verification:

1. **Run full supervisor test suite**:
   ```cmd
   cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > aud_m2.txt 2>&1"
   ```
2. **Inspect and delete log**:
   Confirm that all 15 tests pass with 0 failures, then delete `aud_m2.txt`.
3. **Verify zero orphaned processes**:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   Must exit with code 1 and no matches.
