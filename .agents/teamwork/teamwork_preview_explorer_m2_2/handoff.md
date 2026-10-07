# Milestone 2 Explorer 2 Handoff: Rust Tauri Supervisor Handle & Thread Leak Endurance Contract

## Summary
This investigation establishes the technical design, empirical validation, and complete drop-in test implementation for `test_supervisor_repeated_operations_no_handle_or_thread_leak` in the Rust Tauri desktop supervisor (`apps/desktop/src-tauri`).
Under 50 continuous iterations of session creation, GPU telemetry polling, VRAM preflight calculation, and environment preflight diagnostics, the supervisor incurs **delta = 0 handles** and **delta = 0 threads**, fully satisfying the tripwire bounds (`handle_delta <= 5`, `thread_delta <= 1`) with an execution runtime of **0.09 seconds**.

---

## 1. Observation

### 1.1 Existing Target Endpoints in `CoreProxy` (`apps/desktop/src-tauri/src/proxy.rs`)
1. **Session Creation** (`proxy.rs:302–329`):
   ```rust
   pub async fn create_session(
       &self,
       title: Option<&str>,
       working_directory: Option<&str>,
   ) -> Result<SessionSummary, ProxyError>
   ```
   - Target URL: `POST {core_base_url}/api/v1/sessions`
   - Headers: `Authorization: Bearer {core_bearer_token}`, `Content-Type: application/json`
   - JSON Request Payload: `{"title": "...", "working_directory": ...}`
   - Deserialization Model: `SessionSummary` (`id: String`, `title: String`, `created_at: String`, `updated_at: String`, `message_count: u64`)

2. **GPU Telemetry Polling** (`proxy.rs:427–444`):
   ```rust
   pub async fn get_gpu_telemetry(&self) -> Result<GpuTelemetry, ProxyError>
   ```
   - Target URL: `GET {core_base_url}/api/v1/telemetry/gpu`
   - Headers: `Authorization: Bearer {core_bearer_token}`
   - Deserialization Model: `GpuTelemetry` (`available: bool`, `device_name: String`, `driver_version: String`, `nvml_version: String`, `vram_total_mb: f64`, `vram_used_mb: f64`, `vram_free_mb: f64`, `vram_usage_percent: f64`, `temperature_c: i64`, `power_watts: f64`, `power_limit_watts: f64`, `utilization_gpu_percent: i64`, `utilization_mem_percent: i64`)

3. **VRAM Fit Preflight Check** (`proxy.rs:447–468`):
   ```rust
   pub async fn check_vram_preflight(
       &self,
       request: &PreflightRequest,
   ) -> Result<PreflightResult, ProxyError>
   ```
   - Target URL: `POST {core_base_url}/api/v1/models/preflight`
   - Headers: `Authorization: Bearer {core_bearer_token}`, `Content-Type: application/json`
   - Serialization Model: `PreflightRequest` (`model_name: String`, `context_length: u32`, `kv_cache_dtype: String`, `available_vram_mb: Option<f64>`, `bpw: Option<f64>`)
   - Deserialization Model: `PreflightResult` (`fits: bool`, `model_name: String`, `context_length: u32`, `kv_cache_dtype: String`, `estimated_weights_mb: f64`, `estimated_kv_cache_mb: f64`, `estimated_total_mb: f64`, `available_vram_mb: f64`, `headroom_mb: f64`, `recommended_context: Option<u32>`, `recommended_kv_cache: Option<String>`, `message: String`)

### 1.2 System Preflight Diagnostics (`apps/desktop/src-tauri/src/first_launch.rs`)
- `run_preflight_diagnostics()` (`first_launch.rs:114–270`):
  - In-process native execution: creates and configures a temporary Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, checks architecture, inspects workspace path accessibility, and calls `windows_sys::Win32::Foundation::CloseHandle(job)`.
  - Verifies zero-leak behavior across repeated invocation.

