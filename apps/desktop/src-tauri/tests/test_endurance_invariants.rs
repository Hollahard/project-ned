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
use std::os::windows::io::AsRawHandle;
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
        assert_ne!(
            snapshot, INVALID_HANDLE_VALUE,
            "CreateToolhelp32Snapshot returned INVALID_HANDLE_VALUE"
        );
        assert!(!snapshot.is_null(), "CreateToolhelp32Snapshot returned null handle");

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

/// Subsequence search helper for byte stream scanning.
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

// =========================================================================
// Suite A: Windows Job Object Concurrency & Termination Invariants
// =========================================================================

#[test]
fn test_job_object_limits_permit_concurrency_and_kill_on_close() {
    let _lock = ENDURANCE_SERIALIZATION_LOCK.lock().unwrap();

    let job = JobObject::new().expect("Job Object creation must succeed on Windows");

    // Verify raw_handle and AsRawHandle implementations
    assert_eq!(job.raw_handle(), job.handle());
    assert_eq!(job.as_raw_handle() as HANDLE, job.handle());

    // 1. Verify Job Object Limit Configuration via QueryInformationJobObject
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

    let limit_flags = limit_info.BasicLimitInformation.LimitFlags;
    let active_limit = limit_info.BasicLimitInformation.ActiveProcessLimit;

    // Assert JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0
    assert_ne!(
        limit_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        0,
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE must be enabled in LimitFlags (found: 0x{:08X})",
        limit_flags
    );

    // Assert JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0
    assert_eq!(
        limit_flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
        0,
        "JOB_OBJECT_LIMIT_ACTIVE_PROCESS must NOT be set in LimitFlags (found: 0x{:08X})",
        limit_flags
    );

    // Assert ActiveProcessLimit == 0
    assert_eq!(
        active_limit, 0,
        "ActiveProcessLimit must be 0 (unlimited active processes permitted)"
    );

    // 2. Spawn 3 concurrent child worker processes (cmd.exe /c ping 127.0.0.1 -n 30)
    const NUM_WORKERS: usize = 3;
    let mut workers: Vec<Child> = (0..NUM_WORKERS)
        .map(|idx| {
            Command::new("cmd.exe")
                .args(["/c", "ping", "127.0.0.1", "-n", "30"])
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap_or_else(|e| panic!("Failed to spawn child worker {}: {}", idx, e))
        })
        .collect();

    // Assign all 3 to Job Object, verify membership
    for (idx, worker) in workers.iter().enumerate() {
        let assign_res = job.assign(worker);
        assert!(
            assign_res.is_ok(),
            "Assigning worker {} (PID {}) to Job Object failed: {:?}",
            idx,
            worker.id(),
            assign_res.err()
        );

        let in_job = job
            .contains_process(worker)
            .unwrap_or_else(|e| panic!("Failed to verify worker {} membership: {}", idx, e));
        assert!(
            in_job,
            "Worker {} (PID {}) must be confirmed inside Job Object",
            idx,
            worker.id()
        );
    }

    // Verify query_active_process_count >= 3
    let active_count = job
        .query_active_process_count()
        .expect("Failed to query active process count");
    assert!(
        active_count >= NUM_WORKERS as u32,
        "Expected at least {} active processes in Job Object, found {}",
        NUM_WORKERS,
        active_count
    );

    // 3. Drop JobObject, poll up to 3 seconds for clean termination, assert 0 orphans
    drop(job);

    let poll_start = Instant::now();
    let poll_timeout = Duration::from_secs(3);
    let mut all_terminated = false;

    while poll_start.elapsed() < poll_timeout {
        all_terminated = workers.iter_mut().all(|w| matches!(w.try_wait(), Ok(Some(_))));
        if all_terminated {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    if !all_terminated {
        // Fallback safeguard to clean up any surviving processes
        for worker in workers.iter_mut() {
            let _ = worker.kill();
            let _ = worker.wait();
        }
        panic!("Timed out waiting for child workers to terminate after JobObject drop");
    }

    // Assert all workers reported exit status (0 orphans)
    for (idx, worker) in workers.iter_mut().enumerate() {
        let status = worker.try_wait().expect("Failed to query worker exit status");
        assert!(
            status.is_some(),
            "Child worker {} (PID {}) must be terminated after JobObject drop",
            idx,
            worker.id()
        );
    }
}

// =========================================================================
// Suite B: Repeated Session, Telemetry, and Preflight Leak Invariants
// =========================================================================

#[tokio::test]
async fn test_supervisor_repeated_operations_no_handle_or_thread_leak() {
    let _lock = ENDURANCE_SERIALIZATION_LOCK.lock().unwrap();

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
