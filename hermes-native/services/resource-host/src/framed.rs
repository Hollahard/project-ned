//! Optional bounded control transport. No shell, socket listener or application
//! authentication is introduced; only inherited stdio reaches the owned child.

use crate::capture::CapturedSetup;
use crate::{CapturedWorker, FrameLimits, WorkerGroup, WorkerSpec};
use std::io;
use std::mem::size_of;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::ptr::{null, null_mut};
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::Cryptography::{
    BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, WriteFile, FILE_FLAG_FIRST_PIPE_INSTANCE, FILE_GENERIC_READ, OPEN_EXISTING,
    PIPE_ACCESS_OUTBOUND,
};
use windows_sys::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, GetNamedPipeClientProcessId, PIPE_NOWAIT,
    PIPE_READMODE_BYTE, PIPE_REJECT_REMOTE_CLIENTS, PIPE_TYPE_BYTE,
};

/// Sequential LF-delimited UTF-8 transport. Frame bytes have no Debug wrapper or
/// implicit logs. The application owns JSON validation, IDs and authorization.
pub struct FramedWorker {
    capture: CapturedWorker,
    input: Option<OwnedHandle>,
    limits: FrameLimits,
}

impl WorkerGroup {
    pub fn spawn_framed(&self, spec: &WorkerSpec, limits: FrameLimits) -> io::Result<FramedWorker> {
        let (input, child_input) = input_pipe()?;
        let mut setup = CapturedSetup::new_framed(limits, child_input)?;
        let worker = self.spawn_native(spec, |process| self.assign(process), Some(&mut setup))?;
        Ok(FramedWorker {
            capture: setup.finish(worker),
            input: Some(input),
            limits,
        })
    }
}

impl FramedWorker {
    pub fn capture(&self) -> &CapturedWorker {
        &self.capture
    }

    /// Queue one payload without LF into the pipe. Success means the kernel
    /// accepted the bytes, not that the child read or applied the request; an
    /// application reply is still required. A write timeout/error may follow
    /// partial delivery. Input is permanently closed so the caller cannot retry
    /// on an uncertain stream. Retire the group before starting a replacement.
    pub fn write_frame(&mut self, payload: &[u8], timeout: Duration) -> io::Result<()> {
        if self.input.is_none() {
            return Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "framed input is closed",
            ));
        }
        if payload.is_empty()
            || payload.len() >= self.limits.frame_bytes
            || payload.contains(&b'\n')
            || payload.contains(&b'\r')
            || std::str::from_utf8(payload).is_err()
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid or oversized UTF-8/LF frame payload",
            ));
        }
        let deadline = Instant::now().checked_add(timeout).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "write deadline is out of range",
            )
        })?;
        let mut frame = Vec::with_capacity(payload.len() + 1);
        frame.extend_from_slice(payload);
        frame.push(b'\n');
        let result = self.write_until(&frame, deadline);
        if result.is_err() {
            self.close_stdin();
        }
        result
    }

    fn write_until(&self, bytes: &[u8], deadline: Instant) -> io::Result<()> {
        let handle = self.input.as_ref().expect("write input was checked");
        let mut sent = 0;
        while sent < bytes.len() {
            self.capture.check_frames()?;
            if self
                .capture
                .worker()
                .wait_timeout(Duration::ZERO)?
                .is_some()
            {
                return Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "owned child exited before frame delivery",
                ));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "framed input deadline expired; delivery is uncertain",
                ));
            }
            let mut written = 0;
            // PIPE_NOWAIT byte mode returns immediately, including partial or
            // zero progress when the peer stops consuming. No FlushFileBuffers.
            if unsafe {
                WriteFile(
                    handle.as_raw_handle(),
                    bytes[sent..].as_ptr(),
                    (bytes.len() - sent) as u32,
                    &mut written,
                    null_mut(),
                )
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
            sent += written as usize;
            if written == 0 {
                std::thread::sleep(Duration::from_millis(2).min(remaining));
            }
        }
        Ok(())
    }

    pub fn recv_frame(&self, timeout: Duration) -> io::Result<Vec<u8>> {
        self.capture.recv_frame(timeout)
    }

    /// Finite local close, with no flush or wait for the child. The child sees
    /// EOF/broken pipe; pending input is not guaranteed delivered. For graceful
    /// shutdown, await the application reply before closing this handle.
    pub fn close_stdin(&mut self) {
        self.input.take();
    }
}

fn input_pipe() -> io::Result<(OwnedHandle, OwnedHandle)> {
    let mut nonce = [0u8; 16];
    if unsafe {
        BCryptGenRandom(
            null_mut(),
            nonce.as_mut_ptr(),
            nonce.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    } < 0
    {
        return Err(io::Error::other("failed to obtain private pipe nonce"));
    }
    let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
    let name: Vec<u16> = format!(r"\\.\pipe\hermes-native-stdin-{suffix}")
        .encode_utf16()
        .chain(Some(0))
        .collect();
    // Parent is the sole non-inheritable server writer. The only instance is
    // connected locally by this process before the child starts. Random names,
    // first-instance enforcement and client PID verification reject pipe races.
    let raw = unsafe {
        CreateNamedPipeW(
            name.as_ptr(),
            PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            4096,
            0,
            0,
            null(),
        )
    };
    if raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let writer = unsafe { OwnedHandle::from_raw_handle(raw) };
    let security = SECURITY_ATTRIBUTES {
        nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: null_mut(),
        bInheritHandle: 1,
    };
    // Client defaults to blocking byte reads, as expected by Python stdin.
    let raw = unsafe {
        CreateFileW(
            name.as_ptr(),
            FILE_GENERIC_READ,
            0,
            &security,
            OPEN_EXISTING,
            0,
            null_mut(),
        )
    };
    if raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let reader = unsafe { OwnedHandle::from_raw_handle(raw) };
    if unsafe { ConnectNamedPipe(writer.as_raw_handle(), null_mut()) } == 0
        && io::Error::last_os_error().raw_os_error() != Some(ERROR_PIPE_CONNECTED as i32)
    {
        return Err(io::Error::last_os_error());
    }
    let mut client_pid = 0;
    if unsafe { GetNamedPipeClientProcessId(writer.as_raw_handle(), &mut client_pid) } == 0 {
        return Err(io::Error::last_os_error());
    }
    if client_pid != std::process::id() {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private input pipe has unexpected client ownership",
        ));
    }
    Ok((writer, reader))
}