### 1.3 Windows OS Metrics Capabilities (`apps/desktop/src-tauri/Cargo.toml`)
- Dependencies declared:
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
- Win32 API functions verified:
  - `GetProcessHandleCount` and `GetCurrentProcess`: part of `Win32_System_Threading`.
  - `CreateToolhelp32Snapshot`, `Thread32First`, `Thread32Next`, `TH32CS_SNAPTHREAD`, `THREADENTRY32`: part of `Win32_System_Diagnostics_ToolHelp`.
  - `CloseHandle`, `INVALID_HANDLE_VALUE`: part of `Win32_Foundation`.

### 1.4 Empirical Execution and Timing
A self-contained empirical verification was compiled and executed under `cargo test`:
- Command executed:
  ```pwsh
  cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test temp_m2_full -- --nocapture"
  ```
- Output observed:
  ```text
  Supervisor endurance leak check: handles: 97 -> 97 (delta: 0), threads: 6 -> 6 (delta: 0)
  test test_supervisor_repeated_operations_no_handle_or_thread_leak ... ok
  test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.09s
  ```
- **Observations recorded**:
  1. 10 warmup cycles followed by 50 full continuous cycles (total 60 cycles = 180 HTTP roundtrips + 60 Job Object creations/closures).
  2. Handle delta: Exactly 0 (`97 -> 97`), well within the required `delta <= 5`.
  3. Thread delta: Exactly 0 (`6 -> 6`), well within the required `delta <= 1`.
  4. Total execution time: **0.09 seconds** for the entire test run.

---

## 2. Logic Chain

### 2.1 In-Memory Loopback Mock HTTP Server Design
1. **Binding to `127.0.0.1:0`**:
   `tokio::net::TcpListener::bind("127.0.0.1:0")` binds to loopback on an ephemeral OS-assigned port. This guarantees zero port collisions with already-running services (e.g. Core on 8000/8200 or Tabby on 5000).
2. **Zero Additional Crate Dependencies**:
   By implementing a stream parser on `TcpListener` directly, no third-party HTTP mock servers (`mockito`, `wiremock`, `httpmock`) are needed. `Cargo.toml` remains unchanged.
3. **HTTP/1.1 Keep-Alive Connection Pooling**:
   `reqwest::Client` utilizes connection pooling. By parsing `Content-Length` and keeping the loopback socket open with `Connection: keep-alive`, subsequent HTTP requests across the 50 iterations reuse the established TCP connection. This accurately reflects production behavior, avoids Windows Winsock socket table exhaustion (`TIME_WAIT`), and eliminates handle churn.
4. **Deterministic Lifecycle Teardown**:
   The mock server accepts requests inside a `tokio::select!` block listening on a `tokio::sync::oneshot::channel<()>`. Upon test completion, `shutdown_tx.send(())` triggers immediate shutdown and awaits the server join handle, preventing dangling background tasks.

### 2.2 Win32 Handle Sampling Logic
1. `GetCurrentProcess()` returns the pseudo-handle `-1` for the current process (requires no handle allocation or cleanup).
2. `GetProcessHandleCount(GetCurrentProcess(), &mut count)` retrieves the exact count of handles currently opened in the process table.
3. Because `first_launch::run_preflight_diagnostics()` allocates a Job Object handle via `CreateJobObjectW`, any failure to call `CloseHandle` would increase the handle count by exactly +1 per call (+50 over 50 iterations).
4. Because `reqwest::Client` reuses its connection, socket handles remain constant.
5. Setting the post-warmup tripwire to `delta <= 5` ensures that any systematic handle leak (+50) will fail the test immediately, while absorbing normal OS Winsock / I/O completion port caching.

### 2.3 Win32 Toolhelp Thread Count Sampling Logic
1. `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)` creates a system-wide thread snapshot handle.
2. `Thread32First` and `Thread32Next` traverse all active OS threads in the system.
3. Filtering on `entry.th32OwnerProcessID == GetCurrentProcessId()` tallies the active OS threads belonging specifically to the test runner process.
4. Calling `CloseHandle(snapshot)` immediately after enumeration guarantees that the snapshot handle itself does not leak.
5. In Tokio's multi-threaded runtime, worker threads are fixed at runtime initialization. Asynchronous tasks scheduled via `tokio::spawn` run on existing threads without spawning new OS threads.
6. A monotonic ratchet in thread count would indicate unmanaged thread spawning (such as naked `std::thread::spawn` or unbounded thread-pool growth). Setting the tripwire to `delta <= 1` strictly forbids thread ratcheting while allowing at most 1 transient OS helper thread.

