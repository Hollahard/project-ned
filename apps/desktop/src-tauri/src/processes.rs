//! Windows Job Object process supervisor and child execution manager.
//!
//! Invariants:
//! 1. All child processes (Core service, TabbyAPI sidecar, subagents) MUST belong
//!    to the supervisor's Windows Job Object.
//! 2. JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is mandatory. Breakaway is strictly denied.
//! 3. Child environment is an explicit whitelist. Never copy std::env::vars() wholesale.
//! 4. Direct process invocation via argument vector only. Never spawn via shell=True.

use std::collections::HashMap;
use std::ffi::c_void;
use std::os::windows::io::AsRawHandle;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::ptr::{null, null_mut};
use std::sync::{Arc, Mutex};
use tracing::{info, warn};

use windows_sys::Win32::Foundation::{CloseHandle, BOOL, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, IsProcessInJob,
    JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation,
    QueryInformationJobObject, SetInformationJobObject, TerminateJobObject,
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

#[derive(Debug, thiserror::Error)]
pub enum ProcessError {
    #[error("Failed to create Windows Job Object: error code {0}")]
    JobObjectCreate(u32),
    #[error("Failed to configure Job Object limits: error code {0}")]
    JobObjectConfigure(u32),
    #[error("Failed to assign process PID {pid} to Job Object: error code {code}")]
    AssignProcess { pid: u32, code: u32 },
    #[error("I/O error spawning process: {0}")]
    SpawnIo(#[from] std::io::Error),
    #[error("Binary not found at path: {0}")]
    BinaryNotFound(PathBuf),
    #[error("Failed to reap stale process on port {port}: {reason}")]
    ReapStale { port: u16, reason: String },
}

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

    /// Assign a child process to this Job Object.
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

    /// Assert whether a child process is contained within this Job Object using native Win32 IsProcessInJob.
    pub fn contains_process(&self, child: &Child) -> Result<bool, ProcessError> {
        let raw_handle = child.as_raw_handle() as HANDLE;
        let mut in_job: BOOL = 0;
        let ret = unsafe { IsProcessInJob(raw_handle, self.handle, &mut in_job) };
        if ret == 0 {
            let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            return Err(ProcessError::AssignProcess {
                pid: child.id(),
                code: err,
            });
        }
        Ok(in_job != 0)
    }

    /// Query the current count of active processes running inside this Job Object.
    pub fn query_active_process_count(&self) -> Result<u32, ProcessError> {
        let mut acct_info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
        let ret = unsafe {
            QueryInformationJobObject(
                self.handle,
                JobObjectBasicAccountingInformation,
                &mut acct_info as *mut _ as *mut c_void,
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                null_mut(),
            )
        };
        if ret == 0 {
            let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            return Err(ProcessError::JobObjectConfigure(err));
        }
        Ok(acct_info.ActiveProcesses)
    }

    /// Return raw HANDLE for testing assertions.
    pub fn handle(&self) -> HANDLE {
        self.handle
    }

    /// Return raw Win32 HANDLE for querying job object information and limits.
    pub fn raw_handle(&self) -> HANDLE {
        self.handle
    }

    /// Terminate all processes in this Job Object immediately.
    pub fn terminate(&self, exit_code: u32) {
        if !self.handle.is_null() && self.handle != INVALID_HANDLE_VALUE {
            unsafe {
                TerminateJobObject(self.handle, exit_code);
            }
            info!("Terminated all processes in Job Object with exit code {}", exit_code);
        }
    }
}

impl std::os::windows::io::AsRawHandle for JobObject {
    fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
        self.handle as _
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

/// Explicit whitelist environment builder for child processes.
/// Strips all unknown host credentials, API keys, and parent shell variables.
pub fn build_sanitized_env(
    extra: &HashMap<String, String>,
    venv_dir: Option<&Path>,
) -> HashMap<String, String> {
    const ALLOWED_VARS: &[&str] = &[
        "PATH",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    ];

    let mut env = HashMap::new();

    // Copy only whitelisted system variables
    for var in ALLOWED_VARS {
        if let Ok(val) = std::env::var(var) {
            env.insert(var.to_string(), val);
        }
    }

    // Configure virtual environment if provided
    if let Some(venv) = venv_dir {
        let venv_str = venv.to_string_lossy().to_string();
        env.insert("VIRTUAL_ENV".to_string(), venv_str.clone());
        let scripts_dir = venv.join("Scripts").to_string_lossy().to_string();
        if let Some(existing_path) = env.get("PATH").cloned() {
            env.insert("PATH".to_string(), format!("{};{}", scripts_dir, existing_path));
        } else {
            env.insert("PATH".to_string(), scripts_dir);
        }
    }

    // Always set Python unbuffered output
    env.insert("PYTHONUNBUFFERED".to_string(), "1".to_string());

    // Inject explicit extra variables (e.g. BEARER_TOKEN, ADMIN_KEY)
    for (k, v) in extra {
        env.insert(k.clone(), v.clone());
    }

    env
}

/// Reaps any stale process listening on the specified loopback port.
pub fn reap_stale_port(port: u16) -> Result<(), ProcessError> {
    // Run netstat -ano to find process bound to 127.0.0.1:<port> or 0.0.0.0:<port>
    let output = Command::new("netstat")
        .args(["-ano", "-p", "tcp"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output();

    let output = match output {
        Ok(out) => String::from_utf8_lossy(&out.stdout).to_string(),
        Err(e) => {
            warn!("Failed to query netstat for stale port {}: {}", port, e);
            return Ok(());
        }
    };

    let target_pattern = format!(":{}", port);
    for line in output.lines() {
        if line.contains("LISTENING") && line.contains(&target_pattern) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if let Some(pid_str) = parts.last() {
                if let Ok(pid) = pid_str.parse::<u32>() {
                    if pid > 4 {
                        info!("Reaping stale process PID {} listening on port {}", pid, port);
                        let _ = Command::new("taskkill")
                            .args(["/F", "/PID", &pid.to_string()])
                            .stdout(Stdio::null())
                            .stderr(Stdio::null())
                            .status();
                    }
                }
            }
        }
    }

    Ok(())
}

/// Supervisor process manager that spawns, monitors, and terminates Core and Tabby sidecars.
pub struct ProcessManager {
    job_object: Arc<JobObject>,
    children: Arc<Mutex<Vec<Child>>>,
}

impl ProcessManager {
    pub fn new() -> Result<Self, ProcessError> {
        let job = JobObject::new()?;
        Ok(Self {
            job_object: Arc::new(job),
            children: Arc::new(Mutex::new(Vec::new())),
        })
    }

    /// Spawns the Friday Core FastAPI service inside the Job Object.
    pub fn spawn_core(
        &self,
        core_root: &Path,
        python_exe: &Path,
        bearer_token: &str,
        port: u16,
    ) -> Result<u32, ProcessError> {
        if !python_exe.exists() {
            return Err(ProcessError::BinaryNotFound(python_exe.to_path_buf()));
        }

        reap_stale_port(port)?;

        let mut extra_env = HashMap::new();
        extra_env.insert("FRIDAY_BEARER_TOKEN".to_string(), bearer_token.to_string());
        extra_env.insert("FRIDAY_PORT".to_string(), port.to_string());
        extra_env.insert("PYTHONPATH".to_string(), core_root.join("src").to_string_lossy().to_string());

        let venv_dir = python_exe.parent().and_then(|p| p.parent());
        let sanitized = build_sanitized_env(&extra_env, venv_dir);

        let mut cmd = Command::new(python_exe);
        cmd.args([
            "-m",
            "uvicorn",
            "friday.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--log-level",
            "info",
        ])
        .current_dir(core_root)
        .env_clear()
        .envs(&sanitized)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

        let child = cmd.spawn()?;
        let pid = child.id();

        self.job_object.assign(&child)?;
        self.children.lock().unwrap().push(child);

        info!("Successfully spawned Core service PID {} on 127.0.0.1:{}", pid, port);
        Ok(pid)
    }

    /// Spawns TabbyAPI sidecar inside the Job Object.
    pub fn spawn_tabby(
        &self,
        tabby_root: &Path,
        python_exe: &Path,
        admin_key: &str,
        port: u16,
    ) -> Result<u32, ProcessError> {
        if !python_exe.exists() {
            return Err(ProcessError::BinaryNotFound(python_exe.to_path_buf()));
        }

        reap_stale_port(port)?;

        let mut extra_env = HashMap::new();
        extra_env.insert("TABBY_ADMIN_KEY".to_string(), admin_key.to_string());
        extra_env.insert("TABBY_PORT".to_string(), port.to_string());

        let venv_dir = python_exe.parent().and_then(|p| p.parent());
        let sanitized = build_sanitized_env(&extra_env, venv_dir);

        let mut cmd = Command::new(python_exe);
        cmd.args(["main.py"])
            .current_dir(tabby_root)
            .env_clear()
            .envs(&sanitized)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());

        let child = cmd.spawn()?;
        let pid = child.id();

        self.job_object.assign(&child)?;
        self.children.lock().unwrap().push(child);

        info!("Successfully spawned TabbyAPI sidecar PID {} on port {}", pid, port);
        Ok(pid)
    }

    /// Terminate all child processes immediately via Job Object termination.
    pub fn kill_all(&self) {
        self.job_object.terminate(0);
        let mut list = self.children.lock().unwrap();
        for child in list.iter_mut() {
            let _ = child.kill();
        }
        list.clear();
    }
}
