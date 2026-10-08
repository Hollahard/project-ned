//! Captured output uses one exclusive reader per pipe. PeekNamedPipe bounds each
//! synchronous read to bytes already buffered, so no reader waits for a newline.
//! Drops request cancellation and never join threads or wait for a process.

use crate::frames::{FrameLimits, FrameParser};
use crate::{ReadinessLimits, ReadinessParser, Worker, WorkerGroup};
use std::collections::VecDeque;
use std::ffi::c_void;
use std::io;
use std::mem::{size_of, zeroed};
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{
    SetHandleInformation, ERROR_BROKEN_PIPE, ERROR_NO_DATA, HANDLE, HANDLE_FLAG_INHERIT,
    INVALID_HANDLE_VALUE,
};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, ReadFile, FILE_GENERIC_READ, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
};
use windows_sys::Win32::System::Pipes::{CreatePipe, PeekNamedPipe};
use windows_sys::Win32::System::Threading::{
    DeleteProcThreadAttributeList, InitializeProcThreadAttributeList, UpdateProcThreadAttribute,
    LPPROC_THREAD_ATTRIBUTE_LIST, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, STARTF_USESTDHANDLES,
    STARTUPINFOEXW, STARTUPINFOW,
};

const POLL: Duration = Duration::from_millis(2);

#[derive(Clone, Copy, Debug, Default)]
pub struct CaptureLimits {
    pub readiness: ReadinessLimits,
    /// Optional bounded raw diagnostic tails. Zero by default: child output can
    /// contain credentials. Never log tails without a caller-owned redactor.
    pub tail_bytes_per_stream: usize,
}

/// Deliberately no Debug implementation because tails may contain secrets.
pub struct OutputSnapshot {
    pub stdout_bytes: u64,
    pub stderr_bytes: u64,
    pub stdout_eof: bool,
    pub stderr_eof: bool,
    pub stdout_tail: Vec<u8>,
    pub stderr_tail: Vec<u8>,
}

#[derive(Debug)]
pub struct CaptureReport {
    pub exit_code: u32,
    pub stdout_bytes: u64,
    pub stderr_bytes: u64,
}

pub struct CapturedWorker {
    worker: Worker,
    io: CaptureIo,
}

impl CapturedWorker {
    pub fn worker(&self) -> &Worker {
        &self.worker
    }
    pub fn id(&self) -> u32 {
        self.worker.id()
    }

    /// This only parses a live child's readiness announcement. The caller must
    /// still verify listener/socket ownership and authenticated service identity.
    /// Later malformed/conflicting records invalidate an earlier observation.
    pub fn wait_ready(&self, timeout: Duration) -> io::Result<u16> {
        let deadline = deadline(timeout)?;
        loop {
            let port = self.readiness()?;
            if self.worker.wait_timeout(Duration::ZERO)?.is_some() {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "owned child exited before readiness verification",
                ));
            }
            if let Some(port) = port {
                return Ok(port);
            }
            pause(deadline)?;
        }
    }

    pub fn readiness(&self) -> io::Result<Option<u16>> {
        let state = self
            .io
            .state
            .lock()
            .map_err(|_| io::Error::other("capture lock poisoned"))?;
        state.check_errors()?;
        state
            .readiness
            .as_ref()
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::Unsupported,
                    "port readiness is disabled for framed stdout",
                )
            })?
            .port()
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
    }

    pub(crate) fn recv_frame(&self, timeout: Duration) -> io::Result<Vec<u8>> {
        let deadline = deadline(timeout)?;
        loop {
            {
                let mut state = self
                    .io
                    .state
                    .lock()
                    .map_err(|_| io::Error::other("capture lock poisoned"))?;
                state.check_errors()?;
                let frames = state.frames.as_mut().ok_or_else(|| {
                    io::Error::new(io::ErrorKind::Unsupported, "stdout framing is disabled")
                })?;
                if let Some(frame) = frames
                    .take()
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?
                {
                    return Ok(frame);
                }
                if state.stdout.eof {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "child stdout ended without another frame",
                    ));
                }
            }
            pause(deadline)?;
        }
    }

    pub(crate) fn check_frames(&self) -> io::Result<()> {
        let state = self
            .io
            .state
            .lock()
            .map_err(|_| io::Error::other("capture lock poisoned"))?;
        state.check_errors()?;
        state
            .frames
            .as_ref()
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::Unsupported, "stdout framing is disabled")
            })?
            .check()
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
    }

    pub fn output_snapshot(&self) -> io::Result<OutputSnapshot> {
        let state = self
            .io
            .state
            .lock()
            .map_err(|_| io::Error::other("capture lock poisoned"))?;
        state.check_errors()?;
        Ok(OutputSnapshot {
            stdout_bytes: state.stdout.bytes,
            stderr_bytes: state.stderr.bytes,
            stdout_eof: state.stdout.eof,
            stderr_eof: state.stderr.eof,
            stdout_tail: state.stdout.tail.iter().copied().collect(),
            stderr_tail: state.stderr.tail.iter().copied().collect(),
        })
    }

    /// Wait for root exit, both actual pipe EOFs, and drainer completion. This
    /// never terminates a process; a descendant retaining a writer causes a
    /// deadline error. Use WorkerGroup::retire_captured for tree cleanup.
    pub fn finish_capture(&self, timeout: Duration) -> io::Result<CaptureReport> {
        let deadline = deadline(timeout)?;
        loop {
            let output = self.output_snapshot()?;
            if let Some(exit_code) = self.worker.wait_timeout(Duration::ZERO)? {
                if output.stdout_eof
                    && output.stderr_eof
                    && self.io.threads.iter().all(JoinHandle::is_finished)
                {
                    return Ok(CaptureReport {
                        exit_code,
                        stdout_bytes: output.stdout_bytes,
                        stderr_bytes: output.stderr_bytes,
                    });
                }
            }
            if self.io.threads.iter().any(JoinHandle::is_finished)
                && !(output.stdout_eof && output.stderr_eof)
            {
                let state = self
                    .io
                    .state
                    .lock()
                    .map_err(|_| io::Error::other("capture lock poisoned"))?;
                if state.stdout.cancelled || state.stderr.cancelled {
                    return Err(io::Error::other("capture was cancelled before pipe EOF"));
                }
            }
            pause(deadline)?;
        }
    }
}

