//! Windows ConPTY feasibility host. No UI, backend service or shell policy is integrated.
#![cfg(windows)]

use std::collections::{BTreeMap, VecDeque};
use std::ffi::{c_void, OsStr};
use std::fs::File;
use std::io::{self, Read, Write};
use std::mem::{size_of, zeroed};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::path::PathBuf;
use std::ptr::{null, null_mut};
use std::sync::{mpsc, Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{HANDLE, WAIT_OBJECT_0, WAIT_TIMEOUT};
use windows_sys::Win32::System::Console::{
    ClosePseudoConsole, CreatePseudoConsole, ResizePseudoConsole, COORD, HPCON,
};
use windows_sys::Win32::System::JobObjects::*;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Threading::*;

const INPUT_LIMIT: usize = 4096;
const INPUT_QUEUE: usize = 16;

pub struct TerminalSpec {
    pub executable: PathBuf,
    pub arguments: Vec<String>,
    pub working_directory: PathBuf,
    /// Explicit environment only; parent credentials are not inherited.
    pub environment: BTreeMap<String, String>,
    pub columns: i16,
    pub rows: i16,
    pub output_capacity: usize,
}

#[derive(Debug)]
pub struct OutputChunk {
    pub bytes: Vec<u8>,
    /// Sticky loss indicator. A renderer must resynchronize, never hide this loss.
    pub overflowed: bool,
    /// True only after the native pipe closed and all retained bytes were drained.
    pub eof: bool,
}

#[derive(Default)]
struct OutputState {
    bytes: VecDeque<u8>,
    overflowed: bool,
    eof: bool,
    error: Option<String>,
}
type SharedOutput = Arc<(Mutex<OutputState>, Condvar)>;

struct PseudoConsole(HPCON);
impl Drop for PseudoConsole {
    fn drop(&mut self) {
        // SAFETY: This is the sole HPCON owner. The output reader remains alive.
        unsafe { ClosePseudoConsole(self.0) };
    }
}

struct Attributes {
    storage: Vec<usize>,
    initialized: bool,
}
impl Attributes {
    fn new() -> io::Result<Self> {
        let mut bytes = 0;
        // SAFETY: The first call obtains the allocation size and initializes no list.
        unsafe { InitializeProcThreadAttributeList(null_mut(), 2, 0, &mut bytes) };
        if bytes == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut list = Self {
            storage: vec![0; bytes.div_ceil(size_of::<usize>())],
            initialized: false,
        };
        // SAFETY: Pointer-aligned allocation has at least the requested number of bytes.
        check(unsafe { InitializeProcThreadAttributeList(list.ptr(), 2, 0, &mut bytes) })?;
        list.initialized = true;
        Ok(list)
    }
    fn ptr(&mut self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
        self.storage.as_mut_ptr().cast()
    }
}
impl Drop for Attributes {
    fn drop(&mut self) {
        // SAFETY: Successfully initialized list remains allocated through deletion.
        if self.initialized {
            unsafe { DeleteProcThreadAttributeList(self.ptr()) };
        }
    }
}

pub struct Terminal {
    process: Option<OwnedHandle>,
    job: OwnedHandle,
    pseudo: Option<PseudoConsole>,
    input: Option<mpsc::SyncSender<Vec<u8>>>,
    reader: Option<JoinHandle<()>>,
    writer: Option<JoinHandle<()>>,
    output: SharedOutput,
    setup_handles: Vec<OwnedHandle>,
}

impl Terminal {
    pub fn spawn(spec: TerminalSpec) -> io::Result<Self> {
        validate(&spec)?;
        let output: SharedOutput = Arc::new((Mutex::new(OutputState::default()), Condvar::new()));
        // SAFETY: Null security/name create a private, non-inheritable unnamed job.
        let job = own(unsafe { CreateJobObjectW(null(), null()) })?;
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // SAFETY: Struct and size match the selected information class.
        check(unsafe {
            SetInformationJobObject(
                raw(&job),
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of_val(&limits) as u32,
            )
        })?;
        let (input_read, input_write) = pipe()?;
        let (output_read, output_write) = pipe()?;
        let output_for_reader = Arc::clone(&output);
        let reader = thread::Builder::new()
            .name("conpty-output".into())
            .spawn(move || {
                let mut file = File::from(output_read);
                let mut buffer = [0u8; 4096];
                loop {
                    let count = match file.read(&mut buffer) {
                        Ok(0) => break,
                        Err(error) if error.kind() == io::ErrorKind::BrokenPipe => break,
                        Err(error) => {
                            output_for_reader
                                .0
                                .lock()
                                .unwrap_or_else(|error| error.into_inner())
                                .error = Some(error.to_string());
                            break;
                        }
                        Ok(count) => count,
                    };
                    let (lock, changed) = &*output_for_reader;
                    let mut state = lock.lock().unwrap_or_else(|error| error.into_inner());
                    let available = spec.output_capacity.saturating_sub(state.bytes.len());
                    state.bytes.extend(&buffer[..count.min(available)]);
                    state.overflowed |= count > available;
                    changed.notify_all();
                }
                let (lock, changed) = &*output_for_reader;
                lock.lock().unwrap_or_else(|error| error.into_inner()).eof = true;
                changed.notify_all();
            })?;
        let mut session = Self {
            process: None,
            job,
            pseudo: None,
            input: None,
            reader: Some(reader),
            writer: None,
            output,
            setup_handles: vec![input_read, output_write],
        };
        let mut pseudo = 0;
        // SAFETY: Pipe handles and dimensions are valid and live through child creation.
        hr(unsafe {
            CreatePseudoConsole(
                COORD {
                    X: spec.columns,
                    Y: spec.rows,
                },
                raw(&session.setup_handles[0]),
                raw(&session.setup_handles[1]),
                0,
                &mut pseudo,
            )
        })?;
        session.pseudo = Some(PseudoConsole(pseudo));

        let (sender, receiver) = mpsc::sync_channel::<Vec<u8>>(INPUT_QUEUE);
        session.input = Some(sender);
        session.writer = Some(thread::Builder::new().name("conpty-input".into()).spawn(
            move || {
                let mut file = File::from(input_write);
                while let Ok(bytes) = receiver.recv() {
                    if file.write_all(&bytes).is_err() {
                        break;
                    }
                }
            },
        )?);
        // Keep attribute storage alive until after DeleteProcThreadAttributeList.
        let jobs = Box::new([raw(&session.job)]);
        let mut attributes = Attributes::new()?;
        // SAFETY: HPCON is passed by value as documented; job handle array remains live.
        check(unsafe {
            UpdateProcThreadAttribute(
                attributes.ptr(),
                0,
                PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE as usize,
                pseudo as *const c_void,
                size_of::<HPCON>(),
                null_mut(),
                null(),
            )
        })?;
        check(unsafe {
            UpdateProcThreadAttribute(
                attributes.ptr(),
                0,
                PROC_THREAD_ATTRIBUTE_JOB_LIST as usize,
                jobs.as_ptr().cast(),
                size_of_val(jobs.as_ref()),
                null_mut(),
                null(),
            )
        })?;
        let mut startup: STARTUPINFOEXW = unsafe { zeroed() };
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        // ConPTY must allocate its own standard handles even when this host was
        // launched with redirected output (Microsoft terminal discussion #15814).
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.lpAttributeList = attributes.ptr();
        let mut info: PROCESS_INFORMATION = unsafe { zeroed() };
        let executable = wide(spec.executable.as_os_str())?;
        let cwd = wide(spec.working_directory.as_os_str())?;
        let command = std::iter::once(
            spec.executable
                .to_str()
                .expect("validated UTF-8 path")
                .to_owned(),
        )
        .chain(spec.arguments)
        .map(|argument| quote(&argument))
        .collect::<Vec<_>>()
        .join(" ");
        let mut command = wide(OsStr::new(&command))?;
        let environment = environment_block(&spec.environment)?;
        // SAFETY: Buffers and attributes remain valid for this call. No generic handle
        // inheritance; the job-list attribute makes ownership atomic with creation.
        check(unsafe {
            CreateProcessW(
                executable.as_ptr(),
                command.as_mut_ptr(),
                null(),
                null(),
                0,
                EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                environment.as_ptr().cast(),
                cwd.as_ptr(),
                &startup.StartupInfo,
                &mut info,
            )
        })?;
        session.process = Some(own(info.hProcess)?);
        drop(own(info.hThread)?);
        // Release parent copies so the reader can observe pipe closure at teardown.
        session.setup_handles.clear();
        Ok(session)
    }

    pub fn write(&self, bytes: &[u8]) -> io::Result<()> {
        if bytes.len() > INPUT_LIMIT {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "input exceeds 4096-byte frame limit",
            ));
        }
        let sender = self
            .input
            .as_ref()
            .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "terminal closed"))?;
        sender
            .try_send(bytes.to_vec())
            .map_err(|error| match error {
                mpsc::TrySendError::Full(_) => {
                    io::Error::new(io::ErrorKind::WouldBlock, "terminal input queue full")
                }
                mpsc::TrySendError::Disconnected(_) => {
                    io::Error::new(io::ErrorKind::BrokenPipe, "terminal input closed")
                }
            })
    }

    pub fn read(&self, max_bytes: usize, timeout: Duration) -> io::Result<OutputChunk> {
        if max_bytes == 0 || max_bytes > 1_048_576 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid read bound",
            ));
        }
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "read deadline overflow"))?;
        let (lock, changed) = &*self.output;
        let mut state = lock.lock().unwrap_or_else(|error| error.into_inner());
        while state.bytes.is_empty() && !state.eof && !state.overflowed {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "terminal read deadline",
                ));
            }
            state = changed
                .wait_timeout(state, remaining)
                .unwrap_or_else(|error| error.into_inner())
                .0;
        }
        if let Some(error) = &state.error {
            return Err(io::Error::other(format!("terminal output failed: {error}")));
        }
        let count = max_bytes.min(state.bytes.len());
        let bytes = state.bytes.drain(..count).collect();
        Ok(OutputChunk {
            bytes,
            overflowed: state.overflowed,
            eof: state.eof && state.bytes.is_empty(),
        })
    }

    pub fn resize(&self, columns: i16, rows: i16) -> io::Result<()> {
        dimensions(columns, rows)?;
        let pseudo = self
            .pseudo
            .as_ref()
            .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "terminal closed"))?;
        // SAFETY: The live HPCON is owned by this terminal and resize does not consume it.
        hr(unsafe {
            ResizePseudoConsole(
                pseudo.0,
                COORD {
                    X: columns,
                    Y: rows,
                },
            )
        })
    }

    pub fn wait(&self, timeout: Duration) -> io::Result<Option<u32>> {
        let Some(process) = self.process.as_ref() else {
            return Ok(None);
        };
        // SAFETY: Owned process handle stays open throughout both calls.
        match unsafe {
            WaitForSingleObject(
                raw(process),
                timeout.as_millis().min(u32::MAX as u128 - 1) as u32,
            )
        } {
            WAIT_TIMEOUT => Ok(None),
            WAIT_OBJECT_0 => {
                let mut code = 0;
                check(unsafe { GetExitCodeProcess(raw(process), &mut code) })?;
                Ok(Some(code))
            }
            _ => Err(io::Error::last_os_error()),
        }
    }

    pub fn active_processes(&self) -> io::Result<u32> {
        let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { zeroed() };
        // SAFETY: Information class, initialized output allocation and length agree.
        check(unsafe {
            QueryInformationJobObject(
                raw(&self.job),
                JobObjectBasicAccountingInformation,
                (&mut info as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                size_of_val(&info) as u32,
                null_mut(),
            )
        })?;
        Ok(info.ActiveProcesses)
    }

    /// Terminates only this job; native ConPTY close itself has no timeout parameter.
    pub fn close(&mut self) -> io::Result<()> {
        // SAFETY: This private job contains only the child created with its job-list attribute.
        let result = check(unsafe { TerminateJobObject(raw(&self.job), 137) });
        self.input.take();
        self.setup_handles.clear();
        self.pseudo.take(); // Keep output draining while ClosePseudoConsole completes.
        if let Some(writer) = self.writer.take() {
            let _ = writer.join();
        }
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
        result
    }
}
impl Drop for Terminal {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

fn check(value: i32) -> io::Result<()> {
    if value == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}
fn hr(value: i32) -> io::Result<()> {
    if value < 0 {
        Err(io::Error::other(format!(
            "ConPTY HRESULT 0x{:08x}",
            value as u32
        )))
    } else {
        Ok(())
    }
}
fn raw(handle: &OwnedHandle) -> HANDLE {
    handle.as_raw_handle()
}
fn own(handle: HANDLE) -> io::Result<OwnedHandle> {
    if handle.is_null() || handle as isize == -1 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: Caller transfers one successful Win32 owning handle, exactly once.
    Ok(unsafe { OwnedHandle::from_raw_handle(handle) })
}
fn pipe() -> io::Result<(OwnedHandle, OwnedHandle)> {
    let (mut read, mut write) = (null_mut(), null_mut());
    // SAFETY: Valid output pointers and non-inheritable default security.
    check(unsafe { CreatePipe(&mut read, &mut write, null(), 0) })?;
    Ok((own(read)?, own(write)?))
}
fn wide(value: &OsStr) -> io::Result<Vec<u16>> {
    let mut value: Vec<u16> = value.encode_wide().collect();
    if value.contains(&0) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "embedded NUL"));
    }
    value.push(0);
    Ok(value)
}
fn dimensions(columns: i16, rows: i16) -> io::Result<()> {
    if columns <= 0 || rows <= 0 {
        Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "terminal dimensions must be positive",
        ))
    } else {
        Ok(())
    }
}
fn validate(spec: &TerminalSpec) -> io::Result<()> {
    dimensions(spec.columns, spec.rows)?;
    if spec.executable.to_str().is_none()
        || !spec.executable.is_absolute()
        || !spec.executable.is_file()
        || !spec.working_directory.is_absolute()
        || !spec.working_directory.is_dir()
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "absolute existing executable and cwd required",
        ));
    }
    if !(1024..=1_048_576).contains(&spec.output_capacity) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "output capacity must be 1024..1048576",
        ));
    }
    Ok(())
}
fn environment_block(environment: &BTreeMap<String, String>) -> io::Result<Vec<u16>> {
    let mut block = Vec::new();
    let mut keys = std::collections::HashSet::new();
    let mut entries: Vec<_> = environment.iter().collect();
    entries.sort_by_cached_key(|(key, _)| key.to_uppercase());
    for (key, value) in entries {
        if key.is_empty() || key.contains('=') || !keys.insert(key.to_uppercase()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid or duplicate environment name",
            ));
        }
        block.extend(wide(OsStr::new(&format!("{key}={value}")))?);
    }
    if block.is_empty() {
        block.push(0);
    }
    block.push(0);
    Ok(block)
}
fn quote(value: &str) -> String {
    let mut result = String::from("\"");
    let mut slashes = 0;
    for character in value.chars() {
        if character == '\\' {
            slashes += 1;
            continue;
        }
        if character == '"' {
            result.extend(std::iter::repeat_n('\\', slashes * 2 + 1));
        } else {
            result.extend(std::iter::repeat_n('\\', slashes));
        }
        slashes = 0;
        result.push(character);
    }
    result.extend(std::iter::repeat_n('\\', slashes * 2));
    result.push('"');
    result
}