### 2.4 Warmup Phase Rationale
1. The first 1–10 iterations trigger one-time initialization costs:
   - Tokio runtime worker thread initialization.
   - Winsock DLL and LSP provider loading (`ws2_32.dll`, `mswsock.dll`).
   - Reqwest connection pool, DNS resolver state, and socket allocation.
   - Windows Job Object subsystem kernel structures.
2. Discarding the warmup iterations establishes a stable baseline, matching the soak test specification in ADR-0002.

---

## 3. Caveats

1. **Standalone Execution vs Live Service**:
   The loopback mock server runs completely offline and in-memory. It does not require TabbyAPI or Python FastAPI to be running.
2. **Threadhelp Snapshot Privileges**:
   Under Windows 10/11, standard user processes have full rights to query threads owned by their own PID via `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)`. No administrator elevation is required.
3. **Execution Context**:
   The test must be executed using Tokio multi-threaded test macro `#[tokio::test]`. If Tokio were configured with `flavor = "current_thread"`, all tasks would run on 1 thread, which could mask cross-thread synchronization issues. `#[tokio::test]` defaults to multi-thread flavor when `rt-multi-thread` is active in `features = ["full"]`.
4. **Toolhelp Snapshot Handle Hygiene**:
   `get_current_thread_count()` itself creates a handle (`CreateToolhelp32Snapshot`). If `CloseHandle` were omitted inside `get_current_thread_count()`, the measurement tool would leak handles. The implementation strictly guarantees `CloseHandle(snapshot)` is called before returning.

---

## 4. Conclusion & Drop-in Test Code

The proposed implementation fulfills Milestone 2 Requirement R3 for supervisor handle and thread endurance invariants.

### Drop-in Test Implementation
This code can be placed directly in `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` (or added to `apps/desktop/src-tauri/tests/test_supervisor_soak.rs`):

