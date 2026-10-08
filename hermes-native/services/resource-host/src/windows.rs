use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{c_void, OsStr, OsString};
use std::io;
use std::mem::{size_of, zeroed};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::path::PathBuf;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, TryLockError};
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HANDLE, WAIT_OBJECT_0, WAIT_TIMEOUT};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, IsProcessInJob,
    JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation,
    QueryInformationJobObject, SetInformationJobObject, TerminateJobObject,
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    CreateProcessW, GetExitCodeProcess, OpenProcess, ResumeThread, TerminateProcess,
    WaitForSingleObject, CREATE_NO_WINDOW, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
    EXTENDED_STARTUPINFO_PRESENT, PROCESS_INFORMATION, PROCESS_QUERY_LIMITED_INFORMATION,
    STARTUPINFOW,
};

use crate::capture::{CaptureLimits, CapturedSetup, CapturedWorker};

/// Explicit inputs only: no inherited environment, shell expansion or PATH lookup.
/// Arguments/environment values intentionally have no Debug implementation.
pub struct WorkerSpec {
    pub executable: PathBuf,
    pub arguments: Vec<OsString>,
    pub working_directory: PathBuf,
    pub environment: BTreeMap<String, OsString>,
}

/// Use a separate group for each independently stoppable resource family.
pub struct WorkerGroup {
    job: OwnedHandle,
    retired: Mutex<bool>,
    retirement_requested: AtomicBool,
}

/// A stable native handle, never a PID reopened for termination.
pub struct Worker {
    process: OwnedHandle,
    pid: u32,
}

impl WorkerGroup {
    pub fn new() -> io::Result<Self> {
        // SAFETY: unnamed non-inheritable job; successful handle is owned once.
        let raw = unsafe { CreateJobObjectW(null(), null()) };
        if raw.is_null() {
            return Err(io::Error::last_os_error());
        }
        let job = unsafe { OwnedHandle::from_raw_handle(raw) };
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = unsafe {
            SetInformationJobObject(
                raw,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as *const c_void,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            job,
            retired: Mutex::new(false),
            retirement_requested: AtomicBool::new(false),
        })
    }

    pub fn spawn(&self, spec: &WorkerSpec) -> io::Result<Worker> {
        self.spawn_impl(spec, |process| self.assign(process))
    }

    /// Capture stdout/stderr while supplying closed (NUL) stdin. Only these
    /// three handles are inherited. Drainage begins before child execution.
    pub fn spawn_captured(
        &self,
        spec: &WorkerSpec,
        limits: CaptureLimits,
    ) -> io::Result<CapturedWorker> {
        let mut capture = CapturedSetup::new(limits)?;
        let worker = self.spawn_native(spec, |process| self.assign(process), Some(&mut capture))?;
        Ok(capture.finish(worker))
    }

    fn spawn_impl(
        &self,
        spec: &WorkerSpec,
        assign: impl FnOnce(HANDLE) -> io::Result<()>,
    ) -> io::Result<Worker> {
        self.spawn_native(spec, assign, None)
    }

