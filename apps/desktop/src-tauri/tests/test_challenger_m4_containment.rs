//! Empirical Challenger 2 Adversarial Stress Test Suite for Milestone 4 Process Guardian.
//!
//! Invariant & Stress Tests:
//! 1. Win32 Job Object Limit Flags & Concurrency Stress (ActiveProcessLimit == 0, KILL_ON_JOB_CLOSE = 0x2000, 6 concurrent workers).
//! 2. Rapid Job Object Creation, Churn & Reap (10 cycles).
//! 3. Environment Sanitization Leak Demonstration:
//!    Proves empirically that `Command::new().envs(&sanitized)` without `.env_clear()` leaks parent secrets to child processes!
//! 4. Loopback Proxy Bypass under Poisoned Proxy Environment (.no_proxy() resilience).
//! 5. Zero Orphan Process Post-Execution Verification.

use friday_supervisor::processes::{build_sanitized_env, JobObject};
use friday_supervisor::proxy::CoreProxy;

use std::collections::HashMap;
use std::ffi::c_void;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use windows_sys::Win32::System::JobObjects::{
    JobObjectExtendedLimitInformation, QueryInformationJobObject,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
};

static TEST_SERIALIZATION_LOCK: Mutex<()> = Mutex::new(());

#[test]
fn test_job_object_strict_limit_flags_and_concurrency() {
    let _lock = TEST_SERIALIZATION_LOCK.lock().unwrap();

    let job = JobObject::new().expect("Failed to create Job Object");

    // 1. Empirically query Win32 Job Object Limit Information
    unsafe {
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        let ret = QueryInformationJobObject(
            job.raw_handle(),
            JobObjectExtendedLimitInformation,
            &mut info as *mut _ as *mut c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            std::ptr::null_mut(),
        );
        assert_ne!(ret, 0, "QueryInformationJobObject failed");

        let flags = info.BasicLimitInformation.LimitFlags;
        let active_limit = info.BasicLimitInformation.ActiveProcessLimit;

        // Verify KILL_ON_JOB_CLOSE (0x2000) is enabled
        assert!(
            (flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0,
            "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) must be enabled, got 0x{:08X}",
            flags
        );

        // Verify ACTIVE_PROCESS (0x0008) is strictly omitted
        assert_eq!(
            flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
            0,
            "JOB_OBJECT_LIMIT_ACTIVE_PROCESS (0x0008) must NOT be enabled, got 0x{:08X}",
            flags
        );

        // Verify ActiveProcessLimit == 0 (unrestricted child worker concurrency)
        assert_eq!(
            active_limit, 0,
            "ActiveProcessLimit must be 0 for unrestricted concurrency, got {}",
            active_limit
        );

        // Verify Breakaway flags are NOT enabled (containment invariant)
        assert_eq!(
            flags & JOB_OBJECT_LIMIT_BREAKAWAY_OK,
            0,
            "JOB_OBJECT_LIMIT_BREAKAWAY_OK must NOT be set"
        );
        assert_eq!(
            flags & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
            0,
            "JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK must NOT be set"
        );
    }

    // 2. Concurrency stress: spawn 6 concurrent child workers
    const NUM_WORKERS: usize = 6;
    let mut workers: Vec<Child> = Vec::new();

    for i in 0..NUM_WORKERS {
        let child = Command::new("cmd.exe")
            .args(["/c", "ping", "127.0.0.1", "-n", "30"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap_or_else(|e| panic!("Failed to spawn worker {}: {}", i, e));

        let assign_res = job.assign(&child);
        assert!(
            assign_res.is_ok(),
            "Failed to assign worker {} (PID {}) to Job Object",
            i,
            child.id()
        );

        let in_job = job.contains_process(&child).unwrap();
        assert!(
            in_job,
            "Worker {} (PID {}) must be confirmed inside Job Object",
            i,
            child.id()
        );

        workers.push(child);
    }

    // Verify active processes count >= 6
    let active_count = job
        .query_active_process_count()
        .expect("Failed to query active process count");
    assert!(
        active_count >= NUM_WORKERS as u32,
        "Expected at least {} active processes, found {}",
        NUM_WORKERS,
        active_count
    );

    // 3. Drop JobObject -> verify all 6 workers are killed by the OS kernel
    drop(job);

    let deadline = Instant::now() + Duration::from_secs(3);
    let mut all_dead = false;

    while Instant::now() < deadline {
        if workers.iter_mut().all(|w| matches!(w.try_wait(), Ok(Some(_)))) {
            all_dead = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    if !all_dead {
        for w in workers.iter_mut() {
            let _ = w.kill();
            let _ = w.wait();
        }
        panic!("One or more child workers survived Job Object drop!");
    }

    // Confirm all workers report terminated status
    for (i, w) in workers.iter_mut().enumerate() {
        let status = w.try_wait().unwrap();
        assert!(
            status.is_some(),
            "Worker {} (PID {}) must be terminated",
            i,
            w.id()
        );
    }
}

#[test]
fn test_job_object_rapid_churn_stress() {
    let _lock = TEST_SERIALIZATION_LOCK.lock().unwrap();

    for cycle in 0..10 {
        let job = JobObject::new().expect("Failed to create Job Object in churn cycle");

        let mut child1 = Command::new("cmd.exe")
            .args(["/c", "ping", "127.0.0.1", "-n", "10"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("Spawn failed in churn");

        let mut child2 = Command::new("cmd.exe")
            .args(["/c", "ping", "127.0.0.1", "-n", "10"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("Spawn failed in churn");

        job.assign(&child1).expect("Assign child1 failed in churn");
        job.assign(&child2).expect("Assign child2 failed in churn");

        assert!(job.contains_process(&child1).unwrap());
        assert!(job.contains_process(&child2).unwrap());

        // Drop job object
        drop(job);

        std::thread::sleep(Duration::from_millis(200));

        assert!(
            child1.try_wait().unwrap().is_some(),
            "Child 1 not reaped in cycle {}",
            cycle
        );
        assert!(
            child2.try_wait().unwrap().is_some(),
            "Child 2 not reaped in cycle {}",
            cycle
        );
    }
}

#[test]
fn test_environment_sanitization_adversarial_isolation_proof() {
    let _lock = TEST_SERIALIZATION_LOCK.lock().unwrap();

    // 1. Poison host environment with mock secrets
    unsafe {
        std::env::set_var("ADVERSARIAL_API_KEY", "sk-live-0987654321");
        std::env::set_var("DATABASE_PASSWORD", "SuperSecretPass!");
        std::env::set_var("PRIV_SSH_KEY", "-----BEGIN RSA PRIVATE KEY-----");
        std::env::set_var("GIT_TOKEN", "ghp_1234567890abcdef");
    }

    let mut extra = HashMap::new();
    extra.insert("FRIDAY_BEARER_TOKEN".to_string(), "safe-ephemeral-token".to_string());

    let sanitized = build_sanitized_env(&extra, None);

    // 2. Assert secrets are purged from the sanitized HashMap
    assert!(!sanitized.contains_key("ADVERSARIAL_API_KEY"));
    assert!(!sanitized.contains_key("DATABASE_PASSWORD"));
    assert!(!sanitized.contains_key("PRIV_SSH_KEY"));
    assert!(!sanitized.contains_key("GIT_TOKEN"));

    // 3. Assert whitelisted system keys and extra keys are present in HashMap
    assert!(sanitized.contains_key("PATH"));
    assert!(sanitized.contains_key("TEMP") || sanitized.contains_key("TMP"));
    assert!(sanitized.contains_key("SYSTEMROOT"));
    assert_eq!(sanitized.get("PYTHONUNBUFFERED").unwrap(), "1");
    assert_eq!(sanitized.get("FRIDAY_BEARER_TOKEN").unwrap(), "safe-ephemeral-token");

    // 4. Vulnerability Proof:
    // In Rust std::process::Command, calling .envs(&sanitized) WITHOUT .env_clear()
    // does NOT clear parent environment; it merges onto parent environment!
    // In processes.rs lines 315 and 354, Command::envs(&sanitized) is called without env_clear().
    let script = r#"
import os, sys
hostile_keys = ['ADVERSARIAL_API_KEY', 'DATABASE_PASSWORD', 'PRIV_SSH_KEY', 'GIT_TOKEN']
leaks = [k for k in hostile_keys if k in os.environ]
if leaks:
    print(f"LEAK_DETECTED:{','.join(leaks)}")
    sys.exit(10)
else:
    print("ISOLATED_OK")
    sys.exit(0)
"#;

    // Vulnerable invocation (as written in processes.rs lines 301-320 and 351-365)
    let vuln_output = Command::new("python.exe")
        .args(["-c", script])
        .envs(&sanitized)
        .output()
        .expect("Failed to execute python child process");

    let vuln_stdout = String::from_utf8_lossy(&vuln_output.stdout);
    assert!(
        vuln_stdout.contains("LEAK_DETECTED"),
        "Empirical proof: Command::envs without env_clear must reproduce the secret leak! Output: {}",
        vuln_stdout
    );

    // Secure invocation (with .env_clear())
    let mut secure_cmd = Command::new("python.exe");
    secure_cmd.env_clear();
    secure_cmd.envs(&sanitized);
    let secure_output = secure_cmd
        .args(["-c", script])
        .output()
        .expect("Failed to execute secure python child process");

    let secure_stdout = String::from_utf8_lossy(&secure_output.stdout);
    assert!(
        secure_stdout.contains("ISOLATED_OK"),
        "With env_clear(), secrets are properly isolated! Output: {}",
        secure_stdout
    );
}

#[tokio::test]
async fn test_loopback_proxy_bypass_adversarial_poisoned_environment() {
    let _lock = TEST_SERIALIZATION_LOCK.lock().unwrap();

    // 1. Bind an ephemeral loopback TCP listener simulating Core
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("Failed to bind ephemeral loopback port");
    let port = listener.local_addr().unwrap().port();

    let running = Arc::new(AtomicBool::new(true));
    let running_clone = running.clone();

    // Body to return matching HealthStatus struct
    let json_body = "{\"status\":\"healthy\",\"version\":\"1.0.0\",\"uptime_seconds\":12.3,\"inference_backend\":\"tabby\",\"gpu_available\":true}";
    let resp_payload = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        json_body.len(),
        json_body
    );

    // Spawn loopback server task
    let server_handle = tokio::spawn(async move {
        while running_clone.load(Ordering::SeqCst) {
            tokio::select! {
                accept_res = listener.accept() => {
                    if let Ok((mut socket, _)) = accept_res {
                        let payload = resp_payload.clone();
                        tokio::spawn(async move {
                            let mut buf = [0u8; 1024];
                            if let Ok(n) = socket.read(&mut buf).await {
                                if n > 0 {
                                    let req = String::from_utf8_lossy(&buf[..n]);
                                    if req.starts_with("GET /health") {
                                        let _ = socket.write_all(payload.as_bytes()).await;
                                        let _ = socket.flush().await;
                                    }
                                }
                            }
                        });
                    }
                }
                _ = tokio::time::sleep(Duration::from_millis(50)) => {}
            }
        }
    });

    // 2. Poison host proxy environment with a dead proxy port
    let dead_proxy = "http://127.0.0.1:1";
    unsafe {
        std::env::set_var("HTTP_PROXY", dead_proxy);
        std::env::set_var("http_proxy", dead_proxy);
        std::env::set_var("ALL_PROXY", dead_proxy);
        std::env::set_var("all_proxy", dead_proxy);
    }

    // 3. Test that a naive reqwest client WITHOUT .no_proxy() fails due to routing through dead proxy
    let naive_client = reqwest::Client::builder().build().unwrap();
    let naive_res = naive_client
        .get(format!("http://127.0.0.1:{}/health", port))
        .timeout(Duration::from_millis(500))
        .send()
        .await;

    // The naive client must fail to connect due to dead proxy
    let naive_failed = naive_res.is_err();
    assert!(
        naive_failed,
        "Naive client without .no_proxy() unexpectedly succeeded through dead proxy"
    );

    // 4. Test CoreProxy (which uses Client::builder().no_proxy())
    let proxy = CoreProxy::new(port, "test_token".to_string(), 5000, "admin_key".to_string());

    let health_res = proxy.check_health().await;
    assert!(
        health_res.is_ok(),
        "CoreProxy check_health failed despite .no_proxy()! Error: {:?}",
        health_res.err()
    );

    let health = health_res.unwrap();
    assert_eq!(health.status, "healthy");

    // Clean up proxy env vars
    unsafe {
        std::env::remove_var("HTTP_PROXY");
        std::env::remove_var("http_proxy");
        std::env::remove_var("ALL_PROXY");
        std::env::remove_var("all_proxy");
    }

    running.store(false, Ordering::SeqCst);
    let _ = server_handle.await;
}

#[test]
fn test_zero_orphans_post_execution_contract() {
    let _lock = TEST_SERIALIZATION_LOCK.lock().unwrap();

    // Sleep briefly to ensure previous tests reaped their processes
    std::thread::sleep(Duration::from_millis(200));

    // Assert no orphaned ping.exe processes remain in system
    let output = Command::new("cmd.exe")
        .args(["/c", "tasklist | findstr /i ping.exe"])
        .output()
        .expect("Failed to execute tasklist");

    // findstr returncode 1 means no match was found (0 orphans)
    assert_eq!(
        output.status.code(),
        Some(1),
        "Orphaned ping.exe process detected in system tasklist!"
    );
}