impl WorkerGroup {
    /// Retire this entire resource family, then verify root exit, zero Job
    /// members and output EOF within one deadline. Never accepts an unowned
    /// worker, never reopens admission, and never terminates by PID or port.
    pub fn retire_captured(
        &self,
        worker: &CapturedWorker,
        exit_code: u32,
        timeout: Duration,
    ) -> io::Result<CaptureReport> {
        let deadline = deadline(timeout)?;
        if !self.contains(worker.worker())? {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "worker does not belong to this group",
            ));
        }
        self.terminate_timeout(
            exit_code,
            deadline.saturating_duration_since(Instant::now()),
        )?;
        let report = worker.finish_capture(deadline.saturating_duration_since(Instant::now()))?;
        while self.active_count()? != 0 {
            pause(deadline)?;
        }
        Ok(report)
    }
}

fn deadline(timeout: Duration) -> io::Result<Instant> {
    Instant::now().checked_add(timeout).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "capture deadline is out of range",
        )
    })
}

fn pause(deadline: Instant) -> io::Result<()> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "owned capture deadline expired",
        ));
    }
    thread::sleep(POLL.min(remaining));
    Ok(())
}

#[derive(Default)]
struct StreamState {
    bytes: u64,
    tail: VecDeque<u8>,
    eof: bool,
    cancelled: bool,
    error: Option<i32>,
}
struct State {
    stdout: StreamState,
    stderr: StreamState,
    readiness: Option<ReadinessParser>,
    frames: Option<FrameParser>,
    tail_limit: usize,
}
impl State {
    fn check_errors(&self) -> io::Result<()> {
        if let Some(code) = self.stdout.error.or(self.stderr.error) {
            return Err(io::Error::from_raw_os_error(code));
        }
        Ok(())
    }
}
struct CaptureIo {
    state: Arc<Mutex<State>>,
    stop: Arc<AtomicBool>,
    threads: Vec<JoinHandle<()>>,
}
impl Drop for CaptureIo {
    fn drop(&mut self) {
        // Detached readers own all referenced handles/state. Their bounded peek
        // loop observes this flag; no destructor blocks on child cooperation.
        self.stop.store(true, Ordering::Release);
    }
}

pub(crate) struct CapturedSetup {
    // Child handles remain open until after CreateProcessW; dropping this setup
    // then releases parent copies so child/tree exit can produce real pipe EOF.
    stdio: [OwnedHandle; 3],
    attributes: AttributeList,
    startup: STARTUPINFOEXW,
    io: Option<CaptureIo>,
}

