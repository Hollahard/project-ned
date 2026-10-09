//! Numeric observations only; no frame syntax or payload parsing.
use std::io;

/// Read-only parser progress in WebSocket wire bytes (HTTP headers excluded).
/// Buffered tail may contain complete frames; it is not necessarily stalled input.
/// Use only after a successful read or WouldBlock, not after other protocol errors.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InputProgress {
    /// First byte still buffered, after any parsed header has been consumed.
    pub buffered_wire_start: u64,
    /// Exclusive end of all bytes acquired, including preserved handshake tail.
    pub buffered_wire_end: u64,
    /// Start of the parser's current frame, including a partial header.
    /// Unparsed coalesced tail is represented by the buffered range instead.
    pub pending_frame_start: Option<u64>,
    /// First data frame of the current fragmented message; controls do not change it.
    pub fragmented_data_start: Option<u64>,
    /// Fully decoded frames, including control frames (not application acceptance).
    pub completed_frame_count: u64,
    /// Completed data frames of the current fragmented message, excluding controls.
    pub fragmented_data_frame_count: u64,
}

#[derive(Debug, Default)]
pub(super) struct FrameProgress {
    pub(super) received: u64,
    pub(super) consumed: u64,
    pub(super) current_start: Option<u64>,
    pub(super) last_start: Option<u64>,
    pub(super) completed: u64,
    pub(super) failed: bool,
}

pub(super) fn progress_error() -> io::Error {
    io::Error::other("WebSocket input progress exhausted")
}

impl FrameProgress {
    pub(super) fn check(&self) -> io::Result<()> {
        if self.failed {
            Err(progress_error())
        } else {
            Ok(())
        }
    }
    pub(super) fn fail(&mut self) -> io::Error {
        self.failed = true;
        progress_error()
    }
    pub(super) fn receive(&mut self, size: usize) -> io::Result<()> {
        self.check()?;
        let size = u64::try_from(size).map_err(|_| self.fail())?;
        self.received = self.received.checked_add(size).ok_or_else(|| self.fail())?;
        Ok(())
    }
    pub(super) fn advance(&mut self, size: usize) -> io::Result<()> {
        self.check()?;
        let size = u64::try_from(size).map_err(|_| self.fail())?;
        let next = self.consumed.checked_add(size).ok_or_else(|| self.fail())?;
        if next > self.received {
            return Err(self.fail());
        }
        self.consumed = next;
        Ok(())
    }
    pub(super) fn begin(&mut self) -> io::Result<()> {
        self.check()?;
        if self.current_start.is_none() && self.consumed < self.received {
            self.current_start = Some(self.consumed);
        }
        Ok(())
    }
    pub(super) fn increment(&mut self, counter: u64) -> io::Result<u64> {
        self.check()?;
        counter.checked_add(1).ok_or_else(|| self.fail())
    }
    pub(super) fn finish(&mut self) -> io::Result<()> {
        self.check()?;
        let count = self.increment(self.completed)?;
        let start = self.current_start.ok_or_else(|| self.fail())?;
        self.completed = count;
        self.last_start = Some(start);
        self.current_start = None;
        Ok(())
    }
    pub(super) fn snapshot(&self) -> io::Result<InputProgress> {
        self.check()?;
        Ok(InputProgress {
            buffered_wire_start: self.consumed,
            buffered_wire_end: self.received,
            pending_frame_start: self.current_start,
            fragmented_data_start: None,
            completed_frame_count: self.completed,
            fragmented_data_frame_count: 0,
        })
    }
}