    pub(crate) fn spawn_native(
        &self,
        spec: &WorkerSpec,
        assign: impl FnOnce(HANDLE) -> io::Result<()>,
        mut capture: Option<&mut CapturedSetup>,
    ) -> io::Result<Worker> {
        // Serialize create -> assign -> resume against retirement. Without this
        // fence a concurrent terminate could miss a newly assigned child.
        let retired = self
            .retired
            .lock()
            .map_err(|_| io::Error::other("worker group lifecycle lock poisoned"))?;
        if *retired || self.retirement_requested.load(Ordering::Acquire) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "worker group is retired; create a new group to restart",
            ));
        }
        if !spec.executable.is_absolute() || !spec.working_directory.is_absolute() {
            return Err(invalid("worker executable and directory must be absolute"));
        }
        let executable = spec.executable.canonicalize()?;
        let directory = spec.working_directory.canonicalize()?;
        if !executable.is_file()
            || !directory.is_dir()
            || !executable
                .extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("exe"))
        {
            return Err(invalid(
                "worker requires an existing .exe and working directory",
            ));
        }
        let application = wide_terminated(executable.as_os_str())?;
        let directory = wide_terminated(directory.as_os_str())?;
        let mut command = quote_argument(executable.as_os_str())?;
        for argument in &spec.arguments {
            command.push(b' ' as u16);
            command.extend(quote_argument(argument)?);
        }
        command.push(0);
        if command.len() > 32_767 {
            return Err(invalid("worker command exceeds Windows command line limit"));
        }
        let mut environment = environment_block(&spec.environment)?;
        let mut startup: STARTUPINFOW = unsafe { zeroed() };
        startup.cb = size_of::<STARTUPINFOW>() as u32;
        let startup_ptr = if let Some(capture) = &mut capture {
            capture.startup()
        } else {
            &startup
        };
        let (inherit_handles, extra_flags) = if capture.is_some() {
            (1, EXTENDED_STARTUPINFO_PRESENT)
        } else {
            (0, 0)
        };
        let mut information: PROCESS_INFORMATION = unsafe { zeroed() };
        // SAFETY: buffers outlive the call; executable is explicit; handles are
        // not inherited unless an exact HANDLE_LIST supplies only capture stdio;
        // execution is suspended until successful job assignment.
        let created = unsafe {
            CreateProcessW(
                application.as_ptr(),
                command.as_mut_ptr(),
                null(),
                null(),
                inherit_handles,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | extra_flags,
                environment.as_mut_ptr() as *const c_void,
                directory.as_ptr(),
                startup_ptr,
                &mut information,
            )
        };
        if created == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut suspended = SuspendedWorker {
            process: unsafe { OwnedHandle::from_raw_handle(information.hProcess) },
            thread: unsafe { OwnedHandle::from_raw_handle(information.hThread) },
            resumed: false,
        };
        assign(suspended.process.as_raw_handle())?;
        // A bounded retirement may time out waiting for this lifecycle fence.
        // It still permanently closes admission and cancels a launch that has
        // not yet reached the final resume decision.
        if self.retirement_requested.load(Ordering::Acquire) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "worker group retirement was requested during launch",
            ));
        }
        // Clone before resuming: even handle-allocation failure must not leak a
        // running worker whose ownership was never returned to the caller.
        let process = suspended.process.try_clone()?;
        if unsafe { ResumeThread(suspended.thread.as_raw_handle()) } == u32::MAX {
            return Err(io::Error::last_os_error());
        }
        suspended.resumed = true;
        Ok(Worker {
            process,
            pid: information.dwProcessId,
        })
    }

    pub(crate) fn assign(&self, process: HANDLE) -> io::Result<()> {
        if unsafe { AssignProcessToJobObject(self.job.as_raw_handle(), process) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    pub fn contains(&self, worker: &Worker) -> io::Result<bool> {
        let mut contained = 0;
        if unsafe {
            IsProcessInJob(
                worker.process.as_raw_handle(),
                self.job.as_raw_handle(),
                &mut contained,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(contained != 0)
    }

    /// Read-only membership snapshot for a PID observed by a trusted OS query.
    /// Never adopts, controls, or terminates the observed process. A descendant
    /// may own a socket even when its PID differs from the originally spawned
    /// root. Admission fails closed once retirement is requested or while the
    /// lifecycle fence is busy; this query never waits behind process creation.
    pub fn contains_observed_pid(&self, pid: u32) -> io::Result<bool> {
        if pid == 0 || self.retirement_requested.load(Ordering::Acquire) {
            return Ok(false);
        }
        let retired = match self.retired.try_lock() {
            Ok(guard) => guard,
            Err(TryLockError::WouldBlock) => return Ok(false),
            Err(TryLockError::Poisoned(_)) => {
                return Err(io::Error::other("worker group lifecycle lock poisoned"));
            }
        };
        if *retired || self.retirement_requested.load(Ordering::Acquire) {
            return Ok(false);
        }
        // SAFETY: query-only, non-inheritable process handle. It is closed once
        // by OwnedHandle and never used for termination or memory inspection.
        let raw = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
        if raw.is_null() {
            return Ok(false);
        }
        let process = unsafe { OwnedHandle::from_raw_handle(raw) };
        let mut contained = 0;
        if unsafe {
            IsProcessInJob(
                process.as_raw_handle(),
                self.job.as_raw_handle(),
                &mut contained,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(contained != 0 && !self.retirement_requested.load(Ordering::Acquire))
    }

    /// Escalation after cooperative cancellation/unload. Observe completion via
    /// wait_timeout/active_count; termination alone does not prove VRAM release.
    pub fn terminate(&self, exit_code: u32) -> io::Result<()> {
        let mut retired = self
            .retired
            .lock()
            .map_err(|_| io::Error::other("worker group lifecycle lock poisoned"))?;
        // Remain closed even if the kernel call fails; failure never reopens
        // admission. Repeated termination may retry cleanup, but never spawn.
        *retired = true;
        if unsafe { TerminateJobObject(self.job.as_raw_handle(), exit_code) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    /// Permanently close admission immediately, then wait at most `timeout`
    /// for the create/assign/resume fence before terminating the owned Job.
    /// A timeout reports incomplete cleanup: an in-flight launch may already
    /// have committed to resume. Retry termination or drop the group, whose
    /// kill-on-close Job remains the final containment backstop. Kernel calls
    /// themselves do not provide a hard real-time scheduling guarantee.
    pub fn terminate_timeout(&self, exit_code: u32, timeout: Duration) -> io::Result<()> {
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| invalid("retirement deadline is out of range"))?;
        self.retirement_requested.store(true, Ordering::Release);
        loop {
            match self.retired.try_lock() {
                Ok(mut retired) => {
                    *retired = true;
                    if unsafe { TerminateJobObject(self.job.as_raw_handle(), exit_code) } == 0 {
                        return Err(io::Error::last_os_error());
                    }
                    return Ok(());
                }
                Err(TryLockError::Poisoned(_)) => {
                    return Err(io::Error::other("worker group lifecycle lock poisoned"))
                }
                Err(TryLockError::WouldBlock) => {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        return Err(io::Error::new(io::ErrorKind::TimedOut, "worker group retirement fence deadline expired; admission remains closed"));
                    }
                    std::thread::sleep(remaining.min(Duration::from_millis(2)));
                }
            }
        }
    }

    pub fn active_count(&self) -> io::Result<u32> {
        let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { zeroed() };
        if unsafe {
            QueryInformationJobObject(
                self.job.as_raw_handle(),
                JobObjectBasicAccountingInformation,
                &mut accounting as *mut _ as *mut c_void,
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(accounting.ActiveProcesses)
    }
}

impl Worker {
    pub fn id(&self) -> u32 {
        self.pid
    }

    /// None means still running. No GPU-memory claim is made.
    pub fn wait_timeout(&self, timeout: Duration) -> io::Result<Option<u32>> {
        let milliseconds = timeout.as_millis().min((u32::MAX - 1) as u128) as u32;
        match unsafe { WaitForSingleObject(self.process.as_raw_handle(), milliseconds) } {
            WAIT_TIMEOUT => Ok(None),
            WAIT_OBJECT_0 => {
                let mut code = 0;
                if unsafe { GetExitCodeProcess(self.process.as_raw_handle(), &mut code) } == 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(Some(code))
            }
            _ => Err(io::Error::last_os_error()),
        }
    }
}

struct SuspendedWorker {
    process: OwnedHandle,
    thread: OwnedHandle,
    resumed: bool,
}

impl Drop for SuspendedWorker {
    fn drop(&mut self) {
        if !self.resumed {
            // SAFETY: stable handle refers only to the child we just created.
            unsafe {
                TerminateProcess(self.process.as_raw_handle(), 1);
                WaitForSingleObject(self.process.as_raw_handle(), 5_000);
            }
        }
    }
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

fn wide_terminated(value: &OsStr) -> io::Result<Vec<u16>> {
    let mut wide: Vec<u16> = value.encode_wide().collect();
    if wide.contains(&0) {
        return Err(invalid("NUL is not allowed in process inputs"));
    }
    wide.push(0);
    Ok(wide)
}

// Microsoft C/Rust argv convention; deliberately not shell quoting.
fn quote_argument(value: &OsStr) -> io::Result<Vec<u16>> {
    let value = wide_terminated(value)?;
    let mut quoted = vec![b'"' as u16];
    let mut backslashes = 0;
    for &unit in &value[..value.len() - 1] {
        if unit == b'\\' as u16 {
            backslashes += 1;
            continue;
        }
        let count = if unit == b'"' as u16 {
            backslashes * 2 + 1
        } else {
            backslashes
        };
        quoted.extend(std::iter::repeat_n(b'\\' as u16, count));
        backslashes = 0;
        quoted.push(unit);
    }
    quoted.extend(std::iter::repeat_n(b'\\' as u16, backslashes * 2));
    quoted.push(b'"' as u16);
    Ok(quoted)
}

fn environment_block(environment: &BTreeMap<String, OsString>) -> io::Result<Vec<u16>> {
    let mut names = BTreeSet::new();
    let mut ordered = Vec::new();
    for (name, value) in environment {
        // Conventional ASCII names make case folding and ordering unambiguous.
        if name.is_empty()
            || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
            || !names.insert(name.to_ascii_uppercase())
        {
            return Err(invalid(
                "invalid or case-duplicate environment variable name",
            ));
        }
        let mut entry = OsString::from(name);
        entry.push("=");
        entry.push(value);
        ordered.push((name.to_ascii_uppercase(), wide_terminated(&entry)?));
    }
    ordered.sort_by(|a, b| a.0.cmp(&b.0));
    let mut block: Vec<u16> = ordered.into_iter().flat_map(|(_, value)| value).collect();
    if block.is_empty() {
        block.push(0);
    }
    block.push(0);
    Ok(block)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn observed_membership_never_waits_on_lifecycle_or_admits_retirement() {
        let group = WorkerGroup::new().unwrap();
        let held = group.retired.lock().unwrap();
        let start = Instant::now();
        assert!(!group.contains_observed_pid(std::process::id()).unwrap());
        assert!(start.elapsed() < Duration::from_millis(100));
        drop(held);
        group.retirement_requested.store(true, Ordering::Release);
        assert!(!group.contains_observed_pid(std::process::id()).unwrap());
        assert!(!group.contains_observed_pid(0).unwrap());
    }

    #[test]
    fn environment_rejects_case_duplicates_and_nul() {
        let duplicate = BTreeMap::from([
            ("Path".into(), OsString::from("a")),
            ("PATH".into(), OsString::from("b")),
        ]);
        assert!(environment_block(&duplicate).is_err());
        assert!(
            environment_block(&BTreeMap::from([("KEY".into(), OsString::from("a\0b"))])).is_err()
        );
        assert_eq!(environment_block(&BTreeMap::new()).unwrap(), [0, 0]);
    }

    #[test]
    fn assignment_failure_terminates_suspended_child() {
        let group = WorkerGroup::new().unwrap();
        let exe = std::env::current_exe().unwrap();
        let spec = WorkerSpec {
            working_directory: exe.parent().unwrap().to_path_buf(),
            executable: exe,
            arguments: vec!["--list".into()],
            environment: BTreeMap::new(),
        };
        let mut captured = None;
        let result = group.spawn_impl(&spec, |process| {
            use std::os::windows::io::BorrowedHandle;
            captured = Some(
                unsafe { BorrowedHandle::borrow_raw(process) }
                    .try_clone_to_owned()
                    .unwrap(),
            );
            Err(io::Error::other("synthetic assignment failure"))
        });
        assert!(result.is_err());
        assert!(
            captured.is_some(),
            "process creation failed before synthetic assignment: {}",
            result.err().unwrap()
        );
        assert_eq!(
            unsafe { WaitForSingleObject(captured.unwrap().as_raw_handle(), 0) },
            WAIT_OBJECT_0
        );
        assert_eq!(group.active_count().unwrap(), 0);
    }

    #[test]
    fn retirement_serializes_with_suspended_spawn_and_fences_restart() {
        use std::sync::{mpsc, Arc};
        let group = Arc::new(WorkerGroup::new().unwrap());
        let exe = std::env::current_exe().unwrap();
        let spec = WorkerSpec {
            working_directory: exe.parent().unwrap().to_path_buf(),
            executable: exe,
            arguments: vec!["--list".into()],
            environment: BTreeMap::new(),
        };
        let (paused_tx, paused_rx) = mpsc::channel();
        let (resume_tx, resume_rx) = mpsc::channel();
        let (stop_started_tx, stop_started_rx) = mpsc::channel();
        let (stop_finished_tx, stop_finished_rx) = mpsc::channel();
        let spawning = group.clone();
        let spawn = std::thread::spawn(move || {
            spawning
                .spawn_impl(&spec, |process| {
                    paused_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    spawning.assign(process)
                })
                .unwrap()
        });
        paused_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        // The lifecycle fence is demonstrably held at the exact suspension
        // point, rather than inferred from thread scheduling or a quick exit.
        assert!(matches!(
            group.retired.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        ));
        let stopping = group.clone();
        let stop = std::thread::spawn(move || {
            stop_started_tx.send(()).unwrap();
            stopping.terminate(29).unwrap();
            stop_finished_tx.send(()).unwrap();
        });
        stop_started_rx
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        assert!(matches!(
            stop_finished_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        resume_tx.send(()).unwrap();
        let child = spawn.join().unwrap();
        stop.join().unwrap();
        assert!(child
            .wait_timeout(Duration::from_secs(5))
            .unwrap()
            .is_some());
        let invalid_after_retirement = WorkerSpec {
            executable: "unused.exe".into(),
            working_directory: "unused".into(),
            arguments: vec![],
            environment: BTreeMap::new(),
        };
        assert_eq!(
            group.spawn(&invalid_after_retirement).err().unwrap().kind(),
            io::ErrorKind::PermissionDenied
        );
    }

    #[test]
    fn bounded_retirement_closes_admission_when_spawn_fence_times_out() {
        use std::sync::{mpsc, Arc};
        let group = Arc::new(WorkerGroup::new().unwrap());
        let exe = std::env::current_exe().unwrap();
        let spec = WorkerSpec {
            working_directory: exe.parent().unwrap().to_path_buf(),
            executable: exe,
            arguments: vec!["--list".into()],
            environment: BTreeMap::new(),
        };
        let (paused_tx, paused_rx) = mpsc::channel();
        let (resume_tx, resume_rx) = mpsc::channel();
        let spawning = group.clone();
        let spawn = std::thread::spawn(move || {
            spawning.spawn_impl(&spec, |process| {
                paused_tx.send(()).unwrap();
                resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                spawning.assign(process)
            })
        });
        paused_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(
            group
                .terminate_timeout(29, Duration::from_millis(20))
                .unwrap_err()
                .kind(),
            io::ErrorKind::TimedOut
        );
        assert!(group.retirement_requested.load(Ordering::Acquire));
        resume_tx.send(()).unwrap();
        assert_eq!(
            spawn.join().unwrap().err().unwrap().kind(),
            io::ErrorKind::PermissionDenied
        );
        assert_eq!(group.active_count().unwrap(), 0);
        group.terminate_timeout(29, Duration::from_secs(1)).unwrap();
        let invalid_after_retirement = WorkerSpec {
            executable: "unused.exe".into(),
            working_directory: "unused".into(),
            arguments: vec![],
            environment: BTreeMap::new(),
        };
        assert_eq!(
            group.spawn(&invalid_after_retirement).err().unwrap().kind(),
            io::ErrorKind::PermissionDenied
        );
    }
}