impl CapturedSetup {
    pub(crate) fn new(limits: CaptureLimits) -> io::Result<Self> {
        Self::new_common(limits, None, None)
    }

    pub(crate) fn new_framed(limits: FrameLimits, stdin: OwnedHandle) -> io::Result<Self> {
        let frames = FrameParser::new(limits)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
        Self::new_common(CaptureLimits::default(), Some(frames), Some(stdin))
    }

    fn new_common(
        limits: CaptureLimits,
        frames: Option<FrameParser>,
        stdin: Option<OwnedHandle>,
    ) -> io::Result<Self> {
        if limits.tail_bytes_per_stream > 1_048_576 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "capture tail exceeds 1 MiB per stream",
            ));
        }
        let parser = if frames.is_none() {
            Some(
                ReadinessParser::new(limits.readiness)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?,
            )
        } else {
            None
        };
        let security = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: null_mut(),
            bInheritHandle: 1,
        };
        let stdin = if let Some(stdin) = stdin {
            stdin
        } else {
            let nul = [b'N' as u16, b'U' as u16, b'L' as u16, 0];
            let raw = unsafe {
                CreateFileW(
                    nul.as_ptr(),
                    FILE_GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    &security,
                    OPEN_EXISTING,
                    0,
                    null_mut(),
                )
            };
            if raw == INVALID_HANDLE_VALUE {
                return Err(io::Error::last_os_error());
            }
            unsafe { OwnedHandle::from_raw_handle(raw) }
        };
        let (stdout_read, stdout_write) = pipe(&security)?;
        let (stderr_read, stderr_write) = pipe(&security)?;
        let stdio = [stdin, stdout_write, stderr_write];
        let handles = stdio.each_ref().map(AsRawHandle::as_raw_handle);
        let attributes = AttributeList::new(&handles)?;
        let mut startup: STARTUPINFOEXW = unsafe { zeroed() };
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = handles[0];
        startup.StartupInfo.hStdOutput = handles[1];
        startup.StartupInfo.hStdError = handles[2];
        startup.lpAttributeList = attributes.pointer();
        let state = Arc::new(Mutex::new(State {
            stdout: StreamState::default(),
            stderr: StreamState::default(),
            readiness: parser,
            frames,
            tail_limit: limits.tail_bytes_per_stream,
        }));
        let mut io = CaptureIo {
            state,
            stop: Arc::new(AtomicBool::new(false)),
            threads: Vec::new(),
        };
        for (handle, stdout) in [(stdout_read, true), (stderr_read, false)] {
            let state = io.state.clone();
            let stop = io.stop.clone();
            io.threads.push(
                thread::Builder::new()
                    .name(
                        if stdout {
                            "hermes-stdout"
                        } else {
                            "hermes-stderr"
                        }
                        .into(),
                    )
                    .spawn(move || drain(handle, stdout, state, stop))?,
            );
        }
        Ok(Self {
            stdio,
            attributes,
            startup,
            io: Some(io),
        })
    }

    pub(crate) fn startup(&self) -> *const STARTUPINFOW {
        // Keep the backing stdio/attribute allocations explicitly live.
        let _ = (&self.stdio, &self.attributes);
        &self.startup.StartupInfo
    }
    pub(crate) fn finish(mut self, worker: Worker) -> CapturedWorker {
        CapturedWorker {
            worker,
            io: self.io.take().expect("capture IO transferred once"),
        }
    }
}

