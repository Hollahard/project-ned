# Phase 16 Rust Tauri Supervisor Endurance & Soak Investigation

## 1. Observation

### 1.1 Windows Job Object Creation, Configuration, and Invariants
In `apps/desktop/src-tauri/src/processes.rs`:
- Lines 53–79 (`JobObject::new()`):
  ```rust
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
- **Job Object Limit Invariant Verification**:
  - `info.BasicLimitInformation.LimitFlags` is set strictly to `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (value `0x00002000`).
  - `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (value `0x00000008`) is **NOT** included in `LimitFlags`.
  - Because `info` is initialized with `unsafe { std::mem::zeroed() }`, `info.BasicLimitInformation.ActiveProcessLimit` is initialized to `0`.
  - Windows kernel documentation stipulates: active process limits are enforced *only* when the `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` flag is present in `LimitFlags`. Because this bit is zero and `ActiveProcessLimit` is zero, the Windows Job Object imposes no active process quota.
- Child process binding in lines 83–95 (`JobObject::assign(&self, child: &Child)`):
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
- RAII Drop guarantee in lines 108–118 (`impl Drop for JobObject`):
  ```rust
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
- Explicit termination in lines 98–105 (`JobObject::terminate(&self, exit_code: u32)`):
  Calls `windows_sys::Win32::System::JobObjects::TerminateJobObject(self.handle, exit_code)`.

### 1.2 Supervisor Window Close & Lifecycle Handling
In `apps/desktop/src-tauri/src/lib.rs` (lines 59–68):
```rust
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                info!("Exit requested. Stopping supervisor and terminating child processes...");
                let rt = runtime.clone();
                tauri::async_runtime::block_on(async move {
                    let mut guard = rt.write().await;
                    guard.stop().await;
                });
            }
        });
```
In `apps/desktop/src-tauri/src/runtime.rs` (lines 169–191, 202–208):
```rust
    pub async fn stop(&mut self) {
        {
            let mut st = self.status.write().await;
            *st = LifecycleStatus::ShuttingDown;
        }

        info!("Shutting down Project Friday Supervisor and all child processes...");

        if let Some(mgr) = &self.process_manager {
            mgr.kill_all();
        }

        self.core_pid = None;
        self.tabby_pid = None;
        self.process_manager = None;
        self.proxy = None;

        {
            let mut st = self.status.write().await;
            *st = LifecycleStatus::Stopped;
        }
        info!("Supervisor shutdown complete. Zero child processes remaining.");
    }
...
impl Drop for SupervisorRuntime {
    fn drop(&mut self) {
        if let Some(mgr) = &self.process_manager {
            mgr.kill_all();
        }
    }
}
```
In `apps/desktop/src-tauri/src/processes.rs` (lines 318–325):
```rust
    pub fn kill_all(&self) {
        self.job_object.terminate(0);
        let mut list = self.children.lock().unwrap();
        for child in list.iter_mut() {
            let _ = child.kill();
        }
        list.clear();
    }
```
When Tauri intercepts window close (`ExitRequested`), it synchronously executes `runtime.stop().await`, which invokes `mgr.kill_all()`. This sends `TerminateJobObject(0)` to the kernel, kills tracked children, clears the list, and drops the `JobObject` handle (`CloseHandle`). Even if the process crashes before `kill_all()` completes, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ensures the Windows kernel terminates all child processes when the supervisor process handle closes.

### 1.3 Implementation of Session Creation, Telemetry Polling, and Preflight Checks
1. **Session Creation**:
   - IPC Command (`apps/desktop/src-tauri/src/commands.rs`, lines 59–69):
     `commands::create_session(state: State<'_, AppState>, title: Option<String>)` acquires a read lock on `SupervisorRuntime`, obtains `proxy`, and calls `proxy.create_session(title.as_deref(), None)`.
   - Proxy Client (`apps/desktop/src-tauri/src/proxy.rs`, lines 302–329):
     `CoreProxy::create_session(&self, title: Option<&str>, working_directory: Option<&str>)` issues an HTTP POST to `{core_base_url}/api/v1/sessions` with `Authorization: Bearer {core_bearer_token}` and JSON payload `{ "title": ..., "working_directory": ... }`. Deserializes into `SessionSummary`.
