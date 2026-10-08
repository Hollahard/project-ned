#![cfg(all(windows, feature = "test-fixture"))]
use hermes_control_host::{ControlHost, FilePin, LaunchConfig, SOURCE_FILES};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

static UNIQUE: AtomicU64 = AtomicU64::new(0);
struct Scratch {
    root: PathBuf,
    state: PathBuf,
    config: PathBuf,
}
impl Scratch {
    fn new(mode: &str) -> Self {
        let unique = format!(
            "{}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            UNIQUE.fetch_add(1, Ordering::Relaxed)
        );
        let root = std::env::temp_dir().join(format!("hermes-control-{unique}"));
        std::fs::create_dir(&root).unwrap();
        let state = root.join(format!("{mode}-{unique}"));
        std::fs::create_dir(&state).unwrap();
        Self {
            config: root.join("launch.json"),
            root,
            state,
        }
    }
    fn prepare(&self, fixture: bool) -> LaunchConfig {
        let python = if fixture {
            PathBuf::from(env!("CARGO_BIN_EXE_control-peer-fixture"))
        } else {
            env_path("HERMES_CONTROL_PYTHON")
        };
        let worker = env_path("HERMES_CONTROL_WORKER_ROOT");
        let inference = env_path("HERMES_CONTROL_INFERENCE_SRC");
        let mut sources = BTreeMap::new();
        for name in SOURCE_FILES {
            let (package, file) = name.split_once('/').unwrap();
            let path = if package == "worker" {
                worker.join("src/hermes_control_worker").join(file)
            } else {
                inference.join("hermes_inference").join(file)
            };
            sources.insert((*name).to_owned(), hash(&path));
        }
        LaunchConfig {
            schema_version: 1,
            python: pin(&python),
            bootstrap: pin(&worker.join("bootstrap.py")),
            inference_src: inference.canonicalize().unwrap(),
            state_dir: self.state.canonicalize().unwrap(),
            sources,
            startup_timeout_ms: 5000,
            request_timeout_ms: if fixture { 150 } else { 5000 },
            shutdown_timeout_ms: 2000,
        }
    }
    fn write(&self, config: &LaunchConfig) {
        std::fs::write(&self.config, serde_json::to_vec(config).unwrap()).unwrap();
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        for name in [
            "profiles.sqlite3",
            "profiles.sqlite3-journal",
            ".worker.lock",
            "unexpected.txt",
        ] {
            let _ = std::fs::remove_file(self.state.join(name));
        }
        let _ = std::fs::remove_file(&self.config);
        let _ = std::fs::remove_dir(&self.state);
        for name in [
            "profiles.sqlite3",
            "profiles.sqlite3-journal",
            ".worker.lock",
        ] {
            let _ = std::fs::remove_file(self.root.join("prepared-state").join(name));
        }
        let _ = std::fs::remove_dir(self.root.join("prepared-state"));
        let _ = std::fs::remove_file(self.root.join("prepared.json"));
        let _ = std::fs::remove_dir(&self.root);
    }
}
fn env_path(name: &str) -> PathBuf {
    PathBuf::from(
        std::env::var_os(name)
            .unwrap_or_else(|| panic!("{name} is required for owned CPU worker tests")),
    )
}
fn hash(path: &Path) -> String {
    format!("{:x}", Sha256::digest(std::fs::read(path).unwrap()))
}
fn pin(path: &Path) -> FilePin {
    FilePin {
        path: path.canonicalize().unwrap(),
        sha256: hash(path),
    }
}
fn profile() -> serde_json::Value {
    json!({"artifact_id":"fixture","revision":"fixture-revision","model_name":"fixture-model","expected_model_path":"C:/models/fixture-model","context_length":2048,"cache_size":2048,"cache_mode":"q4","chunk_size":256})
}