fn pipe(security: &SECURITY_ATTRIBUTES) -> io::Result<(OwnedHandle, OwnedHandle)> {
    let (mut read, mut write) = (null_mut(), null_mut());
    if unsafe { CreatePipe(&mut read, &mut write, security, 0) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let read = unsafe { OwnedHandle::from_raw_handle(read) };
    let write = unsafe { OwnedHandle::from_raw_handle(write) };
    if unsafe { SetHandleInformation(read.as_raw_handle(), HANDLE_FLAG_INHERIT, 0) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok((read, write))
}

struct AttributeList {
    storage: Vec<usize>,
    _handles: Box<[HANDLE; 3]>,
}
impl AttributeList {
    fn pointer(&self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
        self.storage.as_ptr() as LPPROC_THREAD_ATTRIBUTE_LIST
    }
    fn new(handles: &[HANDLE; 3]) -> io::Result<Self> {
        let mut bytes = 0;
        unsafe {
            InitializeProcThreadAttributeList(null_mut(), 1, 0, &mut bytes);
        }
        if bytes == 0 {
            return Err(io::Error::last_os_error());
        }
        // usize allocation supplies the alignment required by this opaque list.
        let mut list = Self {
            storage: vec![0; bytes.div_ceil(size_of::<usize>())],
            _handles: Box::new(*handles),
        };
        if unsafe { InitializeProcThreadAttributeList(list.pointer(), 1, 0, &mut bytes) } == 0 {
            // An uninitialized list must not run DeleteProcThreadAttributeList.
            list.storage.clear();
            return Err(io::Error::last_os_error());
        }
        if unsafe {
            UpdateProcThreadAttribute(
                list.pointer(),
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
                list._handles.as_ptr() as *const c_void,
                size_of::<[HANDLE; 3]>(),
                null_mut(),
                null(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(list)
    }
}
impl Drop for AttributeList {
    fn drop(&mut self) {
        if !self.storage.is_empty() {
            unsafe {
                DeleteProcThreadAttributeList(self.pointer());
            }
        }
    }
}

fn drain(handle: OwnedHandle, stdout: bool, state: Arc<Mutex<State>>, stop: Arc<AtomicBool>) {
    let mut buffer = [0u8; 4096];
    let outcome: Result<bool, i32> = (|| {
        while !stop.load(Ordering::Acquire) {
            let mut available = 0;
            if unsafe {
                PeekNamedPipe(
                    handle.as_raw_handle(),
                    null_mut(),
                    0,
                    null_mut(),
                    &mut available,
                    null_mut(),
                )
            } == 0
            {
                let code = io::Error::last_os_error().raw_os_error().unwrap_or(1);
                return if matches!(code as u32, ERROR_BROKEN_PIPE | ERROR_NO_DATA) {
                    Ok(true)
                } else {
                    Err(code)
                };
            }
            if available == 0 {
                thread::sleep(POLL);
                continue;
            }
            let mut count = 0;
            // This is the only reader, and n <= already buffered bytes. The
            // read cannot wait for additional child output or an entire line.
            let ok = unsafe {
                ReadFile(
                    handle.as_raw_handle(),
                    buffer.as_mut_ptr(),
                    available.min(buffer.len() as u32),
                    &mut count,
                    null_mut(),
                )
            };
            if ok == 0 {
                return Err(io::Error::last_os_error().raw_os_error().unwrap_or(1));
            }
            if count == 0 {
                return Ok(true);
            }
            let mut state = state.lock().map_err(|_| 1)?;
            let tail_limit = state.tail_limit;
            if stdout {
                if let Some(readiness) = &mut state.readiness {
                    readiness.feed(&buffer[..count as usize]);
                }
                if let Some(frames) = &mut state.frames {
                    frames.feed(&buffer[..count as usize]);
                }
            }
            let stream = if stdout {
                &mut state.stdout
            } else {
                &mut state.stderr
            };
            stream.bytes = stream.bytes.saturating_add(u64::from(count));
            if tail_limit != 0 {
                for byte in &buffer[..count as usize] {
                    if stream.tail.len() == tail_limit {
                        stream.tail.pop_front();
                    }
                    stream.tail.push_back(*byte);
                }
            }
        }
        Ok(false)
    })();
    if let Ok(mut state) = state.lock() {
        if stdout && outcome == Ok(true) {
            if let Some(readiness) = &mut state.readiness {
                readiness.eof();
            }
            if let Some(frames) = &mut state.frames {
                frames.eof();
            }
        }
        let stream = if stdout {
            &mut state.stdout
        } else {
            &mut state.stderr
        };
        match outcome {
            Ok(true) => stream.eof = true,
            Ok(false) => stream.cancelled = true,
            Err(code) => stream.error = Some(code),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dropping_unlaunched_setup_releases_reader_threads_without_child_cooperation() {
        let setup = CapturedSetup::new(CaptureLimits::default()).unwrap();
        let state = Arc::downgrade(&setup.io.as_ref().unwrap().state);
        drop(setup);
        let end = Instant::now() + Duration::from_secs(2);
        while state.upgrade().is_some() {
            assert!(
                Instant::now() < end,
                "reader threads retained capture state after cancellation"
            );
            thread::sleep(POLL);
        }
    }
}
