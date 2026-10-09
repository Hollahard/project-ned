//! In-memory parser tests run in the parent crate, not only vendor unit tests.
use std::collections::VecDeque;
use std::io::{self, Read, Write};
use tungstenite::{
    protocol::{InputProgress, Role, WebSocket, WebSocketConfig},
    Error, Message,
};

#[allow(dead_code)]
#[path = "../vendor/tungstenite/src/protocol/progress.rs"]
mod counters;

#[derive(Default)]
struct Segmented {
    input: VecDeque<u8>,
    maximum: usize,
    written: Vec<u8>,
    eof: bool,
}
impl Segmented {
    fn push(&mut self, bytes: &[u8]) {
        self.input.extend(bytes);
    }
}
impl Read for Segmented {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if self.input.is_empty() {
            return if self.eof {
                Ok(0)
            } else {
                Err(io::ErrorKind::WouldBlock.into())
            };
        }
        let n = out.len().min(self.input.len()).min(self.maximum.max(1));
        for byte in &mut out[..n] {
            *byte = self.input.pop_front().unwrap();
        }
        Ok(n)
    }
}
impl Write for Segmented {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.written.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
fn socket() -> WebSocket<Segmented> {
    WebSocket::from_raw_socket(
        Segmented {
            maximum: 4096,
            ..Default::default()
        },
        Role::Client,
        Some(
            WebSocketConfig::default()
                .max_frame_size(Some(256))
                .max_message_size(Some(512)),
        ),
    )
}
fn blocked(ws: &mut WebSocket<Segmented>) -> InputProgress {
    assert!(matches!(ws.read(), Err(Error::Io(ref e)) if e.kind()==io::ErrorKind::WouldBlock));
    ws.input_progress().unwrap()
}
#[test]
fn idle_partial_header_payload_and_completion_have_exact_wire_offsets() {
    let mut ws = socket();
    assert_eq!(blocked(&mut ws).buffered_wire_end, 0);
    ws.get_mut().push(&[0x81]);
    let p = blocked(&mut ws);
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (0, 1, Some(0))
    );
    ws.get_mut().push(&[3, b'a']);
    let p = blocked(&mut ws);
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (2, 3, Some(0))
    );
    ws.get_mut().push(b"bc");
    assert_eq!(ws.read().unwrap(), Message::text("abc"));
    let p = ws.input_progress().unwrap();
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start,
            p.completed_frame_count
        ),
        (5, 5, None, 1)
    );
}
#[test]
fn coalesced_complete_message_and_partial_extended_header_keep_distinct_ranges() {
    let mut ws = socket();
    ws.get_mut().push(&[0x81, 1, b'a', 0x82, 126, 0]);
    assert_eq!(ws.read().unwrap(), Message::text("a"));
    let p = ws.input_progress().unwrap();
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (3, 6, None)
    );
    let p = blocked(&mut ws);
    assert_eq!(p.pending_frame_start, Some(3));
    ws.get_mut().push(&[126]);
    let p = blocked(&mut ws);
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (7, 7, Some(3))
    );
    ws.get_mut().push(&[b'x'; 126]);
    assert_eq!(ws.read().unwrap(), Message::binary(vec![b'x'; 126]));
    let p = ws.input_progress().unwrap();
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.completed_frame_count
        ),
        (133, 133, 2)
    );
}
#[test]
fn fragmented_message_survives_ping_pong_and_coalesced_next_partial() {
    let mut ws = socket();
    ws.get_mut().push(&[0x01, 1, b'a', 0x89, 1, b'p']);
    assert!(matches!(ws.read().unwrap(), Message::Ping(_)));
    let p = ws.input_progress().unwrap();
    assert_eq!(
        (
            p.fragmented_data_start,
            p.fragmented_data_frame_count,
            p.completed_frame_count
        ),
        (Some(0), 1, 2)
    );
    ws.get_mut().push(&[0x8a, 0, 0x00, 1, b'b']);
    assert!(matches!(ws.read().unwrap(), Message::Pong(_)));
    let p = blocked(&mut ws);
    assert_eq!(
        (
            p.fragmented_data_start,
            p.fragmented_data_frame_count,
            p.completed_frame_count
        ),
        (Some(0), 2, 4)
    );
    ws.get_mut().push(&[0x80, 1, b'c', 0x81]);
    assert_eq!(ws.read().unwrap(), Message::text("abc"));
    let p = ws.input_progress().unwrap();
    assert_eq!(
        (
            p.fragmented_data_start,
            p.fragmented_data_frame_count,
            p.completed_frame_count
        ),
        (None, 0, 5)
    );
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (14, 15, None)
    );
    assert_eq!(blocked(&mut ws).pending_frame_start, Some(14));
    ws.get_mut().push(&[0]);
    assert_eq!(ws.read().unwrap(), Message::text(""));
    assert!(!ws.get_ref().written.is_empty()); // automatic Pong was retained.
}
#[test]
fn preloaded_handshake_tail_starts_at_websocket_zero_and_read_is_observational() {
    let mut ws = WebSocket::from_partially_read(
        Segmented {
            maximum: 1,
            ..Default::default()
        },
        vec![0x81, 1, b'a', 0x82, 1],
        Role::Client,
        None,
    );
    let before = ws.input_progress().unwrap();
    assert_eq!(before.buffered_wire_end, 5);
    assert_eq!(before, ws.input_progress().unwrap());
    assert!(ws.get_ref().written.is_empty());
    assert_eq!(ws.read().unwrap(), Message::text("a"));
    let p = blocked(&mut ws);
    assert_eq!(
        (
            p.buffered_wire_start,
            p.buffered_wire_end,
            p.pending_frame_start
        ),
        (5, 5, Some(3))
    );
    ws.get_mut().push(b"b");
    assert_eq!(ws.read().unwrap(), Message::binary(vec![b'b']));
    assert_eq!(ws.input_progress().unwrap().buffered_wire_end, 6);
}
#[test]
fn all_segment_boundaries_preserve_unicode_and_control_interleaving() {
    let bytes = [0x01, 1, 0xe9, 0x89, 0, 0x80, 2, 0x9b, 0xaa];
    for cut in 0..=bytes.len() {
        let mut ws = socket();
        ws.get_mut().maximum = 1;
        ws.get_mut().push(&bytes[..cut]);
        let mut events = Vec::new();
        let mut end = 0;
        loop {
            match ws.read() {
                Ok(m) => events.push(m),
                Err(Error::Io(e)) if e.kind() == io::ErrorKind::WouldBlock => break,
                other => panic!("{other:?}"),
            };
            let p = ws.input_progress().unwrap();
            assert!(p.buffered_wire_end >= end);
            end = p.buffered_wire_end;
        }
        let p = ws.input_progress().unwrap();
        assert_eq!(p.buffered_wire_end, cut as u64);
        ws.get_mut().push(&bytes[cut..]);
        loop {
            match ws.read() {
                Ok(m) => events.push(m),
                Err(Error::Io(e)) if e.kind() == io::ErrorKind::WouldBlock => break,
                other => panic!("{other:?}"),
            };
        }
        assert!(matches!(&events[0], Message::Ping(_)));
        assert_eq!(events[1], Message::text("雪"));
        assert_eq!(events.len(), 2);
        let p = ws.input_progress().unwrap();
        assert_eq!(
            (
                p.buffered_wire_start,
                p.buffered_wire_end,
                p.completed_frame_count
            ),
            (9, 9, 3)
        );
        assert_eq!(p.fragmented_data_start, None);
    }
}
#[test]
fn offsets_include_mask_header_and_malformed_inputs_still_fail() {
    let mut ws = WebSocket::from_raw_socket(
        Segmented {
            maximum: 1,
            ..Default::default()
        },
        Role::Server,
        None,
    );
    ws.get_mut()
        .push(&[0x81, 0x83, 1, 2, 3, 4, b'a' ^ 1, b'b' ^ 2, b'c' ^ 3]);
    assert_eq!(ws.read().unwrap(), Message::text("abc"));
    let p = ws.input_progress().unwrap();
    assert_eq!((p.buffered_wire_start, p.buffered_wire_end), (9, 9));
    let mut ws = socket();
    ws.get_mut().push(&[0x81, 1, 0xff]);
    assert!(matches!(ws.read(), Err(Error::Utf8(_))));
    let mut ws = socket();
    ws.get_mut().push(&[0x80, 0]);
    assert!(matches!(ws.read(), Err(Error::Protocol(_))));
}
#[test]
fn partial_eof_remains_protocol_error_not_completed_frame() {
    let mut ws = socket();
    ws.get_mut().push(&[0x81, 3, b'a']);
    blocked(&mut ws);
    ws.get_mut().eof = true;
    assert!(matches!(ws.read(), Err(Error::Protocol(_))));
}
#[test]
fn progress_arithmetic_overflow_and_invalid_advance_are_sticky() {
    use counters::FrameProgress;
    let mut p = FrameProgress {
        received: u64::MAX,
        ..Default::default()
    };
    assert!(p.receive(1).is_err());
    assert!(p.snapshot().is_err());
    assert!(p.receive(0).is_err());
    assert!(p.begin().is_err());
    let mut p = FrameProgress {
        received: u64::MAX,
        consumed: u64::MAX,
        ..Default::default()
    };
    assert!(p.advance(1).is_err());
    assert!(p.check().is_err());
    let mut p = FrameProgress {
        completed: u64::MAX,
        current_start: Some(0),
        ..Default::default()
    };
    assert!(p.finish().is_err());
    assert_eq!(p.completed, u64::MAX);
    assert!(p.snapshot().is_err());
    let mut p = FrameProgress::default();
    assert!(p.increment(u64::MAX).is_err());
    assert!(p.increment(0).is_err());
    let mut p = FrameProgress::default();
    assert!(p.advance(1).is_err());
    assert!(p.snapshot().is_err());
}