#[test]
fn real_worker_validates_normalizes_persists_and_shuts_down_cleanly() {
    let scratch = Scratch::new("actual");
    let config = scratch.prepare(false);
    scratch.write(&config);
    let mut host = ControlHost::from_config(&scratch.config).unwrap();
    assert_eq!(
        host.request("runtime.status", json!({})).unwrap()["runtime_attached"],
        false
    );
    assert_eq!(
        host.request("profiles.schema", json!({})).unwrap()["fields"]
            .as_array()
            .unwrap()
            .len(),
        10
    );
    let validated = host
        .request("profiles.validate", json!({"profile":profile()}))
        .unwrap();
    assert_eq!(validated["profile"]["cache_mode"], "4,4");
    assert_eq!(validated["artifact_verified"], false);
    let saved = host.request("profiles.save", json!({"profile_id":"fixture","name":"Fixture profile","expected_revision":null,"profile":profile()})).unwrap();
    let revision = saved["revision"].as_i64().unwrap();
    let conflict = host.request("profiles.save", json!({"profile_id":"fixture","name":"Conflicting profile","expected_revision":null,"profile":profile()})).unwrap_err();
    assert_eq!(conflict.code, "REVISION_CONFLICT");
    assert!(!conflict.retired);
    assert!(!host.is_retired());
    assert_eq!(
        host.request("profiles.list", json!({})).unwrap()["profiles"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let report = host.retire().unwrap();
    assert!(report.cooperative && report.job_empty && report.stdout_eof && report.stderr_eof);
    assert_eq!(report.root_exit_code, 0);
    let mut reopened = ControlHost::from_config(&scratch.config).unwrap();
    assert_eq!(
        reopened
            .request("profiles.get", json!({"profile_id":"fixture"}))
            .unwrap()["profile"]["cache_mode"],
        "4,4"
    );
    assert_eq!(
        reopened
            .request(
                "profiles.delete",
                json!({"profile_id":"fixture","expected_revision":revision})
            )
            .unwrap()["deleted"],
        true
    );
    assert!(
        reopened.request("profiles.list", json!({})).unwrap()["profiles"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    reopened.retire().unwrap();
}

#[test]
fn renderer_validation_and_application_failure_keep_healthy_worker_usable() {
    let scratch = Scratch::new("actual-validation");
    scratch.write(&scratch.prepare(false));
    let mut host = ControlHost::from_config(&scratch.config).unwrap();
    for method in ["service.describe", "service.shutdown", "model.load"] {
        assert_eq!(
            host.request(method, json!({})).unwrap_err().code,
            "CONTROL_UNAVAILABLE"
        );
    }
    assert_eq!(
        host.request("runtime.status", json!({"api_key":"not forwarded"}))
            .unwrap_err()
            .code,
        "CONTROL_INVALID_REQUEST"
    );
    let mut invalid = profile();
    invalid["cache_size"] = json!(257);
    assert_eq!(
        host.request("profiles.validate", json!({"profile":invalid}))
            .unwrap_err()
            .code,
        "INVALID_PROFILE"
    );
    assert!(!host.is_retired());
    host.request("runtime.status", json!({})).unwrap();
    host.retire().unwrap();
}

#[test]
fn pinned_file_unknown_manifest_field_and_state_tampering_reject_before_launch() {
    let scratch = Scratch::new("invalid");
    let mut config = scratch.prepare(false);
    config.python.sha256 = "0".repeat(64);
    scratch.write(&config);
    assert_eq!(
        ControlHost::from_config(&scratch.config)
            .err()
            .unwrap()
            .code,
        "CONTROL_CONFIG_INVALID"
    );
    let mut value = serde_json::to_value(scratch.prepare(false)).unwrap();
    value["arguments"] = json!(["untrusted"]);
    std::fs::write(&scratch.config, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(ControlHost::from_config(&scratch.config).is_err());
    scratch.write(&scratch.prepare(false));
    std::fs::write(scratch.state.join("unexpected.txt"), b"preserve").unwrap();
    assert!(ControlHost::from_config(&scratch.config).is_err());
    assert_eq!(
        std::fs::read(scratch.state.join("unexpected.txt")).unwrap(),
        b"preserve"
    );
}

struct Unrelated(Child);
impl Drop for Unrelated {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn corrupted_timeout_and_crashing_peers_retire_without_touching_unrelated_process() {
    let unrelated_state = Scratch::new("unrelated");
    let mut unrelated = Unrelated(
        Command::new(env!("CARGO_BIN_EXE_control-peer-fixture"))
            .current_dir(&unrelated_state.state)
            .env_clear()
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(0x08000000)
            .spawn()
            .unwrap(),
    );
    for mode in [
        "wrong-id",
        "duplicate",
        "unknown",
        "truncated",
        "timeout",
        "crash",
    ] {
        let scratch = Scratch::new(mode);
        scratch.write(&scratch.prepare(true));
        let mut host = ControlHost::from_config(&scratch.config).unwrap();
        let start = Instant::now();
        let error = host.request("runtime.status", json!({})).unwrap_err();
        assert!(error.retired && host.is_retired(), "{mode}");
        assert!(start.elapsed() < Duration::from_secs(5));
        let report = host.cleanup_report().expect("owned cleanup verified");
        assert!(report.job_empty && report.stdout_eof && report.stderr_eof);
        assert_eq!(
            host.request("runtime.status", json!({})).unwrap_err().code,
            "CONTROL_RETIRED"
        );
        assert!(unrelated.0.try_wait().unwrap().is_none());
    }
}

#[test]
fn invalid_hello_is_not_accepted_as_service_readiness() {
    let scratch = Scratch::new("bad-hello");
    scratch.write(&scratch.prepare(true));
    assert!(ControlHost::from_config(&scratch.config).is_err());
}

#[test]
fn preparation_script_builds_usable_pinned_config_and_refuses_overwrite() {
    let scratch = Scratch::new("prepare");
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("scripts/prepare_config.py");
    let python = env_path("HERMES_CONTROL_PYTHON").canonicalize().unwrap();
    let output = scratch.root.join("prepared.json");
    let state = scratch.root.join("prepared-state");
    let run = || {
        Command::new(&python)
            .args(["-I", "-S", "-B"])
            .arg(&script)
            .arg("--python")
            .arg(&python)
            .arg("--worker-root")
            .arg(env_path("HERMES_CONTROL_WORKER_ROOT"))
            .arg("--inference-src")
            .arg(env_path("HERMES_CONTROL_INFERENCE_SRC"))
            .arg("--state-dir")
            .arg(&state)
            .arg("--output")
            .arg(&output)
            .creation_flags(0x08000000)
            .output()
            .unwrap()
    };
    assert!(run().status.success());
    let original = std::fs::read(&output).unwrap();
    assert!(!run().status.success());
    assert_eq!(std::fs::read(&output).unwrap(), original);
    let mut host = ControlHost::from_config(&output).unwrap();
    host.request("runtime.status", json!({})).unwrap();
    host.retire().unwrap();
}

#[test]
fn late_protocol_tail_cannot_be_reported_as_cooperative_shutdown() {
    for mode in ["tail-complete", "tail-partial"] {
        let scratch = Scratch::new(mode);
        scratch.write(&scratch.prepare(true));
        let mut host = ControlHost::from_config(&scratch.config).unwrap();
        let report = host.retire().unwrap();
        assert!(!report.cooperative, "{mode}");
        assert!(report.job_empty && report.stdout_eof && report.stderr_eof);
        assert!(host.is_retired());
    }
}

#[test]
fn second_state_writer_fails_without_retiring_first_owner() {
    let scratch = Scratch::new("state-owner");
    scratch.write(&scratch.prepare(false));
    let mut first = ControlHost::from_config(&scratch.config).unwrap();
    assert!(ControlHost::from_config(&scratch.config).is_err());
    assert!(!first.is_retired());
    first.request("runtime.status", json!({})).unwrap();
    assert!(first.retire().unwrap().cooperative);
}
