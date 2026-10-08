#![cfg(all(windows, feature = "test-fixture"))]

use hermes_resource_host::{FrameLimits, WorkerGroup, WorkerSpec};
use std::collections::BTreeMap;
use std::io::ErrorKind;
use std::path::PathBuf;
use std::time::{Duration, Instant};

const WAIT: Duration = Duration::from_secs(10);
fn spec(mode: &str) -> WorkerSpec {
    WorkerSpec {
        executable: PathBuf::from(env!("CARGO_BIN_EXE_worker-fixture")),
        arguments: vec![mode.into()],
        working_directory: std::env::temp_dir(),
        environment: BTreeMap::new(),
    }
}

#[test]
fn framed_roundtrip_unicode_and_exact_maximum_size_then_stdin_eof() {
    let group = WorkerGroup::new().unwrap();
    let mut worker = group
        .spawn_framed(&spec("framed-echo"), FrameLimits::default())
        .unwrap();
    assert_eq!(worker.recv_frame(WAIT).unwrap(), br#"{"type":"ready"}"#);
    assert_eq!(
        worker.capture().readiness().unwrap_err().kind(),
        ErrorKind::Unsupported
    );
    let request = "{\"id\":\"one\",\"name\":\"雪😀\"}";
    worker.write_frame(request.as_bytes(), WAIT).unwrap();
    assert_eq!(worker.recv_frame(WAIT).unwrap(), request.as_bytes());
    let maximum = vec![b'x'; 65_535];
    worker.write_frame(&maximum, WAIT).unwrap();
    assert_eq!(worker.recv_frame(WAIT).unwrap(), maximum);
    worker.close_stdin();
    assert_eq!(worker.capture().finish_capture(WAIT).unwrap().exit_code, 0);
    // A signaled root handle and captured EOF can precede Windows Job accounting.
    // Keep a separate bounded empty-Job proof instead of assuming one snapshot.
    let empty_deadline = Instant::now() + WAIT;
    while group.active_count().unwrap() != 0 {
        assert!(
            Instant::now() < empty_deadline,
            "owned Job did not become empty"
        );
        std::thread::sleep(Duration::from_millis(2));
    }
    assert_eq!(
        worker.write_frame(b"{}", WAIT).unwrap_err().kind(),
        ErrorKind::BrokenPipe
    );
}

#[test]
fn backpressure_write_times_out_closes_input_and_does_not_retry_partial_frame() {
    let group = WorkerGroup::new().unwrap();
    let mut worker = group
        .spawn_framed(&spec("framed-no-read"), FrameLimits::default())
        .unwrap();
    worker.recv_frame(WAIT).unwrap();
    let start = Instant::now();
    assert_eq!(
        worker
            .write_frame(&vec![b'x'; 65_535], Duration::from_millis(40))
            .unwrap_err()
            .kind(),
        ErrorKind::TimedOut
    );
    assert!(start.elapsed() < Duration::from_secs(2));
    assert_eq!(
        worker.write_frame(b"{}", WAIT).unwrap_err().kind(),
        ErrorKind::BrokenPipe
    );
    assert!(worker
        .capture()
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    group.retire_captured(worker.capture(), 0, WAIT).unwrap();
}

#[test]
fn output_overflow_invalid_encoding_long_frame_and_incomplete_eof_fail_closed() {
    for mode in [
        "framed-overflow",
        "framed-invalid",
        "framed-long",
        "framed-partial",
    ] {
        let group = WorkerGroup::new().unwrap();
        let mut worker = group
            .spawn_framed(&spec(mode), FrameLimits::default())
            .unwrap();
        assert_eq!(
            worker.recv_frame(WAIT).unwrap_err().kind(),
            ErrorKind::InvalidData,
            "{mode}"
        );
        assert!(worker.write_frame(b"{}", WAIT).is_err());
        assert_eq!(
            worker.write_frame(b"{}", WAIT).unwrap_err().kind(),
            ErrorKind::BrokenPipe
        );
        group.retire_captured(worker.capture(), 0, WAIT).unwrap();
    }
}

#[test]
fn final_ack_is_available_after_root_exit_and_empty_eof_is_explicit() {
    let group = WorkerGroup::new().unwrap();
    let mut worker = group
        .spawn_framed(&spec("framed-echo"), FrameLimits::default())
        .unwrap();
    worker.recv_frame(WAIT).unwrap();
    worker.write_frame(b"shutdown", WAIT).unwrap();
    assert_eq!(
        worker.capture().worker().wait_timeout(WAIT).unwrap(),
        Some(0)
    );
    assert_eq!(worker.recv_frame(WAIT).unwrap(), br#"{"stopped":true}"#);
    assert_eq!(
        worker.recv_frame(WAIT).unwrap_err().kind(),
        ErrorKind::UnexpectedEof
    );
    worker.capture().finish_capture(WAIT).unwrap();
}

#[test]
fn rejected_local_frames_leave_stream_usable_and_receive_wait_is_bounded() {
    let group = WorkerGroup::new().unwrap();
    let mut worker = group
        .spawn_framed(&spec("framed-echo"), FrameLimits::default())
        .unwrap();
    worker.recv_frame(WAIT).unwrap();
    for invalid in [b"".as_slice(), b"{}\n{}", b"{}\r", b"\xff"] {
        assert_eq!(
            worker.write_frame(invalid, WAIT).unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }
    assert_eq!(
        worker
            .write_frame(&vec![b'x'; 65_536], WAIT)
            .unwrap_err()
            .kind(),
        ErrorKind::InvalidInput
    );
    assert_eq!(
        worker
            .recv_frame(Duration::from_millis(40))
            .unwrap_err()
            .kind(),
        ErrorKind::TimedOut
    );
    worker.write_frame(b"{}", WAIT).unwrap();
    assert_eq!(worker.recv_frame(WAIT).unwrap(), b"{}");
    group.retire_captured(worker.capture(), 0, WAIT).unwrap();
}
