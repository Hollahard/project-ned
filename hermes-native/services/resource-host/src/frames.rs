//! Bounded LF-delimited UTF-8 frames, separate from child logs and readiness.

use std::collections::VecDeque;
use std::fmt;

#[derive(Clone, Copy, Debug)]
pub struct FrameLimits {
    /// Includes the final LF byte. Hard maximum is 64 KiB.
    pub frame_bytes: usize,
    /// Hard maximum is eight frames; total queued bytes <= 512 KiB.
    pub queued_frames: usize,
}
impl Default for FrameLimits {
    fn default() -> Self {
        Self {
            frame_bytes: 65_536,
            queued_frames: 8,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameError {
    InvalidLimits,
    TooLong,
    QueueOverflow,
    InvalidEncoding,
    IncompleteEof,
}
impl fmt::Display for FrameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidLimits => "invalid frame bounds",
            Self::TooLong => "child output frame exceeded its byte bound",
            Self::QueueOverflow => "child output frame queue exceeded its bound",
            Self::InvalidEncoding => "child emitted an empty or invalid UTF-8/LF frame",
            Self::IncompleteEof => "child stdout ended inside a frame",
        })
    }
}
impl std::error::Error for FrameError {}

pub(crate) struct FrameParser {
    limits: FrameLimits,
    partial: Vec<u8>,
    queue: VecDeque<Vec<u8>>,
    error: Option<FrameError>,
}
impl FrameParser {
    pub(crate) fn new(limits: FrameLimits) -> Result<Self, FrameError> {
        if !(2..=65_536).contains(&limits.frame_bytes) || !(1..=8).contains(&limits.queued_frames) {
            return Err(FrameError::InvalidLimits);
        }
        Ok(Self {
            limits,
            partial: Vec::new(),
            queue: VecDeque::new(),
            error: None,
        })
    }
    pub(crate) fn feed(&mut self, bytes: &[u8]) {
        if self.error.is_some() {
            return;
        }
        for &byte in bytes {
            if byte == b'\n' {
                if self.partial.is_empty() || std::str::from_utf8(&self.partial).is_err() {
                    self.fail(FrameError::InvalidEncoding);
                    return;
                }
                if self.queue.len() == self.limits.queued_frames {
                    self.fail(FrameError::QueueOverflow);
                    return;
                }
                self.queue.push_back(std::mem::take(&mut self.partial));
            } else if byte == b'\r' {
                self.fail(FrameError::InvalidEncoding);
                return;
            } else if self.partial.len() >= self.limits.frame_bytes - 1 {
                self.fail(FrameError::TooLong);
                return;
            } else {
                self.partial.push(byte);
            }
        }
    }
    pub(crate) fn eof(&mut self) {
        if self.error.is_none() && !self.partial.is_empty() {
            self.fail(FrameError::IncompleteEof);
        }
    }
    pub(crate) fn take(&mut self) -> Result<Option<Vec<u8>>, FrameError> {
        self.check()?;
        Ok(self.queue.pop_front())
    }
    pub(crate) fn check(&self) -> Result<(), FrameError> {
        self.error.map_or(Ok(()), Err)
    }
    fn fail(&mut self, error: FrameError) {
        self.error = Some(error);
        self.partial.clear();
        self.queue.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fragmented_frames_and_exact_byte_bound() {
        let mut parser = FrameParser::new(FrameLimits {
            frame_bytes: 4,
            queued_frames: 2,
        })
        .unwrap();
        parser.feed(b"ab");
        assert_eq!(parser.take(), Ok(None));
        parser.feed(b"c\nz\n");
        assert_eq!(parser.take(), Ok(Some(b"abc".to_vec())));
        assert_eq!(parser.take(), Ok(Some(b"z".to_vec())));
        parser.feed(b"abcd");
        assert_eq!(parser.take(), Err(FrameError::TooLong));
    }
    #[test]
    fn overflow_discards_old_frames_and_is_sticky() {
        let mut parser = FrameParser::new(FrameLimits {
            frame_bytes: 64,
            queued_frames: 1,
        })
        .unwrap();
        parser.feed(b"first\nsecond\n");
        assert_eq!(parser.take(), Err(FrameError::QueueOverflow));
        parser.feed(b"later\n");
        assert_eq!(parser.take(), Err(FrameError::QueueOverflow));
    }
    #[test]
    fn invalid_encoding_and_partial_eof_fail_closed() {
        for bytes in [b"\xff\n".as_slice(), b"\n", b"{}\r\n"] {
            let mut parser = FrameParser::new(FrameLimits::default()).unwrap();
            parser.feed(bytes);
            assert_eq!(parser.take(), Err(FrameError::InvalidEncoding));
        }
        let mut parser = FrameParser::new(FrameLimits::default()).unwrap();
        parser.feed(b"{}\npartial");
        parser.eof();
        assert_eq!(parser.take(), Err(FrameError::IncompleteEof));
    }
}
