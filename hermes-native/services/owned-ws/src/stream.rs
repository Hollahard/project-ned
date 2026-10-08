//! Same-socket stream budget shared by handshake and automatic control writes.
use hermes_resource_host::WorkerGroup;
use std::io::{self, Read, Write};
use std::net::TcpStream;
use std::time::Instant;
const WIRE_LIMIT: usize = 4 * 1024 * 1024;
pub(crate) struct DeadlineStream<'a> {
    pub tcp: TcpStream,
    group: &'a WorkerGroup,
    pid: u32,
    deadline: Instant,
    wire_bytes: usize,
    header_limit: Option<usize>,
    header_bytes: usize,
    tail: [u8; 4],
}
impl<'a> DeadlineStream<'a> {
    pub fn new(
        tcp: TcpStream,
        group: &'a WorkerGroup,
        pid: u32,
        deadline: Instant,
        header_limit: usize,
    ) -> Self {
        Self {
            tcp,
            group,
            pid,
            deadline,
            wire_bytes: 0,
            header_limit: Some(header_limit),
            header_bytes: 0,
            tail: [0; 4],
        }
    }
    pub fn finish_handshake(&mut self) {
        self.header_limit = None;
    }
    pub fn reset(&mut self, deadline: Instant) {
        self.deadline = deadline;
        self.wire_bytes = 0;
    }
    pub fn check(&self) -> io::Result<()> {
        if self.deadline <= Instant::now() {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "socket deadline"));
        }
        if !self.group.contains_observed_pid(self.pid)? {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "socket owner retired",
            ));
        }
        Ok(())
    }
    fn budget(&self) -> io::Result<std::time::Duration> {
        self.check()?;
        let left = self.deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            Err(io::Error::new(io::ErrorKind::TimedOut, "socket deadline"))
        } else {
            Ok(left)
        }
    }
    fn allowance(&self, length: usize) -> io::Result<usize> {
        let available = WIRE_LIMIT.saturating_sub(self.wire_bytes);
        if available == 0 {
            Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "socket byte budget",
            ))
        } else {
            Ok(length.min(available))
        }
    }
}
impl Read for DeadlineStream<'_> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let timeout = self.budget()?;
        self.tcp.set_read_timeout(Some(timeout))?;
        let mut max = self.allowance(buffer.len())?;
        if let Some(limit) = self.header_limit {
            if self.header_bytes >= limit {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "upgrade header limit",
                ));
            }
            max = max.min(limit - self.header_bytes);
        }
        let count = self.tcp.read(&mut buffer[..max])?;
        self.wire_bytes += count;
        if self.header_limit.is_some() {
            for byte in &buffer[..count] {
                self.header_bytes += 1;
                self.tail.rotate_left(1);
                self.tail[3] = *byte;
                if self.tail == *b"\r\n\r\n" {
                    self.header_limit = None;
                    break;
                }
            }
        }
        Ok(count)
    }
}
impl Write for DeadlineStream<'_> {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let timeout = self.budget()?;
        self.tcp.set_write_timeout(Some(timeout))?;
        let max = self.allowance(buffer.len())?;
        let count = self.tcp.write(&buffer[..max])?;
        self.wire_bytes += count;
        Ok(count)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.check()?;
        self.tcp.flush()
    }
}