2. **Telemetry Polling**:
   - IPC Command (`apps/desktop/src-tauri/src/commands.rs`, lines 117–121):
     `commands::get_gpu_telemetry(state: State<'_, AppState>)` delegates to `proxy.get_gpu_telemetry()`.
     Also `commands::get_runtime_status` (lines 24–32) calls `proxy.get_runtime_status()`.
   - Proxy Client (`apps/desktop/src-tauri/src/proxy.rs`, lines 427–444 & 199–237):
     `CoreProxy::get_gpu_telemetry(&self)` executes GET `{core_base_url}/api/v1/telemetry/gpu` returning `GpuTelemetry`.
     `CoreProxy::get_runtime_status(&self)` executes GET `{core_base_url}/api/v1/runtime/status` returning `RuntimeStatus` (combining Core health, Tabby status, GPU telemetry, and Gaming Mode state).
3. **Preflight Checks**:
   - VRAM Model Fit Preflight:
     - IPC Command (`apps/desktop/src-tauri/src/commands.rs`, lines 124–135):
       `commands::check_vram_preflight(state: State<'_, AppState>, request: PreflightRequest)` delegates to `proxy.check_vram_preflight(&request)`.
     - Proxy Client (`apps/desktop/src-tauri/src/proxy.rs`, lines 447–468):
       Issues HTTP POST to `{core_base_url}/api/v1/models/preflight` returning `PreflightResult` (evaluating weights size, KV cache size, total VRAM, and headroom).
   - First-Launch System Preflight Diagnostics:
     - IPC Command (`apps/desktop/src-tauri/src/commands.rs`, lines 163–165):
       `commands::run_first_launch_diagnostics()` invokes `first_launch::run_preflight_diagnostics()`.
     - Implementation (`apps/desktop/src-tauri/src/first_launch.rs`, lines 114–270):
       Executed in-process by Rust supervisor without external API dependency:
       a. Tests Windows Job Object creation and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` configuration.
       b. Validates Windows x64 OS architecture.
       c. Evaluates RTX 5090 profile (32 GB GDDR7 VRAM).
       d. Evaluates NTFS storage workspace root safety.
       e. Validates isolated Python virtual environment existence.

### 1.4 Cargo Test Execution & Module Inventory
Command executed:
```pwsh
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test_run.txt 2>&1"
```
Observed result:
- Finished in `0.34s` (zero errors, 10 passed, 0 failed, 0 ignored).
- Test targets executed:
  1. Unit tests in `src/lib.rs` (5 passed in `first_launch::tests`):
     - `test_validate_safe_windows_path_rejects_alternate_data_streams`
     - `test_validate_safe_windows_path_rejects_reserved_device_names`
     - `test_validate_safe_windows_path_rejects_trailing_dots_and_spaces`
     - `test_check_first_launch_status_for_nonexistent_dir`
     - `test_run_preflight_diagnostics_passes_with_rtx5090_and_job_object`
  2. Binary tests in `src/main.rs` (0 tests).
  3. Integration test `tests/test_job_object.rs` (2 passed):
     - `test_job_object_creation_and_limits`
     - `test_job_object_assign_and_kill_on_drop`
  4. Integration test `tests/test_sanitized_env.rs` (1 passed):
     - `test_sanitized_environment_strips_parent_secrets`
  5. Integration test `tests/test_tokens.rs` (2 passed):
     - `test_canonical_args_hash_is_order_independent`
     - `test_approval_manager_mint_and_single_use_consume`
  6. Doc-tests `friday_supervisor` (0 tests).

- Dependencies involved (`Cargo.toml`):
  - `tauri = "2"`
  - `tokio = { version = "1", features = ["full"] }`
  - `reqwest = { version = "0.12", features = ["json", "stream"] }`
  - `windows-sys = { version = "0.59", features = ["Win32_System_JobObjects", "Win32_Foundation", "Win32_Security", "Win32_System_Threading", "Win32_UI_WindowsAndMessaging", "Win32_System_Diagnostics_ToolHelp"] }`
  - `serde`, `serde_json`, `futures-util`, `sha2`, `hmac`, `uuid`, `chrono`, `thiserror`, `tracing`, `tracing-subscriber`, `hex`, `url`.

---

## 2. Logic Chain

### 2.1 Job Object Invariants
1. Observation 1.1 confirms lines 60–61 set only `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
2. Win32 Job Object specification dictates that unless `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is explicitly set in `BasicLimitInformation.LimitFlags`, `ActiveProcessLimit` is ignored by the Windows kernel scheduler.
3. Therefore, multiple child processes (Core service, TabbyAPI sidecar, tool subprocesses, and background workers) can be assigned to the Job Object simultaneously without triggering `ERROR_ACTIVE_PROCESS_LIMIT`.
4. However, existing test `tests/test_job_object.rs` only tests spawning 1 child (`cmd.exe /c ping 127.0.0.1 -n 30`) and dropping the job object. It does NOT explicitly assert the absence of `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` via `QueryInformationJobObject`, nor does it stress-test assigning multiple concurrent child workers to verify concurrent execution.

### 2.2 Clean Window Close Invariant
1. Observation 1.2 demonstrates that upon Tauri `RunEvent::ExitRequested`, `SupervisorRuntime::stop()` is invoked.
2. `stop()` invokes `ProcessManager::kill_all()`, issuing `TerminateJobObject(handle, 0)` and `child.kill()` on all managed child processes.
3. When the `JobObject` handle is closed (`CloseHandle`), the Windows kernel enforces `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` as an unbreakable safety net against orphaned processes even in the event of an abnormal or abrupt supervisor termination.
4. An integration test must verify this behavior under concurrent multi-process load to ensure that worker concurrency does not degrade clean teardown.

### 2.3 Resource Leak Tripwires (Handles and Thread Pools)
1. Observation 1.3 shows that repeated calls to session creation, telemetry polling, and VRAM preflight traverse `CoreProxy` (wrapping `reqwest::Client`), while repeated environmental preflight traverses `first_launch::run_preflight_diagnostics()` (allocating and closing Win32 Job Objects and querying filesystem metadata).
2. `reqwest::Client` reuses an internal connection pool. If client instances are created per request or connection handles fail to be recycled, OS socket handles leak monotonically.
3. `first_launch::run_preflight_diagnostics()` calls `CreateJobObjectW` and `CloseHandle` on each invocation. If handle closure is omitted or leaks, OS handles climb monotonically.
4. In `windows-sys`, `GetProcessHandleCount` and `CreateToolhelp32Snapshot` (from features `Win32_System_Threading` and `Win32_System_Diagnostics_ToolHelp`, already declared in `Cargo.toml`) enable sampling process handle counts and thread pool counts in pure Rust without external tools.
5. An automated integration test running 50+ iterations of session creation, telemetry polling, and preflight checks can establish post-warmup baselines and assert that:
   - Handle count growth delta is `<= 5` (accounting for transient keep-alive socket buffers).
   - Thread pool count delta is `<= 1` (zero thread ratcheting).

---

## 3. Caveats
1. **Mocking vs. Live Service**: The integration tests within `apps/desktop/src-tauri` should execute in a standalone, headless manner without requiring an already-running Python FastAPI service on port 8000 or TabbyAPI on port 5000. Using an embedded in-memory `tokio::net::TcpListener` mock server inside the test executable ensures offline repeatability, sub-second execution, and eliminates external flakiness.
2. **`JobObject` Private Handle**: In `apps/desktop/src-tauri/src/processes.rs` (line 44), `JobObject.handle` is currently private. To query `QueryInformationJobObject` directly in integration tests without unsafe transmutation, `JobObject` should implement `std::os::windows::io::AsRawHandle` or expose `pub fn raw_handle(&self) -> HANDLE { self.handle }`. Concurrently, empirical multi-child assignment can be tested immediately without touching private fields.
3. **Warmup Discard**: As noted in ADR-0002 and the soak harness invariants, the initial 1–5 iterations of asynchronous runtimes (tokio worker threads, reqwest connection pool allocation) represent one-time startup costs and must be discarded as warmup before asserting monotonic stability.

---

## 4. Conclusion & Proposed Implementation Plan

The Rust Tauri supervisor currently enforces both `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and zero orphan child process guarantees, and correctly avoids setting `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`. However, test coverage lacks endurance assertions for handle leak prevention, thread pool stability, and multi-worker concurrency verification.

