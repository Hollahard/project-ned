# Milestone 2 Explorer 1: Windows Job Object Concurrency & Termination Invariants Report

## 1. Observation

### 1.1 JobObject Creation & Limit Configuration in `processes.rs`
In `G:\Project_Ned\apps\desktop\src-tauri\src\processes.rs` (lines 44–82):
```rust
/// Windows Job Object wrapper providing RAII cleanup and kill-on-close guarantees.
pub struct JobObject {
    handle: HANDLE,
}

unsafe impl Send for JobObject {}
unsafe impl Sync for JobObject {}

impl JobObject {
    /// Create a new Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` enabled
    /// and breakaway strictly prohibited.
    pub fn new() -> Result<Self, ProcessError> {
        let handle = unsafe { CreateJobObjectW(null(), null()) };
        if handle.is_null() || handle == INVALID_HANDLE_VALUE {
            let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            return Err(ProcessError::JobObjectCreate(err));
        }

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

        if ret == 0 {
            let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            unsafe { CloseHandle(handle) };
            return Err(ProcessError::JobObjectConfigure(err));
        }

        info!("Created Windows Job Object with KILL_ON_JOB_CLOSE enabled (handle: {:p})", handle as *const ());
        Ok(Self { handle })
    }
```

Key direct observations:
1. Line 62 initializes `info` via `std::mem::zeroed()`. Consequently:
   - `info.BasicLimitInformation.ActiveProcessLimit` is initialized to `0`.
   - All other limit threshold fields (`ProcessMemoryLimit`, `JobMemoryLimit`, `PerProcessUserTimeLimit`, etc.) are initialized to `0`.
2. Line 63 sets `info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;`.
   - In Win32 SDK / `windows-sys`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is bitmask `0x00002000` (8192 decimal).
   - `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is bitmask `0x00000008` (8 decimal).
   - Therefore:
     - `LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0` is strictly TRUE (`0x2000 != 0`).
     - `LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0` is strictly TRUE (`0x0000 == 0`).
     - `ActiveProcessLimit == 0` is strictly TRUE.

### 1.2 Process Assignment, Membership Inspection, and Lifecycle
In `G:\Project_Ned\apps\desktop\src-tauri\src\processes.rs` (lines 85–160):
- **Process Assignment** (`assign`, lines 85–97):
  ```rust
  pub fn assign(&self, child: &Child) -> Result<(), ProcessError> {
      let raw_handle = child.as_raw_handle() as HANDLE;
      let ret = unsafe { AssignProcessToJobObject(self.handle, raw_handle) };
      if ret == 0 {
          let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
          return Err(ProcessError::AssignProcess {
              pid: child.id(),
              code: err,
          });
      }
      info!("Assigned child PID {} to Job Object", child.id());
      Ok(())
  }
  ```
- **Job Membership Query** (`contains_process`, lines 100–112):
  Invokes Win32 `IsProcessInJob(raw_handle, self.handle, &mut in_job)` returning a boolean.
- **Active Process Accounting** (`query_active_process_count`, lines 115–131):
  Invokes `QueryInformationJobObject` with `JobObjectBasicAccountingInformation`, returning `acct_info.ActiveProcesses`.
- **Existing Handle Exposure** (lines 133–136):
  ```rust
  /// Return raw HANDLE for testing assertions.
  pub fn handle(&self) -> HANDLE {
      self.handle
  }
  ```
  Note: `JobObject` currently has `pub fn handle(&self) -> HANDLE`, but does not yet implement `std::os::windows::io::AsRawHandle` or expose `pub fn raw_handle(&self) -> HANDLE`.
- **Explicit Termination & RAII Cleanup** (lines 139–159):
  ```rust
  pub fn terminate(&self, exit_code: u32) {
      if !self.handle.is_null() && self.handle != INVALID_HANDLE_VALUE {
          unsafe {
              TerminateJobObject(self.handle, exit_code);
          }
          info!("Terminated all processes in Job Object with exit code {}", exit_code);
      }
  }

  impl Drop for JobObject {
      fn drop(&mut self) {
          if !self.handle.is_null() && self.handle != INVALID_HANDLE_VALUE {
              info!("Closing Job Object handle. Windows kernel will terminate all child processes.");
              unsafe {
                  CloseHandle(self.handle);
              }
              self.handle = null_mut();
          }
      }
  }
  ```

