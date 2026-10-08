//! Strict, bounded parsing of complete machine readiness records.

use std::fmt;

#[derive(Clone, Copy, Debug)]
pub struct ReadinessLimits {
    pub line_bytes: usize,
    pub total_bytes: u64,
}

impl Default for ReadinessLimits {
    fn default() -> Self {
        Self {
            line_bytes: 16_384,
            total_bytes: 2_097_152,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadinessError {
    InvalidLimits,
    LineTooLong,
    OutputTooLong,
    Malformed,
    ConflictingPorts,
    EndedBeforeReady,
}

impl fmt::Display for ReadinessError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidLimits => "invalid readiness bounds",
            Self::LineTooLong => "stdout exceeded readiness line bound",
            Self::OutputTooLong => "stdout exceeded readiness byte bound",
            Self::Malformed => "malformed readiness record",
            Self::ConflictingPorts => "conflicting readiness ports",
            Self::EndedBeforeReady => "stdout ended before a complete readiness record",
        })
    }
}

impl std::error::Error for ReadinessError {}

pub struct ReadinessParser {
    limits: ReadinessLimits,
    partial: Vec<u8>,
    total: u64,
    port: Option<u16>,
    error: Option<ReadinessError>,
}

impl ReadinessParser {
    pub fn new(limits: ReadinessLimits) -> Result<Self, ReadinessError> {
        if limits.line_bytes < 64
            || limits.line_bytes > 1_048_576
            || limits.total_bytes < limits.line_bytes as u64
        {
            return Err(ReadinessError::InvalidLimits);
        }
        Ok(Self {
            limits,
            partial: Vec::new(),
            total: 0,
            port: None,
            error: None,
        })
    }

    /// Errors are sticky and never include child output or credentials.
    /// A later conflicting record invalidates an earlier ready observation.
    pub fn feed(&mut self, bytes: &[u8]) {
        if self.error.is_some() {
            return;
        }
        self.total = self.total.saturating_add(bytes.len() as u64);
        if self.total > self.limits.total_bytes {
            self.fail(ReadinessError::OutputTooLong);
            return;
        }
        for &byte in bytes {
            if byte == b'\n' {
                self.line();
                self.partial.clear();
                if self.error.is_some() {
                    return;
                }
            } else if self.partial.len() == self.limits.line_bytes {
                self.fail(ReadinessError::LineTooLong);
                return;
            } else {
                self.partial.push(byte);
            }
        }
    }

    pub fn eof(&mut self) {
        if self.error.is_none() {
            if self.port.is_none() {
                self.fail(ReadinessError::EndedBeforeReady);
            } else if self.partial.starts_with(b"HERMES_BACKEND_READY")
                || self.partial.starts_with(b"HERMES_DASHBOARD_READY")
            {
                self.fail(ReadinessError::Malformed);
            }
        }
    }

    pub fn port(&self) -> Result<Option<u16>, ReadinessError> {
        self.error.map_or(Ok(self.port), Err)
    }

    fn fail(&mut self, error: ReadinessError) {
        self.error = Some(error);
        self.partial.clear();
    }

    fn line(&mut self) {
        let line = self.partial.strip_suffix(b"\r").unwrap_or(&self.partial);
        let prefix = [
            b"HERMES_BACKEND_READY".as_slice(),
            b"HERMES_DASHBOARD_READY".as_slice(),
        ]
        .into_iter()
        .find(|prefix| line.starts_with(prefix));
        let Some(prefix) = prefix else {
            return;
        };
        let Some(digits) = line[prefix.len()..].strip_prefix(b" port=") else {
            self.fail(ReadinessError::Malformed);
            return;
        };
        if digits.is_empty() || digits.len() > 5 || !digits.iter().all(u8::is_ascii_digit) {
            self.fail(ReadinessError::Malformed);
            return;
        }
        let port = digits
            .iter()
            .fold(0u32, |port, digit| port * 10 + u32::from(digit - b'0'));
        if !(1..=65535).contains(&port) {
            self.fail(ReadinessError::Malformed);
        } else if self
            .port
            .is_some_and(|previous| u32::from(previous) != port)
        {
            self.fail(ReadinessError::ConflictingPorts);
        } else {
            self.port = Some(port as u16);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parser() -> ReadinessParser {
        ReadinessParser::new(ReadinessLimits::default()).unwrap()
    }

    #[test]
    fn fragmented_crlf_and_duplicate_same_port() {
        let mut state = parser();
        state.feed(b"log \xff\nHERMES_BACK");
        state.feed(b"END_READY port=1234\r");
        assert_eq!(state.port(), Ok(None));
        state.feed(b"\nHERMES_DASHBOARD_READY port=1234\n");
        assert_eq!(state.port(), Ok(Some(1234)));
    }

    #[test]
    fn malformed_or_conflicting_records_are_sticky() {
        for record in [
            b"HERMES_BACKEND_READY port=0\n".as_slice(),
            b"HERMES_BACKEND_READY port=65536\n",
            b"HERMES_BACKEND_READY port=42 trailing\n",
            b"HERMES_BACKEND_READY_BAD port=42\n",
        ] {
            let mut state = parser();
            state.feed(record);
            state.feed(b"HERMES_BACKEND_READY port=42\n");
            assert_eq!(state.port(), Err(ReadinessError::Malformed));
        }
        let mut state = parser();
        state.feed(b"HERMES_BACKEND_READY port=1\nHERMES_BACKEND_READY port=2\n");
        assert_eq!(state.port(), Err(ReadinessError::ConflictingPorts));
    }

    #[test]
    fn bounds_and_eof_never_accept_partial_ready() {
        let mut state = ReadinessParser::new(ReadinessLimits {
            line_bytes: 64,
            total_bytes: 128,
        })
        .unwrap();
        state.feed(&[b'x'; 65]);
        assert_eq!(state.port(), Err(ReadinessError::LineTooLong));
        let mut state = ReadinessParser::new(ReadinessLimits {
            line_bytes: 64,
            total_bytes: 128,
        })
        .unwrap();
        state.feed(&[b'\n'; 129]);
        assert_eq!(state.port(), Err(ReadinessError::OutputTooLong));
        let mut state = parser();
        state.feed(b"HERMES_BACKEND_READY port=1");
        state.eof();
        assert_eq!(state.port(), Err(ReadinessError::EndedBeforeReady));
        assert!(ReadinessParser::new(ReadinessLimits {
            line_bytes: usize::MAX,
            total_bytes: u64::MAX
        })
        .is_err());
    }
}
