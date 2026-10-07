# Milestone 2 Challenger 1 Report: Job Object Concurrency & Termination Invariants

**Challenger**: Challenger 1 (`teamwork_preview_challenger_m2_1`)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Milestone**: Milestone 2: Rust Tauri Supervisor Endurance Contract  
**Verdict**: **APPROVE**  

---

## 1. Observation

### 1.1 Direct Source Code Inspection

1. **`apps/desktop/src-tauri/src/processes.rs`**:
   - Lines 55–82 (`JobObject::new`):
     ```rust
     let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
     info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

     let ret = unsafe {
         SetInformationJobObject(
             handle,
             JobObjectExtendedLimitInformation,
             &info as *const _ as *const c_void,
             std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
         )
     };
     ```
   - Lines 138–141:
     ```rust
     /// Return raw Win32 HANDLE for querying job object information and limits.
     pub fn raw_handle(&self) -> HANDLE {
         self.handle
     }
     ```
   - Lines 154–158:
     ```rust
     impl std::os::windows::io::AsRawHandle for JobObject {
         fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
             self.handle as _
         }
     }
     ```

2. **`apps/desktop/src-tauri/tests/test_endurance_invariants.rs`**:
   - Lines 191–203:
     ```rust
     let mut limit_info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
     let mut return_length: u32 = 0;
     let query_ret = unsafe {
         QueryInformationJobObject(
             job.raw_handle(),
             JobObjectExtendedLimitInformation,
             &mut limit_info as *mut _ as *mut c_void,
             std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
             &mut return_length as *mut u32,
         )
     };
     assert_ne!(query_ret, 0, "QueryInformationJobObject must succeed");
     ```
   - Lines 205–228:
     ```rust
     let limit_flags = limit_info.BasicLimitInformation.LimitFlags;
     let active_limit = limit_info.BasicLimitInformation.ActiveProcessLimit;

     assert_ne!(
         limit_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
         0,
         "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE must be enabled in LimitFlags (found: 0x{:08X})",
         limit_flags
     );

     assert_eq!(
         limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
         0,
         "JOB_OBJECT_LIMIT_ACTIVE_PROCESS must NOT be set in LimitFlags (found: 0x{:08X})",
         limit_flags
     );

     assert_eq!(
         active_limit, 0,
         "ActiveProcessLimit must be 0 (unlimited active processes permitted)"
     );
     ```
   - Lines 231–276:
     Spawns 3 concurrent child worker processes (`cmd.exe /c ping 127.0.0.1 -n 30`), assigns all 3 via `job.assign(worker)`, verifies membership via `job.contains_process(worker)`, and asserts `job.query_active_process_count() >= 3`.
   - Lines 278–310:
     Calls `drop(job)` and polls `worker.try_wait()` until all 3 report exit status (`Some(status)`).

### 1.2 Targeted Test Execution

Command executed per GEMINI.md:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants test_job_object_limits_permit_concurrency_and_kill_on_close > chal1_m2.txt 2>&1"
```
Log inspection of `chal1_m2.txt`:
```text
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.35s
     Running tests\test_endurance_invariants.rs (apps\desktop\src-tauri\target\debug\deps\test_endurance_invariants-941ac4f1d843015c.exe)

running 1 test
test test_job_object_limits_permit_concurrency_and_kill_on_close ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.06s
```
Temporary log `chal1_m2.txt` deleted immediately.

### 1.3 Full Test Suite Regression Execution

Command executed:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > full_cargo_test.txt 2>&1"
```
Log inspection of `full_cargo_test.txt`:
```text
running 5 tests
test first_launch::tests::test_validate_safe_windows_path_rejects_alternate_data_streams ... ok
test first_launch::tests::test_validate_safe_windows_path_rejects_reserved_device_names ... ok
test first_launch::tests::test_validate_safe_windows_path_rejects_trailing_dots_and_spaces ... ok
test first_launch::tests::test_check_first_launch_status_for_nonexistent_dir ... ok
test first_launch::tests::test_run_preflight_diagnostics_passes_with_rtx5090_and_job_object ... ok
test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

running 2 tests
test test_job_object_limits_permit_concurrency_and_kill_on_close ... ok
test test_supervisor_repeated_operations_no_handle_or_thread_leak ... ok
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.16s

running 2 tests
test test_job_object_creation_and_limits ... ok
test test_job_object_assign_and_kill_on_drop ... ok
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.31s

running 1 test
test test_sanitized_environment_strips_parent_secrets ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

running 3 tests
test test_repeated_preflight_and_diagnostics_zero_handle_leak ... ok
test test_job_object_membership_asserted_in_rust ... ok
test test_supervisor_exit_reaps_core_and_tabby_sidecars ... ok
test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.41s

running 2 tests
test test_canonical_args_hash_is_order_independent ... ok
test test_approval_manager_mint_and_single_use_consume ... ok
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```
Total: 15 passed, 0 failed, 0 ignored, 0 warnings.
Temporary log `full_cargo_test.txt` deleted immediately.