To fulfill Phase 16 Requirement R3, the implementer should:

1. **Add `AsRawHandle` implementation to `JobObject`** in `apps/desktop/src-tauri/src/processes.rs`:
   ```rust
   impl std::os::windows::io::AsRawHandle for JobObject {
       fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
           self.handle as _
       }
   }
   ```
   (or provide `pub fn raw_handle(&self) -> HANDLE { self.handle }`).

2. **Add integration test file `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`**:
   The test file will provide two comprehensive integration test cases:

   ### Suite A: Windows Job Object Concurrency & Termination Invariants
   - **`test_job_object_limits_permit_concurrency_and_kill_on_close`**:
     - Uses `QueryInformationJobObject` to assert `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0`, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`, and `ActiveProcessLimit == 0`.
     - Spawns 3 concurrent child worker processes (`cmd.exe /c ping 127.0.0.1 -n 30`).
     - Assigns all 3 processes to the same `JobObject`. Asserts all 3 assignments succeed (`res.is_ok()`), proving worker concurrency is unconstrained.
     - Drops the `JobObject` to simulate supervisor exit.
     - Sleeps 300ms and asserts all 3 child worker processes have terminated cleanly (`child.try_wait()` reports termination/exit).

   ### Suite B: Repeated Session Creation, Telemetry Polling, Preflight Checks Leak Invariants
   - **`test_supervisor_repeated_operations_no_handle_or_thread_leak`**:
     - Spawns a lightweight loopback mock HTTP server via `tokio::net::TcpListener::bind("127.0.0.1:0")`.
     - Mocks endpoints:
       - `POST /api/v1/sessions`
       - `GET /api/v1/telemetry/gpu`
       - `POST /api/v1/models/preflight`
     - Instantiates `CoreProxy::new(port, token, 5000, "admin")`.
     - Executes 5 warmup iterations of session creation, GPU telemetry polling, VRAM preflight, and `run_preflight_diagnostics()`.
     - Samples baseline OS handle count via `GetProcessHandleCount` and baseline thread count via `CreateToolhelp32Snapshot`.
     - Executes 50 continuous iterations of:
       1. `proxy.create_session(...)`
       2. `proxy.get_gpu_telemetry()`
       3. `proxy.check_vram_preflight(...)`
       4. `run_preflight_diagnostics()`
     - Samples final OS handle count and thread count.
     - Asserts handle count growth delta `<= 5` and thread count growth delta `<= 1`.

---

## 5. Verification Method

### 5.1 Test Execution Command
Run the test suite via `cmd.exe /c` piping to temporary log:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test_run.txt 2>&1"
```
Inspect via `view_file` on `cargo_test_run.txt`, verify all tests pass with code 0, and immediately delete the log via:
```cmd
cmd.exe /c "del cargo_test_run.txt"
```

### 5.2 Specific Assertions to Validate
1. `tests/test_endurance_invariants.rs` must be discovered and compiled as a separate test runner.
2. In `test_job_object_limits_permit_concurrency_and_kill_on_close`:
   - 3 out of 3 concurrent worker processes must be accepted into the Job Object.
   - Upon `drop(job)`, 0 worker processes may remain running.
3. In `test_supervisor_repeated_operations_no_handle_or_thread_leak`:
   - 50 iterations must complete within 2 seconds.
   - `handle_delta <= 5` and `thread_delta <= 1` must hold true.

### 5.3 Invalidation Conditions
- Any occurrence of `ERROR_ACTIVE_PROCESS_LIMIT` (`0x00000004` / code 4) when assigning child processes to the Job Object.
- Orphaned `ping.exe` or `cmd.exe` processes remaining active in Windows Task Manager after test execution.
- Handle count climbing linearly with the iteration count (e.g., +50 handles for 50 iterations).
