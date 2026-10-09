//! Empirical stress challenges for InputProgress wire offset tracking,
//! extreme frame fragmentation, interleaving control frames, and sticky error latches.

use std::collections::VecDeque;
use std::io::{self, Read, Write};
use tungstenite::{
    protocol::{Role, WebSocket, WebSocketConfig},
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
                .max_frame_size(Some(1024))
                .max_message_size(Some(2048)),
        ),
    )
}

#[test]
fn stress_challenge_fragmented_frames_byte_by_byte_monotonic_tracking() {
    // Construct a fragmented message:
    // Fragment 1: Opcode 0x01 (Text), FIN=0, payload "frag1" (5 bytes) -> frame len = 2 + 5 = 7 bytes.
    // Ping: Opcode 0x89 (Ping), FIN=1, payload "ping1" (5 bytes) -> frame len = 2 + 5 = 7 bytes.
    // Fragment 2: Opcode 0x00 (Cont), FIN=0, payload "frag2" (5 bytes) -> frame len = 2 + 5 = 7 bytes.
    // Pong: Opcode 0x8a (Pong), FIN=1, payload "pong1" (5 bytes) -> frame len = 2 + 5 = 7 bytes.
    // Fragment 3: Opcode 0x80 (Cont), FIN=1, payload "frag3" (5 bytes) -> frame len = 2 + 5 = 7 bytes.
    // Total wire bytes = 35 bytes.
    let mut wire = Vec::new();
    // Frag 1 (text start): bytes 0..7
    wire.extend_from_slice(&[0x01, 5]);
    wire.extend_from_slice(b"frag1");
    // Ping 1: bytes 7..14
    wire.extend_from_slice(&[0x89, 5]);
    wire.extend_from_slice(b"ping1");
    // Frag 2 (continuation): bytes 14..21
    wire.extend_from_slice(&[0x00, 5]);
    wire.extend_from_slice(b"frag2");
    // Pong 1: bytes 21..28
    wire.extend_from_slice(&[0x8a, 5]);
    wire.extend_from_slice(b"pong1");
    // Frag 3 (continuation final): bytes 28..35
    wire.extend_from_slice(&[0x80, 5]);
    wire.extend_from_slice(b"frag3");

    let mut ws = socket();
    ws.get_mut().maximum = 1;

    let mut messages = Vec::new();
    let mut last_buffered_end = 0;
    let mut last_buffered_start = 0;

    for (byte_idx, &byte) in wire.iter().enumerate() {
        ws.get_mut().push(&[byte]);
        loop {
            match ws.read() {
                Ok(msg) => {
                    messages.push(msg);
                }
                Err(Error::Io(ref e)) if e.kind() == io::ErrorKind::WouldBlock => {
                    break;
                }
                Err(other) => panic!("Unexpected read error at byte {byte_idx}: {other:?}"),
            }
        }
        let p = ws.input_progress().unwrap();

        // Invariant 1: Wire end must match total bytes pushed so far
        assert_eq!(p.buffered_wire_end, (byte_idx + 1) as u64);
        assert!(p.buffered_wire_end >= last_buffered_end);
        last_buffered_end = p.buffered_wire_end;

        // Invariant 2: Buffered start must never exceed buffered end
        assert!(p.buffered_wire_start <= p.buffered_wire_end);
        assert!(p.buffered_wire_start >= last_buffered_start);
        last_buffered_start = p.buffered_wire_start;

        // Invariant 3: Fragmented data tracking:
        // Before frag 1 completes (byte_idx < 6), fragmented_data_start is None.
        // Once frag 1 completes (byte_idx >= 6) and until frag 3 completes (byte_idx < 34),
        // fragmented_data_start must be Some(0).
        if (6..34).contains(&byte_idx) {
            assert_eq!(
                p.fragmented_data_start,
                Some(0),
                "fragmented_data_start lost at byte {byte_idx}"
            );
            assert!(p.fragmented_data_frame_count >= 1);
        }
    }

    // After all 35 bytes are read:
    // We should have received: Ping("ping1"), Pong("pong1"), and Text("frag1frag2frag3")
    assert_eq!(messages.len(), 3);
    assert_eq!(messages[0], Message::Ping(b"ping1".to_vec().into()));
    assert_eq!(messages[1], Message::Pong(b"pong1".to_vec().into()));
    assert_eq!(messages[2], Message::text("frag1frag2frag3"));

    let final_p = ws.input_progress().unwrap();
    assert_eq!(final_p.buffered_wire_start, 35);
    assert_eq!(final_p.buffered_wire_end, 35);
    assert_eq!(final_p.completed_frame_count, 5);
    assert_eq!(final_p.fragmented_data_start, None);
    assert_eq!(final_p.fragmented_data_frame_count, 0);
}