```rust
use friday_supervisor::first_launch::run_preflight_diagnostics;
use friday_supervisor::proxy::{CoreProxy, PreflightRequest};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::Threading::{
    GetCurrentProcess, GetCurrentProcessId, GetProcessHandleCount,
};

/// Queries the current number of open handles for the supervisor process.
fn get_current_handle_count() -> u32 {
    unsafe {
        let h_proc = GetCurrentProcess();
        let mut count: u32 = 0;
        let ok = GetProcessHandleCount(h_proc, &mut count);
        assert_ne!(ok, 0, "Failed to get process handle count via GetProcessHandleCount");
        count
    }
}

/// Enumerates the exact number of active OS threads belonging to the supervisor process.
fn get_current_thread_count() -> u32 {
    unsafe {
        let current_pid = GetCurrentProcessId();
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snapshot == INVALID_HANDLE_VALUE || snapshot.is_null() {
            panic!("Failed to create toolhelp snapshot for thread enumeration");
        }

        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;

        let mut count: u32 = 0;
        if Thread32First(snapshot, &mut entry) != 0 {
            loop {
                if entry.th32OwnerProcessID == current_pid {
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

/// Case-insensitive search for Content-Length in HTTP headers.
fn parse_content_length(headers: &str) -> usize {
    for line in headers.lines() {
        let trimmed = line.trim();
        if let Some(colon_pos) = trimmed.find(':') {
            let (name, val) = trimmed.split_at(colon_pos);
            if name.trim().eq_ignore_ascii_case("content-length") {
                if let Ok(len) = val[1..].trim().parse::<usize>() {
                    return len;
                }
            }
        }
    }
    0
}

/// Subsequence search helper.
fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

/// Handles incoming loopback connections, supporting HTTP/1.1 keep-alive request streams.
async fn handle_mock_client(mut socket: tokio::net::TcpStream) {
    let mut buf = vec![0u8; 8192];
    let mut cursor = 0;

    loop {
        // Read until full HTTP header delimiter (\r\n\r\n) is discovered
        let header_end = loop {
            if let Some(pos) = find_subsequence(&buf[..cursor], b"\r\n\r\n") {
                break pos;
            }
            if cursor == buf.len() {
                buf.resize(buf.len() * 2, 0);
            }
            match socket.read(&mut buf[cursor..]).await {
                Ok(0) => return, // Connection closed by client
                Ok(n) => cursor += n,
                Err(_) => return,
            }
        };

        let headers_str = String::from_utf8_lossy(&buf[..header_end]);
        let first_line = headers_str.lines().next().unwrap_or("").to_string();
        let content_length = parse_content_length(&headers_str);
        let total_request_len = header_end + 4 + content_length;

        // Ensure entire request body is consumed
        while cursor < total_request_len {
            if cursor == buf.len() {
                buf.resize(buf.len() * 2, 0);
            }
            match socket.read(&mut buf[cursor..]).await {
                Ok(0) => return,
                Ok(n) => cursor += n,
                Err(_) => return,
            }
        }

        // Route by method and endpoint
        let (status, body) = if first_line.starts_with("POST /api/v1/sessions") {
            (
                "200 OK",
                r#"{"id":"mock-session-001","title":"Endurance Session","created_at":"2026-10-07T16:00:00Z","updated_at":"2026-10-07T16:00:00Z","message_count":0}"#,
            )
        } else if first_line.starts_with("GET /api/v1/telemetry/gpu") {
            (
                "200 OK",
                r#"{"available":true,"device_name":"NVIDIA GeForce RTX 5090","driver_version":"572.16","nvml_version":"12.572.16","vram_total_mb":32607.0,"vram_used_mb":4096.0,"vram_free_mb":28511.0,"vram_usage_percent":12.5,"temperature_c":45,"power_watts":85.0,"power_limit_watts":600.0,"utilization_gpu_percent":5,"utilization_mem_percent":10}"#,
            )
        } else if first_line.starts_with("POST /api/v1/models/preflight") {
            (
                "200 OK",
                r#"{"fits":true,"model_name":"Mistral-Small-3.1-24B-Instruct-2503-exl3","context_length":32768,"kv_cache_dtype":"q6","estimated_weights_mb":14500.0,"estimated_kv_cache_mb":4200.0,"estimated_total_mb":18700.0,"available_vram_mb":32607.0,"headroom_mb":13907.0,"recommended_context":32768,"recommended_kv_cache":"q6","message":"Model fits in VRAM"}"#,
            )
        } else {
            ("404 Not Found", r#"{"error":"not found"}"#)
        };

        let response = format!(
            "HTTP/1.1 {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: keep-alive\r\n\r\n{}",
            status,
            body.len(),
            body
        );

        if socket.write_all(response.as_bytes()).await.is_err() {
            return;
        }

        // Shift pipelined or subsequent bytes forward
        buf.copy_within(total_request_len..cursor, 0);
        cursor -= total_request_len;
    }
}

#[tokio::test]
async fn test_supervisor_repeated_operations_no_handle_or_thread_leak() {
    // 1. Bind in-memory loopback mock HTTP server on ephemeral port
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("Failed to bind loopback TCP listener");
    let port = listener
        .local_addr()
        .expect("Failed to query local socket address")
        .port();

    let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    let server_task = tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = &mut shutdown_rx => {
                    break;
                }
                res = listener.accept() => {
                    match res {
                        Ok((socket, _)) => {
                            tokio::spawn(handle_mock_client(socket));
                        }
                        Err(_) => break,
                    }
                }
            }
        }
    });

    // 2. Instantiate CoreProxy pointing to loopback mock server
    let proxy = CoreProxy::new(port, "test_token_5090".to_string(), 5000, "admin_5090".to_string());

    let preflight_req = PreflightRequest {
        model_name: "Mistral-Small-3.1-24B-Instruct-2503-exl3".to_string(),
        context_length: 32768,
        kv_cache_dtype: "q6".to_string(),
        available_vram_mb: Some(32607.0),
        bpw: Some(6.0),
    };

    // 3. Warmup cycles (10 iterations) to saturate tokio thread pools and socket buffers
    for _ in 0..10 {
        let session = proxy
            .create_session(Some("Warmup Session"), None)
            .await
            .expect("Warmup create_session failed");
        assert!(!session.id.is_empty());

        let telem = proxy
            .get_gpu_telemetry()
            .await
            .expect("Warmup get_gpu_telemetry failed");
        assert!(telem.available);

        let pf = proxy
            .check_vram_preflight(&preflight_req)
            .await
            .expect("Warmup check_vram_preflight failed");
        assert!(pf.fits);

        let diag = run_preflight_diagnostics();
        assert!(diag.job_object_supported);
    }

    // 4. Sample baseline handle and thread counts
    let initial_handles = get_current_handle_count();
    let initial_threads = get_current_thread_count();

    // 5. Execute 50 continuous iterations of all 4 operations
    for i in 0..50 {
        let session = proxy
            .create_session(Some(&format!("Endurance Session {}", i)), None)
            .await
            .expect("Endurance create_session failed");
        assert!(!session.id.is_empty());

        let telem = proxy
            .get_gpu_telemetry()
            .await
            .expect("Endurance get_gpu_telemetry failed");
        assert!(telem.available);
        assert_eq!(telem.temperature_c, 45);

        let pf = proxy
            .check_vram_preflight(&preflight_req)
            .await
            .expect("Endurance check_vram_preflight failed");
        assert!(pf.fits);

        let diag = run_preflight_diagnostics();
        assert_eq!(diag.overall_status, "pass");
        assert!(diag.job_object_supported);
    }

    // 6. Sample final metrics and calculate deltas
    let final_handles = get_current_handle_count();
    let final_threads = get_current_thread_count();

    let handle_delta = (final_handles as i64) - (initial_handles as i64);
    let thread_delta = (final_threads as i64) - (initial_threads as i64);

    // 7. Clean up loopback mock server
    let _ = shutdown_tx.send(());
    let _ = server_task.await;

    // 8. Assert leak tripwires
    assert!(
        handle_delta <= 5,
        "Supervisor handle leak detected: initial handles = {}, final handles = {}, delta = {} (threshold: <= 5)",
        initial_handles,
        final_handles,
        handle_delta
    );

    assert!(
        thread_delta <= 1,
        "Supervisor thread leak detected: initial threads = {}, final threads = {}, delta = {} (threshold: <= 1)",
        initial_threads,
        final_threads,
        thread_delta
    );
}
```

---

## 5. Verification Method

### 5.1 Verification Commands
Run the integration test via `cmd.exe /c` piping to temporary log:
```cmd
cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test test_endurance_invariants -- --nocapture > cargo_test_run.txt 2>&1"
```
Inspect via `view_file` on `cargo_test_run.txt`, verify exit code 0, and immediately delete the log via:
```cmd
cmd.exe /c "del cargo_test_run.txt"
```

### 5.2 Pass Criteria
1. The test executes all 50 continuous iterations and finishes in under 2.0 seconds (empirically ~0.09s).
2. `handle_delta` must satisfy `handle_delta <= 5` (empirically observed: 0).
3. `thread_delta` must satisfy `thread_delta <= 1` (empirically observed: 0).
4. No panic, error, or unhandled socket disconnection occurs during execution.

### 5.3 Invalidation Conditions
- Any occurrence of `handle_delta > 5` indicates a socket or Job Object handle leak.
- Any occurrence of `thread_delta > 1` indicates thread-pool ratcheting or unmanaged OS thread creation.
- Test hang or timeout indicates deadlocked socket read or missing `Content-Length` framing in the loopback server.
