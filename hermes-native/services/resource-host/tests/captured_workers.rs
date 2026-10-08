#![cfg(all(windows, feature = "test-fixture"))]

use hermes_resource_host::{CaptureLimits, WorkerGroup, WorkerSpec};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::mem::size_of;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::ptr::{null, null_mut};
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Threading::{CreateEventW, WaitForSingleObject};

const WAIT: Duration = Duration::from_secs(10);

fn spec(mode: &str) -> WorkerSpec {
    WorkerSpec {
        executable: PathBuf::from(env!("CARGO_BIN_EXE_worker-fixture")),
        arguments: vec![mode.into()],
        working_directory: std::env::temp_dir(),
        environment: BTreeMap::new(),
    }
}
struct Unrelated(Child);
impl Drop for Unrelated {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn closed_stdin_ready_and_group_retirement_have_verified_eof() {
    let group = WorkerGroup::new().unwrap();
    let worker = group
        .spawn_captured(&spec("ready"), CaptureLimits::default())
        .unwrap();
    assert!(group.contains(worker.worker()).unwrap());
    assert_eq!(worker.wait_ready(WAIT).unwrap(), 31415);
    let report = group.retire_captured(&worker, 27, WAIT).unwrap();
    assert_eq!(report.exit_code, 27);
    assert_eq!(group.active_count().unwrap(), 0);
    let output = worker.output_snapshot().unwrap();
    assert!(output.stdout_eof && output.stderr_eof);
    assert!(output.stdout_tail.is_empty() && output.stderr_tail.is_empty());
    assert!(group
        .spawn_captured(&spec("ready"), CaptureLimits::default())
        .is_err());
}

#[test]
fn exact_handle_list_excludes_unrelated_inheritable_event() {
    let security = SECURITY_ATTRIBUTES {
        nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: null_mut(),
        bInheritHandle: 1,
    };
    let raw = unsafe { CreateEventW(&security, 1, 0, null()) };
    assert!(!raw.is_null());
    let event = unsafe { OwnedHandle::from_raw_handle(raw) };
    let group = WorkerGroup::new().unwrap();
    let mut input = spec("inheritance");
    input
        .arguments
        .push(OsString::from((event.as_raw_handle() as usize).to_string()));
    let limits = CaptureLimits {
        tail_bytes_per_stream: 256,
        ..Default::default()
    };
    let worker = group.spawn_captured(&input, limits).unwrap();
    assert_eq!(worker.wait_ready(WAIT).unwrap(), 31415);
    assert_eq!(
        unsafe { WaitForSingleObject(event.as_raw_handle(), 0) },
        WAIT_TIMEOUT
    );
    assert!(worker
        .output_snapshot()
        .unwrap()
        .stdout_tail
        .starts_with(b"inherited=false\n"));
    group.retire_captured(&worker, 0, WAIT).unwrap();
}

#[test]
fn stderr_flood_is_drained_and_retained_memory_is_bounded() {
    let group = WorkerGroup::new().unwrap();
    let worker = group
        .spawn_captured(
            &spec("stderr-flood"),
            CaptureLimits {
                tail_bytes_per_stream: 97,
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(worker.wait_ready(WAIT).unwrap(), 31415);
    let report = group.retire_captured(&worker, 0, WAIT).unwrap();
    assert_eq!(report.stderr_bytes, 4 * 1024 * 1024);
    let output = worker.output_snapshot().unwrap();
    assert_eq!(output.stderr_tail, vec![b'x'; 97]);
    assert!(output.stdout_tail.len() <= 97);
}

#[test]
fn malformed_conflicting_long_and_early_exit_outputs_fail_boundedly() {
    for mode in ["malformed", "conflict", "long-line", "early-exit"] {
        let group = WorkerGroup::new().unwrap();
        let worker = group
            .spawn_captured(&spec(mode), CaptureLimits::default())
            .unwrap();
        let start = Instant::now();
        let error = worker.wait_ready(WAIT).unwrap_err();
        assert!(
            matches!(
                error.kind(),
                std::io::ErrorKind::InvalidData | std::io::ErrorKind::UnexpectedEof
            ),
            "{mode}: {error}"
        );
        assert!(start.elapsed() < WAIT);
        group.retire_captured(&worker, 0, WAIT).unwrap();
    }
}

#[test]
fn readiness_deadline_does_not_claim_or_kill_unrelated_worker() {
    let group = WorkerGroup::new().unwrap();
    let input = spec("sleep");
    let mut unrelated = Unrelated(
        Command::new(&input.executable)
            .arg("sleep")
            .creation_flags(0x08000000)
            .spawn()
            .unwrap(),
    );
    let worker = group
        .spawn_captured(&input, CaptureLimits::default())
        .unwrap();
    assert_eq!(
        worker
            .wait_ready(Duration::from_millis(40))
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::TimedOut
    );
    assert!(worker
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    group.retire_captured(&worker, 0, WAIT).unwrap();
    assert!(unrelated.0.try_wait().unwrap().is_none());
}

#[test]
fn descendant_held_pipe_requires_owned_tree_cleanup() {
    let group = WorkerGroup::new().unwrap();
    let mut input = spec("descendant-output");
    let path = std::env::temp_dir().join(format!(
        "hermes-captured-descendant-{}.txt",
        std::process::id()
    ));
    input.arguments.push(path.clone().into_os_string());
    let worker = group
        .spawn_captured(&input, CaptureLimits::default())
        .unwrap();
    assert_eq!(worker.worker().wait_timeout(WAIT).unwrap(), Some(0));
    assert_eq!(
        worker
            .finish_capture(Duration::from_millis(40))
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::TimedOut
    );
    assert!(group.active_count().unwrap() >= 1);
    group.retire_captured(&worker, 0, WAIT).unwrap();
    assert_eq!(group.active_count().unwrap(), 0);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn wrong_group_cannot_retire_capture_owner() {
    let owner = WorkerGroup::new().unwrap();
    let other = WorkerGroup::new().unwrap();
    let worker = owner
        .spawn_captured(&spec("ready"), CaptureLimits::default())
        .unwrap();
    worker.wait_ready(WAIT).unwrap();
    assert_eq!(
        other.retire_captured(&worker, 0, WAIT).unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied
    );
    assert!(worker
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    owner.retire_captured(&worker, 0, WAIT).unwrap();
}
