# Milestone 2 Explorer 3 Handoff: Rust Tauri Supervisor Crate Structure, Cargo.toml Features, and Test Integration Contract

**Agent Identity**: Explorer 3 (Milestone 2: Rust Tauri Supervisor Endurance Contract)  
**Parent**: orchestrator_1 (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Workspace**: `G:\Project_Ned`  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m2_3`  
**Target Subsystem**: `apps/desktop/src-tauri` (`friday-supervisor` crate)  

---

## Executive Summary
This investigation provides a comprehensive analysis of the crate structure, dependency declarations, `windows-sys` feature sets, Cargo test execution runner, and integration test layout for Milestone 2 (Phase 16 Deliverable R3).
Key findings:
1. **Cargo.toml Dependency Completeness**: The existing `apps/desktop/src-tauri/Cargo.toml` already declares all six required `windows-sys = { version = "0.59", features = [...] }` feature flags (`Win32_System_JobObjects`, `Win32_Foundation`, `Win32_Security`, `Win32_System_Threading`, `Win32_UI_WindowsAndMessaging`, `Win32_System_Diagnostics_ToolHelp`) and `tokio = { version = "1", features = ["full"] }`. **No dependency additions or feature modifications are required in `Cargo.toml`.**
2. **Integration Test Auto-Discovery**: Adding `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` is automatically discovered by Cargo as an independent test target (`test_endurance_invariants`).
3. **Test Serialization Invariant**: Because Win32 handle and thread sampling measures the entire process table (`GetProcessHandleCount`, `CreateToolhelp32Snapshot`), concurrent execution of child-spawning tests (Suite A) and handle-sampling tests (Suite B) within the same binary must be serialized via an in-file `std::sync::Mutex` test lock to eliminate transient metric cross-contamination.
4. **Verification Protocol**: Formulated exact, reproducible build, check, and test verification pipelines adhering strictly to `GEMINI.md` subshell routing (`cmd.exe /c`), output log capture, immediate log cleanup, and hung process cleanup.

---

## 1. Observation

### 1.1 `Cargo.toml` Dependency & Feature Declaration
File: `G:\Project_Ned\apps\desktop\src-tauri\Cargo.toml` (lines 10–34):
```toml
[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tokio = { version = "1", features = ["full"] }
reqwest = { version = "0.12", features = ["json", "stream"] }
futures-util = "0.3"
windows-sys = { version = "0.59", features = [
    "Win32_System_JobObjects",
    "Win32_Foundation",
    "Win32_Security",
    "Win32_System_Threading",
    "Win32_UI_WindowsAndMessaging",
    "Win32_System_Diagnostics_ToolHelp"
] }
sha2 = "0.10"
hmac = "0.12"
uuid = { version = "1", features = ["v4"] }
chrono = { version = "0.4", features = ["serde"] }
thiserror = "2.0"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
hex = "0.4"
url = "2.5"

[lib]
name = "friday_supervisor"
path = "src/lib.rs"

[[bin]]
name = "friday"
path = "src/main.rs"
```

### 1.2 Win32 API Symbol Mapping to `windows-sys` Features
Direct symbol mapping for the functions and structures required by Milestone 2 integration tests:

| Required Win32 Symbol | Kind | Required Feature Flag | Status in `Cargo.toml` |
|---|---|---|---|
| `CreateJobObjectW` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `SetInformationJobObject` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `QueryInformationJobObject` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `AssignProcessToJobObject` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `TerminateJobObject` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `IsProcessInJob` | Function | `Win32_System_JobObjects` | Enabled (line 18) |
| `JobObjectExtendedLimitInformation` | Const (enum) | `Win32_System_JobObjects` | Enabled (line 18) |
| `JobObjectBasicAccountingInformation` | Const (enum) | `Win32_System_JobObjects` | Enabled (line 18) |
| `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` | Struct | `Win32_System_JobObjects` | Enabled (line 18) |
| `JOBOBJECT_BASIC_ACCOUNTING_INFORMATION`| Struct | `Win32_System_JobObjects` | Enabled (line 18) |
| `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` | Constant bit | `Win32_System_JobObjects` | Enabled (line 18) |
| `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` | Constant bit | `Win32_System_JobObjects` | Enabled (line 18) |
| `GetCurrentProcess` | Function | `Win32_System_Threading` | Enabled (line 21) |
| `GetCurrentProcessId` | Function | `Win32_System_Threading` | Enabled (line 21) |
| `GetProcessHandleCount` | Function | `Win32_System_Threading` | Enabled (line 21) |
| `CreateToolhelp32Snapshot` | Function | `Win32_System_Diagnostics_ToolHelp` | Enabled (line 23) |
| `Thread32First` | Function | `Win32_System_Diagnostics_ToolHelp` | Enabled (line 23) |
| `Thread32Next` | Function | `Win32_System_Diagnostics_ToolHelp` | Enabled (line 23) |
| `THREADENTRY32` | Struct | `Win32_System_Diagnostics_ToolHelp` | Enabled (line 23) |
| `TH32CS_SNAPTHREAD` | Constant bit | `Win32_System_Diagnostics_ToolHelp` | Enabled (line 23) |
| `CloseHandle` | Function | `Win32_Foundation` | Enabled (line 19) |
| `HANDLE`, `BOOL`, `INVALID_HANDLE_VALUE` | Types/Constants | `Win32_Foundation` | Enabled (line 19) |
| `GetLastError` | Function | `Win32_Foundation` | Enabled (line 19) |

Empirical `cargo tree` validation (`cargo tree --manifest-path apps/desktop/src-tauri/Cargo.toml -i windows-sys:0.59.0 --edges features`) confirmed all six features are activated directly by `friday-supervisor v0.1.0`.

### 1.3 Cargo Test Discovery and Current Test Inventory
Executing `cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test_output.txt 2>&1"` yields:
- **Unit test runner**: `src/lib.rs` (5 tests passing in `first_launch::tests`)
- **Binary runner**: `src/main.rs` (0 tests)
- **Integration test runner 1**: `tests/test_job_object.rs` (2 tests passing: creation, single-child kill on drop)
- **Integration test runner 2**: `tests/test_sanitized_env.rs` (1 test passing: parent secret stripping)
- **Integration test runner 3**: `tests/test_supervisor_soak.rs` (3 tests passing: preflight handle leak, JobObject membership, sidecar exit reaping)
- **Integration test runner 4**: `tests/test_tokens.rs` (2 tests passing: args hash, token consumption)
- **Doc-tests**: `friday_supervisor` (0 tests)
- **Total passing**: 13 passed, 0 failed, 0 ignored in 0.72s.

### 1.4 Module Export Status in `src/lib.rs`
All modules required by Milestone 2 integration tests are public exports in `apps/desktop/src-tauri/src/lib.rs`:
```rust
pub mod approvals;
pub mod commands;
pub mod first_launch;
pub mod processes;
pub mod proxy;
pub mod runtime;
```
Specifically:
- `JobObject`: exported from `friday_supervisor::processes::JobObject`
- `CoreProxy`, `PreflightRequest`, `PreflightResult`: exported from `friday_supervisor::proxy`
- `run_preflight_diagnostics`: exported from `friday_supervisor::first_launch`

### 1.5 Handle Accessor in `src/processes.rs`
In `apps/desktop/src-tauri/src/processes.rs`:
- Line 134 provides:
  ```rust
  pub fn handle(&self) -> HANDLE {
      self.handle
  }
  ```
- Does not yet declare `pub fn raw_handle(&self) -> HANDLE` or implement `std::os::windows::io::AsRawHandle`.

---

## 2. Logic Chain

### 2.1 Crate Feature Completeness
1. Observation 1.1 and 1.2 demonstrate that every single Win32 API function, struct, and bitmask required by Milestone 2 is provided by `windows-sys = { version = "0.59" }` under the six feature flags already declared.
2. `tokio = { version = "1", features = ["full"] }` already provides `#[tokio::test]`, `tokio::net::TcpListener`, `tokio::io::AsyncReadExt`, `tokio::io::AsyncWriteExt`, `tokio::sync::oneshot`, and the full multi-threaded async executor.
3. Because all dependencies are declared under `[dependencies]` rather than being restricted to `[lib]`, they are unconditionally accessible to all integration test files in `tests/*.rs`.
4. Therefore, no modifications to `apps/desktop/src-tauri/Cargo.toml` are necessary or desirable.

### 2.2 Integration Test Structure & Auto-Discovery
1. By Cargo convention, Cargo automatically compiles each individual `.rs` file located in `tests/` into an independent integration test executable linked to the `friday_supervisor` library crate.
2. Placing `test_endurance_invariants.rs` in `apps/desktop/src-tauri/tests/` registers the target `test_endurance_invariants` without requiring manual entries in `Cargo.toml`.
3. Running:
   `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants`
   will selectively compile and run only this integration test target.
4. Running:
   `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`
   will execute all 13 existing tests plus the new endurance integration tests, ensuring zero regression across the entire supervisor test suite.

### 2.3 Concurrency Race Condition Analysis & Test Serialization Lock
1. Cargo runs test functions inside an integration test binary concurrently across multiple threads by default (`--test-threads = num_cpus`).
2. Milestone 2 combines two distinct test suites in `test_endurance_invariants.rs`:
   - **Suite A**: `test_job_object_limits_permit_concurrency_and_kill_on_close` (spawns 3 `ping.exe` child processes, allocates process handles and stdin/stdout pipes, and drops them).
   - **Suite B**: `test_supervisor_repeated_operations_no_handle_or_thread_leak` (samples process-wide handle count via `GetProcessHandleCount` and process-wide thread count via `CreateToolhelp32Snapshot`).
3. If Suite A and Suite B execute concurrently:
   - The OS handle count sampled in Suite B will observe the transient child process handles, job object handles, and pipe handles allocated and torn down by Suite A.
   - This could artificially inflate `handle_diff` beyond the `<= 5` threshold.
4. **Resolution**:
   In `test_endurance_invariants.rs`, define a static serialization lock:
   ```rust
   static ENDURANCE_SERIALIZATION_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
   ```
   Each test function acquires this lock at the start of execution (`let _lock = ENDURANCE_SERIALIZATION_LOCK.lock().unwrap();`). This guarantees that even when Cargo runs the test binary without `--test-threads=1`, the tests execute serially and cannot cross-contaminate process metrics.

### 2.4 Tokio Runtime Thread Pool Stabilization
1. In Tokio's multi-threaded runtime (`#[tokio::test]`), worker threads are spawned upon runtime entry.
2. Executing 5–10 warmup cycles before sampling the baseline handle and thread counts ensures that Tokio worker threads, Winsock DLL provider initialization (`ws2_32.dll`), and reqwest HTTP connection pools have stabilized into steady-state.
3. Once in steady-state, subsequent operations reuse existing threads and pooled connections, resulting in `handle_delta = 0` and `thread_delta = 0` (well within `<= 5` handles and `<= 1` thread).

---

## 3. Caveats

1. **Parallel Execution Across Separate Test Binaries**:
   Cargo may run separate test binaries (e.g. `test_job_object.rs` and `test_endurance_invariants.rs`) in parallel processes. Because `GetProcessHandleCount` and `CreateToolhelp32Snapshot` measure only the *calling process's* handles and threads, concurrent execution of *other test binaries* does NOT affect Suite B's measurements. Only intra-binary multi-threading within `test_endurance_invariants.rs` could cause interference, which is completely mitigated by the in-file `Mutex`.
2. **Asynchronous Windows Kernel Process Reaping**:
   When a Job Object is dropped, the Windows kernel terminates assigned child processes asynchronously. While termination is guaranteed, `child.try_wait()` may return `Ok(None)` for a few milliseconds while the kernel cleans up process table entries. The test implementation must poll `child.try_wait()` with a timeout loop (e.g. up to 3 seconds with 50ms intervals) rather than asserting an instantaneous exit on line + 1.
3. **HTTP Mock Server Socket Hygiene**:
   The in-memory mock server must support HTTP/1.1 persistent connections (`keep-alive`) and cleanly terminate its listener task upon test completion via a `tokio::sync::oneshot` channel to avoid lingering socket handles.
4. **Win32 ToolHelp Snapshot Handle Hygiene**:
   `CreateToolhelp32Snapshot` allocates a kernel handle. If `CloseHandle(snapshot)` were omitted in the helper function, the sampling tool itself would leak handles. The helper must strictly close the snapshot handle before returning.

---

## 4. Conclusion & Proposed Implementation Strategy

### 4.1 `Cargo.toml` Action
**Zero changes required.** `apps/desktop/src-tauri/Cargo.toml` is fully equipped for Milestone 2.

### 4.2 `apps/desktop/src-tauri/src/processes.rs` Action
To ensure complete interface contract alignment with `PROJECT.md` §Interface Contracts and idiomatic standard library ergonomics, add:
1. `raw_handle(&self) -> HANDLE` (alias to `handle(&self)`):
   ```rust
   /// Return raw Win32 HANDLE for querying job object information and limits.
   pub fn raw_handle(&self) -> HANDLE {
       self.handle
   }
   ```
2. `AsRawHandle` implementation:
   ```rust
   impl std::os::windows::io::AsRawHandle for JobObject {
       fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
           self.handle as _
       }
   }
   ```

### 4.3 `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` Drop-In Design
Create `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` containing both suites guarded by the serialization lock:

```rust
//! Supervisor Endurance Invariant Tests (Phase 16 Milestone 2 / Requirement R3).
//!
//! Invariants strictly enforced:
//! 1. Windows Job Object LimitFlags enforce JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
//! 2. LimitFlags omit JOB_OBJECT_LIMIT_ACTIVE_PROCESS (ActiveProcessLimit == 0), permitting worker concurrency.
//! 3. Dropping JobObject cleanly reaps 3 concurrent worker processes without orphans.
//! 4. 50 continuous iterations of session creation, telemetry polling, VRAM preflight,
//!    and environment diagnostics leak zero Windows OS handles (delta <= 5) and zero threads (delta <= 1).

use friday_supervisor::first_launch::run_preflight_diagnostics;
use friday_supervisor::processes::JobObject;
use friday_supervisor::proxy::{CoreProxy, PreflightRequest};

use std::ffi::c_void;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, THREADENTRY32, TH32CS_SNAPTHREAD,
};
use windows_sys::Win32::System::JobObjects::{
    JobObjectExtendedLimitInformation, QueryInformationJobObject,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    GetCurrentProcess, GetCurrentProcessId, GetProcessHandleCount,
};

/// Test serialization lock ensuring process-wide metric tests do not experience
/// race conditions with concurrent child-spawning tests.
static ENDURANCE_SERIALIZATION_LOCK: Mutex<()> = Mutex::new(());

fn get_current_handle_count() -> u32 {
    unsafe {
        let mut count: u32 = 0;
        let ok = GetProcessHandleCount(GetCurrentProcess(), &mut count);
        assert_ne!(ok, 0, "GetProcessHandleCount failed");
        count
    }
}

fn get_current_thread_count() -> u32 {
    unsafe {
        let pid = GetCurrentProcessId();
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        assert_ne!(
            snapshot, INVALID_HANDLE_VALUE,
            "CreateToolhelp32Snapshot failed"
        );

        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;

        let mut count: u32 = 0;
        if Thread32First(snapshot, &mut entry) != 0 {
            loop {
                if entry.th32OwnerProcessID == pid {
                    count += 1;
                }
                if Thread32Next(snapshot, &mut entry) == 0 {
                    break;
                }
            }
        }
        CloseHandle(snapshot);
        count
    }
}

// =========================================================================
// Suite A: Windows Job Object Concurrency & Termination Invariants
// =========================================================================

#[test]
fn test_job_object_limits_permit_concurrency_and_kill_on_close() {
    let _lock = ENDURANCE_SERIALIZATION_LOCK.lock().unwrap();

    let job = JobObject::new().expect("Job Object creation must succeed on Windows");

    // 1. Verify Job Object Limit Configuration via QueryInformationJobObject
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

    // 2. Spawn 3 concurrent child workers & assign to Job Object
    let mut workers: Vec<Child> = (0..3)
        .map(|idx| {
            Command::new("cmd.exe")
                .args(["/c", "ping", "127.0.0.1", "-n", "30"])
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap_or_else(|e| panic!("Failed to spawn worker process {}: {}", idx, e))
        })
        .collect();

    for (idx, worker) in workers.iter().enumerate() {
        let assign_res = job.assign(worker);
        assert!(
            assign_res.is_ok(),
            "Assigning worker {} to Job Object must succeed: {:?}",
            idx,
            assign_res.err()
        );
        let in_job = job
            .contains_process(worker)
            .expect("Querying job membership must succeed");
        assert!(
            in_job,
            "Worker {} must be verified as member of Job Object",
            idx
        );
    }

    let active_count = job
        .query_active_process_count()
        .expect("Querying active process count must succeed");
    assert!(
        active_count >= 3,
        "Job Object active process count must be at least 3 (found: {})",
        active_count
    );

    // 3. Drop Job Object and assert all 3 workers terminate cleanly
    drop(job);

    let start = Instant::now();
    let timeout = Duration::from_secs(3);
    for (idx, worker) in workers.iter_mut().enumerate() {
        let mut terminated = false;
        while start.elapsed() < timeout {
            match worker.try_wait() {
                Ok(Some(_status)) => {
                    terminated = true;
                    break;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(50)),
                Err(e) => panic!("Error polling worker {} exit: {}", idx, e),
            }
        }
        assert!(
            terminated,
            "Worker {} failed to terminate within {:?} of JobObject drop",
            idx, timeout
        );
    }
}

// =========================================================================
// Suite B: Repeated Session, Telemetry, and Preflight Leak Invariants
// =========================================================================

#[tokio::test]
async fn test_supervisor_repeated_operations_no_handle_or_thread_leak() {
    let _lock = ENDURANCE_SERIALIZATION_LOCK.lock().unwrap();

    // 1. In-memory loopback mock HTTP server
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("Failed to bind loopback test server");
    let port = listener.local_addr().unwrap().port();

    let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    let server_task = tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = &mut shutdown_rx => break,
                res = listener.accept() => {
                    if let Ok((mut socket, _)) = res {
                        tokio::spawn(async move {
                            let mut buf = [0u8; 4096];
                            loop {
                                let n = match socket.read(&mut buf).await {
                                    Ok(0) | Err(_) => break,
                                    Ok(n) => n,
                                };
                                let req = String::from_utf8_lossy(&buf[..n]);

                                let (body, content_type) = if req.contains("/api/v1/sessions") {
                                    (
                                        r#"{"id":"sess-123","title":"Test Session","created_at":"2026-10-07T00:00:00Z","updated_at":"2026-10-07T00:00:00Z","message_count":0}"#,
                                        "application/json",
                                    )
                                } else if req.contains("/api/v1/telemetry/gpu") {
                                    (
                                        r#"{"available":true,"device_name":"NVIDIA GeForce RTX 5090","driver_version":"570.86","nvml_version":"12.570.86","vram_total_mb":32768.0,"vram_used_mb":4096.0,"vram_free_mb":28672.0,"vram_usage_percent":12.5,"temperature_c":45,"power_watts":65.0,"power_limit_watts":600.0,"utilization_gpu_percent":5,"utilization_mem_percent":8}"#,
                                        "application/json",
                                    )
                                } else if req.contains("/api/v1/models/preflight") {
                                    (
                                        r#"{"fits":true,"model_name":"test-model","context_length":32768,"kv_cache_dtype":"q6","estimated_weights_mb":18000.0,"estimated_kv_cache_mb":4000.0,"estimated_total_mb":22000.0,"available_vram_mb":32000.0,"headroom_mb":10000.0,"recommended_context":null,"recommended_kv_cache":null,"message":"Model fits comfortably"}"#,
                                        "application/json",
                                    )
                                } else {
                                    (r#"{"status":"ok"}"#, "application/json")
                                };

                                let response = format!(
                                    "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: keep-alive\r\n\r\n{}",
                                    content_type,
                                    body.len(),
                                    body
                                );
                                if socket.write_all(response.as_bytes()).await.is_err() {
                                    break;
                                }
                            }
                        });
                    }
                }
            }
        }
    });

    let proxy = CoreProxy::new(port, "test-token".to_string(), port, "test-admin".to_string());
    let preflight_req = PreflightRequest {
        model_name: "test-model".to_string(),
        context_length: 32768,
        kv_cache_dtype: "q6".to_string(),
        available_vram_mb: Some(32000.0),
        bpw: Some(4.0),
    };

    // 2. Warmup phase (stabilizes Tokio threads, connection pool, Winsock state)
    for _ in 0..10 {
        let _ = proxy.create_session(Some("Warmup"), None).await;
        let _ = proxy.get_gpu_telemetry().await;
        let _ = proxy.check_vram_preflight(&preflight_req).await;
        let _ = run_preflight_diagnostics();
    }

    // 3. Record baseline metrics
    let baseline_handles = get_current_handle_count();
    let baseline_threads = get_current_thread_count();

    // 4. Execute 50 continuous iterations
    for _ in 0..50 {
        let session = proxy
            .create_session(Some("Endurance Turn"), None)
            .await
            .expect("Session creation failed");
        assert_eq!(session.id, "sess-123");

        let telemetry = proxy
            .get_gpu_telemetry()
            .await
            .expect("Telemetry fetch failed");
        assert!(telemetry.available);

        let preflight = proxy
            .check_vram_preflight(&preflight_req)
            .await
            .expect("Preflight check failed");
        assert!(preflight.fits);

        let diag = run_preflight_diagnostics();
        assert!(diag.job_object_supported);
    }

    // 5. Record final metrics & evaluate tripwires
    let final_handles = get_current_handle_count();
    let final_threads = get_current_thread_count();

    let handle_diff = (final_handles as i64) - (baseline_handles as i64);
    let thread_diff = (final_threads as i64) - (baseline_threads as i64);

    println!(
        "Endurance leak check: handles: {} -> {} (delta: {}), threads: {} -> {} (delta: {})",
        baseline_handles, final_handles, handle_diff, baseline_threads, final_threads, thread_diff
    );

    // Enforce tripwires
    assert!(
        handle_diff <= 5,
        "OS handle leak detected: baseline {}, final {}, delta {} > 5",
        baseline_handles, final_handles, handle_diff
    );

    assert!(
        thread_diff <= 1,
        "Thread pool ratchet detected: baseline {}, final {}, delta {} > 1",
        baseline_threads, final_threads, thread_diff
    );

    // Clean teardown
    let _ = shutdown_tx.send(());
    let _ = server_task.await;
}
```

---

## 5. Verification Method

All verification commands are formulated strictly per `GEMINI.md`:
- Routing through `cmd.exe /c`
- Output redirection to temporary log files (`> log.txt 2>&1`)
- Inspection via `view_file`
- Immediate deletion of temporary log files
- `BypassSandbox: true` on drive `G:`

### 5.1 Verification Commands

#### Step 1: Compilation & Type Check
Verify that the integration tests and supervisor crate compile with zero errors:
```cmd
cmd.exe /c "cargo check --tests --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_check.txt 2>&1"
```
*Verification*: Inspect `cargo_check.txt` with `view_file`. Verify exit code 0 and zero compilation errors.  
*Cleanup*: `cmd.exe /c "del cargo_check.txt"`

#### Step 2: Targeted Endurance Invariants Test Execution
Execute specifically the new endurance contract test target:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants -- --nocapture > cargo_endurance_run.txt 2>&1"
```
*Verification*: Inspect `cargo_endurance_run.txt` with `view_file`.  
*Pass Criteria*:
1. Both tests pass (`test result: ok. 2 passed; 0 failed; 0 ignored`).
2. `test_job_object_limits_permit_concurrency_and_kill_on_close ... ok` confirms 3/3 workers assigned and all 3 terminated.
3. `test_supervisor_repeated_operations_no_handle_or_thread_leak ... ok` reports `handle_diff <= 5` and `thread_diff <= 1`.
4. Total execution completes in under 2 seconds.  
*Cleanup*: `cmd.exe /c "del cargo_endurance_run.txt"`

#### Step 3: Full Supervisor Test Suite Regression Check (Acceptance Criterion 2)
Verify all existing tests continue to pass cleanly alongside the new endurance suite:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_full_run.txt 2>&1"
```
*Verification*: Inspect `cargo_full_run.txt` with `view_file`.  
*Pass Criteria*:
1. Total passed tests = 15 (5 unit tests + 10 integration tests across `test_job_object`, `test_sanitized_env`, `test_supervisor_soak`, `test_tokens`, and `test_endurance_invariants`).
2. Zero failed, zero warnings, exit code 0.  
*Cleanup*: `cmd.exe /c "del cargo_full_run.txt"`

#### Step 4: Emergency Hung Process Teardown (if tests are interrupted)
Per `GEMINI.md` Testing & Mocking Invariants:
```cmd
cmd.exe /c "taskkill /F /IM ping.exe /T 2>nul & taskkill /F /IM cmd.exe /FI \"WINDOWTITLE eq test*\" 2>nul"
```

### 5.2 Invalidation Conditions
The endurance test suite is invalidated if any of the following occur:
- `QueryInformationJobObject` reports `JOB_OBJECT_LIMIT_ACTIVE_PROCESS != 0` or `ActiveProcessLimit > 0`.
- Assigning any of the 3 child workers fails with `ERROR_ACTIVE_PROCESS_LIMIT` (`0x00000004` / code 4).
- Any `ping.exe` or `cmd.exe` process remains running 3 seconds after dropping the `JobObject`.
- `handle_diff > 5` over 50 iterations (indicates systematic socket or JobObject handle leak).
- `thread_diff > 1` over 50 iterations (indicates unbounded thread-pool growth).