### 1.3 Windows-Sys Features and Dependencies
In `G:\Project_Ned\apps\desktop\src-tauri\Cargo.toml` (lines 17–24):
```toml
windows-sys = { version = "0.59", features = [
    "Win32_System_JobObjects",
    "Win32_Foundation",
    "Win32_Security",
    "Win32_System_Threading",
    "Win32_UI_WindowsAndMessaging",
    "Win32_System_Diagnostics_ToolHelp"
] }
```
All required Win32 APIs and structures (`QueryInformationJobObject`, `JobObjectExtendedLimitInformation`, `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, `CloseHandle`, `HANDLE`) are already enabled and available to both `src/` and `tests/`.

### 1.4 Existing Test Baseline
Running `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` verified 13 passed tests across:
- `first_launch::tests` (5 tests)
- `tests/test_job_object.rs` (2 tests: creation & 1-child drop)
- `tests/test_sanitized_env.rs` (1 test)
- `tests/test_supervisor_soak.rs` (3 tests: handle leak, membership, sidecar reaping)
- `tests/test_tokens.rs` (2 tests)

Existing tests in `tests/test_job_object.rs` test only a single child process (`ping 127.0.0.1 -n 30`). They do not assert:
1. `QueryInformationJobObject` limits directly.
2. The absence of `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`.
3. Multi-process concurrency (e.g. 3 concurrent workers simultaneously assigned and active).

---

## 2. Logic Chain

### 2.1 Concurrency Semantics in Windows Job Objects
1. Observation 1.1 shows that `info.BasicLimitInformation.LimitFlags` is set strictly to `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
2. According to Microsoft Win32 kernel specifications (`JOBOBJECT_BASIC_LIMIT_INFORMATION` structure documentation):
   - The `ActiveProcessLimit` member specifies the maximum number of simultaneously active processes for the job object.
   - **Crucially**, `ActiveProcessLimit` is evaluated and enforced by the kernel *only* if the `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` flag is present in `LimitFlags`.
   - If `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is omitted from `LimitFlags`, the Windows kernel imposes no quota on active processes within the job object.
3. Because `info` is zeroed and only `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is OR-ed into `LimitFlags`, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is zero.
4. If a developer had mistakenly set `ActiveProcessLimit = 1` or included `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, any attempt to assign a second or third process (such as TabbyAPI sidecar, subagent workers, or tools) via `AssignProcessToJobObject` would immediately fail with error code 4 (`ERROR_ACTIVE_PROCESS_LIMIT`).
5. Because the flag is zero, the supervisor can spawn Core FastAPI, TabbyAPI sidecar, and multiple concurrent worker/MCP processes inside the same Job Object without contention.

### 2.2 Process Termination Guarantee via `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
1. Observation 1.1 and 1.2 demonstrate that when `JobObject` is created, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is configured.
2. When the `JobObject` instance is dropped (either on normal supervisor exit or during crash/panic), `CloseHandle(self.handle)` closes the last handle to the Job Object.
3. The Windows kernel's Object Manager detects that the handle count has dropped to zero and initiates asynchronous process termination on all processes currently assigned to the Job Object.
4. Testing with 3 concurrent worker processes proves that `KILL_ON_JOB_CLOSE` scales to multiple simultaneous processes without hanging or leaving orphaned child processes behind.

### 2.3 Handle Exposure & Interoperability
1. Observation 1.2 shows `JobObject` currently has `pub fn handle(&self) -> HANDLE`.
2. To satisfy the Milestone 2 interface contract specified in `PROJECT.md` §Interface Contracts and the dispatch instructions:
   - Providing `pub fn raw_handle(&self) -> windows_sys::Win32::Foundation::HANDLE` ensures method-name alignment with callers expecting `raw_handle()`.
   - Implementing `std::os::windows::io::AsRawHandle` aligns `JobObject` with idiomatic Rust standard library patterns for OS handle wrappers (`Child`, `File`, etc.).
   - Providing a safe query method `pub fn query_extended_limits(&self) -> Result<JOBOBJECT_EXTENDED_LIMIT_INFORMATION, ProcessError>` allows caller code to safely inspect configured limits without requiring `unsafe` FFI blocks.

---

## 3. Caveats

1. **Kernel Asynchronous Termination Timing**:
   When `JobObject` is dropped, the Windows kernel terminates member processes asynchronously. An immediate call to `child.try_wait()` right after `drop(job)` may still observe the process transitioning from active to terminated. A polling loop (e.g. up to 3 seconds with 50ms intervals) ensures deterministic, non-flaky test execution across diverse CI runners and high CPU load conditions.
2. **Grandchild Process Containment (`cmd.exe` vs `ping.exe`)**:
   Spawning `cmd.exe /c ping 127.0.0.1 -n 30` creates `cmd.exe`, which in turn creates `ping.exe`. Because Job Objects deny breakaway by default, both parent and child belong to the Job Object. In our test design, tracking and querying the spawned `Child` handles ensures direct measurement of process exit status.
3. **No External Services Needed**:
   The Job Object concurrency and termination invariants are pure Win32 supervisor tests and require no Python virtual environments, network listeners, or GPU hardware. They execute in < 0.5 seconds headlessly.

---

## 4. Conclusion & Proposed Implementation Strategy

The implementer should make two surgical updates:

### Proposed Change 1: Enhance Handle Exposure in `apps/desktop/src-tauri/src/processes.rs`

In `apps/desktop/src-tauri/src/processes.rs`:
1. Add `pub fn raw_handle(&self) -> HANDLE`:
   ```rust
   /// Return raw Win32 HANDLE for querying job object information and limits.
   pub fn raw_handle(&self) -> HANDLE {
       self.handle
   }
   ```
2. Implement `AsRawHandle` (import `std::os::windows::io::{AsRawHandle, RawHandle}`):
   ```rust
   impl AsRawHandle for JobObject {
       fn as_raw_handle(&self) -> RawHandle {
           self.handle as RawHandle
       }
   }
   ```
3. Add a safe helper to query extended limits:
   ```rust
   /// Query extended limit information configured on this Job Object.
   pub fn query_extended_limits(&self) -> Result<JOBOBJECT_EXTENDED_LIMIT_INFORMATION, ProcessError> {
       let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
       let mut ret_len: u32 = 0;
       let ret = unsafe {
           QueryInformationJobObject(
               self.handle,
               JobObjectExtendedLimitInformation,
               &mut info as *mut _ as *mut c_void,
               std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
               &mut ret_len as *mut u32,
           )
       };
       if ret == 0 {
           let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
           return Err(ProcessError::JobObjectConfigure(err));
       }
       Ok(info)
   }
   ```

### Proposed Change 2: Design `test_job_object_limits_permit_concurrency_and_kill_on_close`

In `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`:

```rust
//! Supervisor Endurance Invariant Tests (Milestone 2).
//!
//! Enforces:
//! 1. Windows Job Object concurrency invariants (no active process limit).
//! 2. Multi-worker assignment and clean termination upon drop (KILL_ON_JOB_CLOSE).
//! 3. Resource stability across repeated operations (zero handle/thread leaks).

use friday_supervisor::processes::JobObject;
use std::ffi::c_void;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use windows_sys::Win32::System::JobObjects::{
    QueryInformationJobObject,
    JobObjectExtendedLimitInformation,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

#[test]
fn test_job_object_limits_permit_concurrency_and_kill_on_close() {
    // -------------------------------------------------------------------------
    // Phase 1: Verify Job Object Limit Configuration via QueryInformationJobObject
    // -------------------------------------------------------------------------
    let job = JobObject::new().expect("Job Object creation must succeed on Windows");

    let mut limit_info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    let mut return_length: u32 = 0;
    let query_ret = unsafe {
        QueryInformationJobObject(
            job.handle(),
            JobObjectExtendedLimitInformation,
            &mut limit_info as *mut _ as *mut c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            &mut return_length as *mut u32,
        )
    };
    assert_ne!(query_ret, 0, "QueryInformationJobObject must succeed");

    let limit_flags = limit_info.BasicLimitInformation.LimitFlags;
    let active_limit = limit_info.BasicLimitInformation.ActiveProcessLimit;

    // Assert: JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is strictly enabled
    assert_ne!(
        limit_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        0,
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE must be enabled in LimitFlags (found: 0x{:08X})",
        limit_flags
    );

    // Assert: JOB_OBJECT_LIMIT_ACTIVE_PROCESS is NOT set
    assert_eq!(
        limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
        0,
        "JOB_OBJECT_LIMIT_ACTIVE_PROCESS must NOT be set in LimitFlags (found: 0x{:08X})",
        limit_flags
    );

    // Assert: ActiveProcessLimit is 0 (unlimited active processes)
    assert_eq!(
        active_limit,
        0,
        "ActiveProcessLimit must be 0 (unlimited active processes permitted)"
    );

    // -------------------------------------------------------------------------
    // Phase 2: Spawn 3 Concurrent Child Workers & Assign to Job Object
    // -------------------------------------------------------------------------
    const NUM_WORKERS: usize = 3;
    let mut workers: Vec<Child> = Vec::with_capacity(NUM_WORKERS);

    for i in 0..NUM_WORKERS {
        let child = Command::new("cmd.exe")
            .args(["/c", "ping", "127.0.0.1", "-n", "30"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap_or_else(|e| panic!("Failed to spawn child worker {}: {}", i, e));

        assert!(child.id() > 0, "Child worker {} must have valid PID", i);
        workers.push(child);
    }

    // Assign each worker to the Job Object and verify membership
    for (i, worker) in workers.iter().enumerate() {
        let assign_res = job.assign(worker);
        assert!(
            assign_res.is_ok(),
            "Assigning worker {} (PID {}) to Job Object failed: {:?}",
            i,
            worker.id(),
            assign_res.err()
        );

        let is_member = job
            .contains_process(worker)
            .unwrap_or_else(|e| panic!("Failed to verify worker {} membership: {}", i, e));
        assert!(
            is_member,
            "Worker {} (PID {}) must be confirmed inside Job Object",
            i,
            worker.id()
        );
    }

    // Verify active process accounting indicates at least 3 active processes
    let active_count = job
        .query_active_process_count()
        .expect("Failed to query active process count");
    assert!(
        active_count >= NUM_WORKERS as u32,
        "Expected at least {} active processes in Job Object, found {}",
        NUM_WORKERS,
        active_count
    );

    // -------------------------------------------------------------------------
    // Phase 3: Drop Job Object & Confirm Clean Termination
    // -------------------------------------------------------------------------
    drop(job);

    // Poll for up to 3 seconds for all 3 child workers to be terminated by the kernel
    let poll_start = Instant::now();
    let poll_timeout = Duration::from_secs(3);
    let mut all_terminated = false;

    while poll_start.elapsed() < poll_timeout {
        all_terminated = workers.iter_mut().all(|w| {
            matches!(w.try_wait(), Ok(Some(_)))
        });
        if all_terminated {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    // Safeguard: Ensure no orphaned processes survive even if assertion fails
    if !all_terminated {
        for worker in workers.iter_mut() {
            let _ = worker.kill();
            let _ = worker.wait();
        }
        panic!("Timed out waiting for child workers to terminate after JobObject drop");
    }

    // Assert every worker reported exit status
    for (i, worker) in workers.iter_mut().enumerate() {
        let status = worker.try_wait().expect("Failed to query worker exit status");
        assert!(
            status.is_some(),
            "Child worker {} (PID {}) must be terminated after JobObject drop",
            i,
            worker.id()
        );
    }
}
```

---

## 5. Verification Method

### 5.1 Test Execution Command
Following `GEMINI.md` Rule 1 (subshell piping to temporary log file and inspecting via `view_file`):
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants > cargo_test_run.txt 2>&1"
```
Or for full workspace supervisor test execution:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test_run.txt 2>&1"
```
Inspect `cargo_test_run.txt`, verify exit code 0, and immediately delete via:
```cmd
cmd.exe /c "del cargo_test_run.txt"
```

### 5.2 Verification Checklist
- [ ] `QueryInformationJobObject` succeeds and confirms:
  - `limit_flags & 0x00002000 != 0` (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)
  - `limit_flags & 0x00000008 == 0` (`JOB_OBJECT_LIMIT_ACTIVE_PROCESS`)
  - `active_limit == 0`
- [ ] 3 concurrent workers spawn with unique PIDs.
- [ ] All 3 assignments to `JobObject` succeed without `ERROR_ACTIVE_PROCESS_LIMIT`.
- [ ] `contains_process` confirms all 3 workers in job object.
- [ ] `query_active_process_count` reports `>= 3`.
- [ ] After `drop(job)`, all 3 workers transition to terminated within 3 seconds.
- [ ] Zero orphaned `ping.exe` or `cmd.exe` processes remain active.

### 5.3 Invalidation Conditions
- Failure of `AssignProcessToJobObject` with Win32 code 4 (`ERROR_ACTIVE_PROCESS_LIMIT`).
- `limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS != 0`.
- Any worker process remaining running (`try_wait() == Ok(None)`) 3 seconds after `drop(job)`.
- Compilation errors regarding missing Win32 symbols or type mismatches.