### 1.4 Zero Orphaned Process Verification

Command executed:
```cmd
cmd.exe /c "tasklist | findstr /i ping.exe > ping_check.txt 2>&1"
```
Returned exit code 1 (zero matching lines). `ping_check.txt` inspected and deleted.

---

## 2. Logic Chain

1. **Adversarial Assessment of Limit Querying**:
   - `QueryInformationJobObject` on line 197 explicitly passes `JobObjectExtendedLimitInformation` (class enum value 9 in Win32 API).
   - This ensures the test queries the exact extended limits structure (`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`) containing both `BasicLimitInformation.LimitFlags` and `BasicLimitInformation.ActiveProcessLimit`.
   - The test asserts that `QueryInformationJobObject` succeeds (`assert_ne!(query_ret, 0)`).

2. **Adversarial Assessment of Active Process Limits**:
   - If `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (0x00000008) were set, or if `ActiveProcessLimit` were non-zero (e.g. 1), the Job Object would restrict concurrency to 1 child process, failing when subsequent worker processes (such as Core + TabbyAPI + MCP sidecars) are assigned.
   - The test strictly asserts:
     - `limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`
     - `active_limit == 0`
   - Simultaneously, it asserts that `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x00002000) is enabled.

3. **Empirical Multi-Worker Concurrency & Reaping**:
   - 3 separate worker processes (`cmd.exe /c ping 127.0.0.1 -n 30`) were spawned simultaneously.
   - All 3 were assigned to the Job Object without encountering `ERROR_ACTIVE_PROCESS_LIMIT` (Win32 error 4).
   - `job.contains_process(&worker)` confirmed that each worker was accepted into the Job Object.
   - `job.query_active_process_count()` verified `active_count >= 3`.
   - Upon `drop(job)`, `CloseHandle` closed the Job Object handle. The Windows kernel immediately terminated all assigned child processes. The test finished in 0.06s instead of waiting 30s for pings to expire, confirming kernel-level termination.
   - The tasklist check confirmed no residual `ping.exe` processes remained in the operating system.

---

## 3. Caveats

- **No Caveats**: All invariants were empirically executed and verified on native Windows 11 using native Win32 FFI calls without relying on third-party mock tools.

---

## 4. Conclusion

**Verdict: APPROVE**

The implementation of `JobObject::raw_handle()` and `AsRawHandle` in `apps/desktop/src-tauri/src/processes.rs` together with the integration test `test_job_object_limits_permit_concurrency_and_kill_on_close` in `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` meets all requirements of Milestone 2 (Phase 16 Deliverable R3):
1. Specifically queries `JobObjectExtendedLimitInformation`.
2. Verifies that `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is NOT set and `ActiveProcessLimit == 0`.
3. Verifies that 3 workers run concurrently and are cleanly reaped on drop leaving zero orphans.
4. Passes all tests cleanly in 0.06s with zero regressions across the 15 supervisor tests.

---

## 5. Verification Method

To independently reproduce this verification:
1. Run the targeted test per GEMINI.md:
   ```cmd
   cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants test_job_object_limits_permit_concurrency_and_kill_on_close > chal1_m2.txt 2>&1"
   ```
2. Verify exit code 0 and `test result: ok. 1 passed; 0 failed`.
3. Delete `chal1_m2.txt`.
4. Verify no orphaned worker processes:
   ```cmd
   cmd.exe /c "tasklist | findstr /i ping.exe"
   ```
   (Must return exit code 1 with zero output).