#[test]
fn stress_challenge_frame_progress_latch_invariance_under_illegal_state_transitions() {
    use counters::FrameProgress;

    // Test 1: once failed via illegal advance, FrameProgress permanently rejects ALL methods
    let mut p = FrameProgress::default();
    assert!(p.check().is_ok());

    // Advance past received triggers fail()
    assert!(p.advance(10).is_err());
    assert!(p.failed);

    // Assert that every single subsequent call fails
    assert!(p.check().is_err());
    assert!(p.receive(10).is_err());
    assert!(p.advance(0).is_err());
    assert!(p.begin().is_err());
    assert!(p.increment(1).is_err());
    assert!(p.finish().is_err());
    assert!(p.snapshot().is_err());

    // Test 2: finish() without begin() triggers failure and sticky latch
    let mut p2 = FrameProgress::default();
    p2.receive(10).unwrap();
    assert!(p2.finish().is_err());
    assert!(p2.failed);
    assert!(p2.check().is_err());
    assert!(p2.snapshot().is_err());
    assert!(p2.advance(1).is_err());
    assert!(p2.receive(1).is_err());

    // Test 3: Arithmetic overflow triggers failure and sticky latch
    let mut p3 = FrameProgress {
        received: u64::MAX,
        ..Default::default()
    };
    assert!(p3.receive(1).is_err());
    assert!(p3.failed);
    assert!(p3.check().is_err());
    assert!(p3.snapshot().is_err());

    // Test 4: Counter overflow triggers failure and sticky latch
    let mut p4 = FrameProgress::default();
    assert!(p4.increment(u64::MAX).is_err());
    assert!(p4.failed);
    assert!(p4.check().is_err());
    assert!(p4.snapshot().is_err());
}

#[test]
fn stress_challenge_randomized_chunk_splits_across_multiplexed_frames() {
    // Generate a sequence of 10 messages: alternating text, ping, binary
    let mut full_wire = Vec::new();
    let mut expected_messages = 0;
    for i in 0..10 {
        if i % 3 == 0 {
            // Text frame
            let payload = format!("hello_{i}");
            full_wire.push(0x81);
            full_wire.push(payload.len() as u8);
            full_wire.extend_from_slice(payload.as_bytes());
            expected_messages += 1;
        } else if i % 3 == 1 {
            // Ping frame
            let payload = format!("ping_{i}");
            full_wire.push(0x89);
            full_wire.push(payload.len() as u8);
            full_wire.extend_from_slice(payload.as_bytes());
            expected_messages += 1;
        } else {
            // Binary frame
            let payload = vec![i as u8; 4];
            full_wire.push(0x82);
            full_wire.push(payload.len() as u8);
            full_wire.extend_from_slice(&payload);
            expected_messages += 1;
        }
    }

    // Deterministic pseudo-random chunk chunking (using simple LCG)
    let mut lcg: u64 = 0xdeadbeef;
    let next_chunk_size = |state: &mut u64| -> usize {
        *state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        ((*state >> 32) % 7 + 1) as usize // Chunks from 1 to 7 bytes
    };

    let mut ws = socket();
    let mut offset = 0;
    let mut received_messages = 0;

    while offset < full_wire.len() {
        let chunk_size = next_chunk_size(&mut lcg).min(full_wire.len() - offset);
        ws.get_mut().push(&full_wire[offset..offset + chunk_size]);
        offset += chunk_size;

        loop {
            match ws.read() {
                Ok(_) => {
                    received_messages += 1;
                }
                Err(Error::Io(ref e)) if e.kind() == io::ErrorKind::WouldBlock => {
                    break;
                }
                Err(e) => panic!("Unexpected error during chunk stream: {e:?}"),
            }
        }
        let p = ws.input_progress().unwrap();
        assert_eq!(p.buffered_wire_end, offset as u64);
        assert!(p.buffered_wire_start <= p.buffered_wire_end);
    }

    assert_eq!(received_messages, expected_messages);
    let final_p = ws.input_progress().unwrap();
    assert_eq!(final_p.completed_frame_count, 10);
    assert_eq!(final_p.buffered_wire_start, full_wire.len() as u64);
    assert_eq!(final_p.buffered_wire_end, full_wire.len() as u64);
}
