#![cfg(all(windows, feature = "test-fixture"))]

use hermes_resource_host::{WorkerGroup, WorkerSpec};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::System::Threading::{
    OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE,
};

const WAIT: Duration = Duration::from_secs(5);

struct Scratch(PathBuf);
impl Scratch {
    fn new() -> Self {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hermes-owned-worker-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        Self(root)
    }
    fn file(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        // Only this fixture's known flat output files are removed, no recursion.
        for name in ["dump.json", "pid.txt"] {
            let _ = std::fs::remove_file(self.file(name));
        }
        let _ = std::fs::remove_dir(&self.0);
    }
}

struct ChildGuard(Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn spec(directory: &Path, args: &[OsString]) -> WorkerSpec {
    WorkerSpec {
        executable: PathBuf::from(env!("CARGO_BIN_EXE_worker-fixture")),
        arguments: args.to_vec(),
        working_directory: directory.to_path_buf(),
        environment: BTreeMap::new(),
    }
}

fn wait_for_file(path: &Path) -> String {
    let deadline = Instant::now() + WAIT;
    loop {
        if let Ok(content) = std::fs::read_to_string(path) {
            if !content.is_empty() {
                return content;
            }
        }
        assert!(Instant::now() < deadline, "fixture output did not arrive");
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn child_receives_literal_unicode_arguments_and_only_explicit_environment() {
    let scratch = Scratch::new();
    let group = WorkerGroup::new().unwrap();
    let values = [
        "",
        "two words",
        "quote\"inside",
        "C:\\trailing slash\\",
        "雪😀",
        "$() & ; `literal`",
        "\\\"\\",
    ];
    let mut args = vec![
        OsString::from("dump"),
        scratch.file("dump.json").into_os_string(),
    ];
    args.extend(values.iter().map(OsString::from));
    let mut input = spec(&scratch.0, &args);
    input
        .environment
        .insert("HERMES_TEST_VALUE".into(), "雪 spaced value".into());
    let child = group.spawn(&input).unwrap();
    assert!(group.contains(&child).unwrap());
    assert_eq!(child.wait_timeout(WAIT).unwrap(), Some(0));
    let payload: serde_json::Value =
        serde_json::from_str(&wait_for_file(&scratch.file("dump.json"))).unwrap();
    assert_eq!(payload["arguments"], serde_json::json!(values));
    assert_eq!(payload["allowed_value"], "雪 spaced value");
    let keys: Vec<_> = payload["environment_keys"]
        .as_array()
        .unwrap()
        .iter()
        .map(|key| key.as_str().unwrap().to_ascii_uppercase())
        .collect();
    // The test parent has an active virtualenv. Its environment and credentials
    // must not be inherited just because the worker supplies some overrides.
    assert!(!keys.iter().any(
        |key| ["VIRTUAL_ENV", "PATH", "OPENAI_API_KEY", "TABBY_API_KEY"].contains(&key.as_str())
    ));
    assert_eq!(
        PathBuf::from(payload["directory"].as_str().unwrap())
            .canonicalize()
            .unwrap(),
        scratch.0.canonicalize().unwrap()
    );
}

#[test]
fn terminating_inference_group_preserves_other_group_and_unrelated_fixture() {
    let scratch = Scratch::new();
    let inference = WorkerGroup::new().unwrap();
    let gateway = WorkerGroup::new().unwrap();
    let input = spec(&scratch.0, &["sleep".into()]);
    let inference_child = inference.spawn(&input).unwrap();
    let gateway_child = gateway.spawn(&input).unwrap();
    let mut unrelated = ChildGuard(
        Command::new(&input.executable)
            .arg("sleep")
            .creation_flags(0x08000000)
            .spawn()
            .unwrap(),
    );
    assert!(!inference.contains(&gateway_child).unwrap());
    inference.terminate(23).unwrap();
    assert_eq!(inference_child.wait_timeout(WAIT).unwrap(), Some(23));
    assert_eq!(gateway_child.wait_timeout(Duration::ZERO).unwrap(), None);
    assert!(unrelated.0.try_wait().unwrap().is_none());
    gateway.terminate(24).unwrap();
    assert_eq!(gateway_child.wait_timeout(WAIT).unwrap(), Some(24));
}

#[test]
fn dropping_last_job_handle_kills_worker_and_its_descendant() {
    let scratch = Scratch::new();
    let group = WorkerGroup::new().unwrap();
    let input = spec(
        &scratch.0,
        &[
            "descendant".into(),
            scratch.file("pid.txt").into_os_string(),
        ],
    );
    let worker = group.spawn(&input).unwrap();
    let descendant: u32 = wait_for_file(&scratch.file("pid.txt")).parse().unwrap();
    // Observation only: never terminate a process reopened by PID.
    let raw = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, descendant) };
    assert!(!raw.is_null());
    let descendant_handle = unsafe { OwnedHandle::from_raw_handle(raw) };
    // Windows may create additional console/runtime helpers in the same job.
    assert!(group.active_count().unwrap() >= 2);
    drop(group);
    assert!(worker.wait_timeout(WAIT).unwrap().is_some());
    assert_eq!(
        unsafe { WaitForSingleObject(descendant_handle.as_raw_handle(), 5_000) },
        WAIT_OBJECT_0
    );
}

#[test]
fn abrupt_owner_exit_closes_job_and_terminates_its_worker() {
    let scratch = Scratch::new();
    let executable = PathBuf::from(env!("CARGO_BIN_EXE_worker-fixture"));
    let mut owner = ChildGuard(
        Command::new(&executable)
            .args([
                OsString::from("own"),
                scratch.file("pid.txt").into_os_string(),
            ])
            .creation_flags(0x08000000)
            .spawn()
            .unwrap(),
    );
    let pid: u32 = wait_for_file(&scratch.file("pid.txt")).parse().unwrap();
    let raw = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, pid) };
    assert!(!raw.is_null());
    let worker = unsafe { OwnedHandle::from_raw_handle(raw) };
    owner.0.kill().unwrap();
    owner.0.wait().unwrap();
    assert_eq!(
        unsafe { WaitForSingleObject(worker.as_raw_handle(), 5_000) },
        WAIT_OBJECT_0
    );
}

#[test]
fn invalid_inputs_fail_before_worker_starts() {
    let scratch = Scratch::new();
    let group = WorkerGroup::new().unwrap();
    let mut input = spec(&scratch.0, &["sleep".into()]);
    input.arguments.push("nul\0argument".into());
    assert!(group.spawn(&input).is_err());
    input.arguments.clear();
    input.executable = "relative.exe".into();
    assert!(group.spawn(&input).is_err());
    assert_eq!(group.active_count().unwrap(), 0);
}
