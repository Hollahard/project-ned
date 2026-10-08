#![cfg(windows)]
use hermes_catalog_host::{CatalogState, FilePin, LaunchConfig, SOURCE_FILES};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};
static NEXT: AtomicUsize = AtomicUsize::new(0);
fn hash(path: &Path) -> String {
    format!("{:x}", Sha256::digest(std::fs::read(path).unwrap()))
}
fn python() -> PathBuf {
    std::env::var_os("HERMES_CATALOG_PYTHON")
        .map(PathBuf::from)
        .expect("Set HERMES_CATALOG_PYTHON to a base Python executable")
        .canonicalize()
        .unwrap()
}
struct Fixture {
    dir: PathBuf,
    model: PathBuf,
    config: LaunchConfig,
    path: PathBuf,
}
impl Fixture {
    fn new(peer: Option<&str>) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let dir = std::env::var_os("HERMES_CATALOG_TEST_ROOT")
            .map(PathBuf::from)
            .expect("Set HERMES_CATALOG_TEST_ROOT to an owned output root")
            .join(format!(
                "catalog-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
        std::fs::create_dir_all(&dir).unwrap();
        for folder in ["cwd", "worker", "models", "source/hermes_model_catalog"] {
            std::fs::create_dir_all(dir.join(folder)).unwrap();
        }
        let source = dir.join("source");
        let original = root.join("../model-catalog/src/hermes_model_catalog");
        for name in SOURCE_FILES {
            std::fs::copy(
                original.join(name),
                source.join("hermes_model_catalog").join(name),
            )
            .unwrap();
        }
        let bootstrap = dir.join("worker/bootstrap.py");
        if let Some(peer) = peer {
            std::fs::write(&bootstrap, peer).unwrap();
        } else {
            std::fs::copy(root.join("bootstrap.py"), &bootstrap).unwrap();
        }
        let model = dir.join("models/model");
        std::fs::create_dir(&model).unwrap();
        std::fs::write(model.join("config.json"),br#"{"architectures":["LlamaForCausalLM"],"model_type":"llama","quantization_config":{"quant_method":"exl3","bits":5}}"#).unwrap();
        let header = br#"{"layer.trellis":{"dtype":"I16","shape":[2],"data_offsets":[0,4]}}"#;
        let mut weights = (header.len() as u64).to_le_bytes().to_vec();
        weights.extend(header);
        weights.extend([0u8; 4]);
        std::fs::write(model.join("model.safetensors"), weights).unwrap();
        let python = python();
        let config = LaunchConfig {
            schema_version: 1,
            python: FilePin {
                sha256: hash(&python),
                path: python,
            },
            bootstrap: FilePin {
                sha256: hash(&bootstrap),
                path: bootstrap,
            },
            catalog_src: source.clone(),
            working_directory: dir.join("cwd"),
            root_grants: vec![dir.join("models")],
            sources: SOURCE_FILES
                .iter()
                .map(|name| {
                    (
                        name.to_string(),
                        hash(&source.join("hermes_model_catalog").join(name)),
                    )
                })
                .collect::<BTreeMap<_, _>>(),
            work_timeout_ms: 3000,
            cleanup_timeout_ms: 2000,
        };
        let path = dir.join("config.json");
        let fixture = Self {
            dir,
            model,
            config,
            path,
        };
        fixture.save();
        fixture
    }
    fn save(&self) {
        std::fs::write(&self.path, serde_json::to_vec(&self.config).unwrap()).unwrap();
    }
    fn state(&self) -> CatalogState {
        CatalogState::from_config(&self.path).unwrap()
    }
    fn inspect(
        &self,
        state: &CatalogState,
    ) -> Result<serde_json::Value, hermes_catalog_host::CatalogError> {
        state.try_admit(self.model.to_str().unwrap())?.inspect()
    }
}
#[test]
fn real_inspection_is_header_only_and_each_request_is_fresh() {
    let f = Fixture::new(None);
    let state = f.state();
    let first = f.inspect(&state).unwrap();
    assert_eq!(first["status"], "metadata_inspected");
    assert_eq!(first["format"], "EXL3");
    assert_eq!(first["observed_tensor_count"], 1);
    assert_eq!(first["weight_payload_bytes_read"], 0);
    assert_eq!(first["load_certified"], false);
    assert!(first["runtime_compatible"].is_null());
    std::fs::write(
        f.model.join("tokenizer_config.json"),
        br#"{"chat_template":"synthetic"}"#,
    )
    .unwrap();
    let second = f.inspect(&state).unwrap();
    assert_ne!(
        first["metadata_fingerprint"],
        second["metadata_fingerprint"]
    );
    let cleanup = state.retire(Duration::from_secs(2)).unwrap().unwrap();
    assert!(cleanup.verified && cleanup.job_empty && cleanup.stdout_eof && cleanup.stderr_eof);
    assert_eq!(cleanup.root_exit_code, 0);
    assert_eq!(f.inspect(&state).unwrap_err().code, "CATALOG_RETIRED");
}
#[test]
fn missing_shard_is_successful_incomplete_evidence() {
    let f = Fixture::new(None);
    std::fs::remove_file(f.model.join("model.safetensors")).unwrap();
    std::fs::write(
        f.model.join("model.safetensors.index.json"),
        br#"{"weight_map":{"layer.trellis":"model-00001-of-00001.safetensors"}}"#,
    )
    .unwrap();
    let state = f.state();
    let report = f.inspect(&state).unwrap();
    assert_eq!(report["status"], "incomplete");
    assert_eq!(
        report["missing_shards"][0],
        "model-00001-of-00001.safetensors"
    );
    assert!(
        state
            .retire(Duration::from_secs(2))
            .unwrap()
            .unwrap()
            .verified
    );
}
#[test]
fn admission_is_bounded_and_queued_close_prevents_launch() {
    let f = Fixture::new(None);
    let state = f.state();
    let permit = state.try_admit(f.model.to_str().unwrap()).unwrap();
    assert_eq!(
        state
            .try_admit(f.model.to_str().unwrap())
            .err()
            .unwrap()
            .code,
        "CATALOG_BUSY"
    );
    let now = Instant::now();
    assert!(state.retire(Duration::from_millis(100)).unwrap().is_none());
    assert!(now.elapsed() < Duration::from_millis(500));
    assert_eq!(permit.inspect().unwrap_err().code, "CATALOG_RETIRED");
}
#[test]
fn cancelled_queued_permit_releases_admission() {
    let f = Fixture::new(None);
    let state = f.state();
    drop(state.try_admit(f.model.to_str().unwrap()).unwrap());
    assert!(f.inspect(&state).is_ok());
    state.retire(Duration::from_secs(2)).unwrap();
}
#[test]
fn unconfigured_and_outside_grant_are_static_failures() {
    assert_eq!(
        CatalogState::default()
            .try_admit("C:\\missing")
            .err()
            .unwrap()
            .code,
        "CATALOG_UNAVAILABLE"
    );
    let f = Fixture::new(None);
    let state = f.state();
    for path in [f.dir.join("not-authorized/missing"), f.model.join("nested")] {
        let error = state
            .try_admit(path.to_str().unwrap())
            .unwrap()
            .inspect()
            .unwrap_err();
        assert_eq!(error.code, "CATALOG_OUTSIDE_GRANT");
        assert!(!error.to_string().contains("not-authorized"));
    }
    assert!(f.inspect(&state).is_ok());
    state.retire(Duration::from_secs(2)).unwrap();
}
#[test]
fn receipt_change_after_startup_is_denied_before_launch() {
    let f = Fixture::new(None);
    let state = f.state();
    std::fs::write(
        f.config.catalog_src.join("hermes_model_catalog/common.py"),
        "raise RuntimeError('canary')",
    )
    .unwrap();
    assert_eq!(
        f.inspect(&state).unwrap_err().code,
        "CATALOG_CONFIG_INVALID"
    );
    assert!(state.retire(Duration::from_secs(1)).unwrap().is_none());
}
#[test]
fn malformed_oversized_and_early_exit_peers_get_verified_cleanup() {
    for peer in [
        "print('{}',flush=True)",
        "print('x'*70000,flush=True)",
        "raise SystemExit(3)",
        "import sys;sys.stdout.write('{');sys.stdout.flush()",
    ] {
        let f = Fixture::new(Some(peer));
        let state = f.state();
        let error = f.inspect(&state).unwrap_err();
        assert!(["CATALOG_PROTOCOL_FAILED", "CATALOG_TRANSPORT_FAILED"].contains(&error.code));
        assert!(!error.to_string().contains("canary"));
        assert!(
            state
                .retire(Duration::from_secs(2))
                .unwrap()
                .unwrap()
                .verified
        );
    }
}
#[test]
fn deadline_kills_owned_descendant_but_unrelated_process_survives() {
    let outsider_child = std::process::Command::new(python())
        .args(["-I", "-S", "-B", "-c", "import time;time.sleep(60)"])
        .spawn()
        .unwrap();
    let mut outsider = ChildGuard(outsider_child);
    let mut f=Fixture::new(Some("import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)'])\ntime.sleep(60)"));
    f.config.work_timeout_ms = 150;
    f.save();
    let state = f.state();
    let started = Instant::now();
    assert_eq!(
        f.inspect(&state).unwrap_err().code,
        "CATALOG_TRANSPORT_FAILED"
    );
    assert!(started.elapsed() < Duration::from_secs(4));
    assert!(
        state
            .retire(Duration::from_secs(2))
            .unwrap()
            .unwrap()
            .job_empty
    );
    assert!(outsider.0.try_wait().unwrap().is_none());
}
#[test]
fn close_during_inspection_fences_returned_success() {
    let mut f = Fixture::new(None);
    let marker = f.dir.join("peer-running.txt");
    let peer = format!(
        "from pathlib import Path\nimport time\nPath({}).write_text('running')\ntime.sleep(60)",
        serde_json::to_string(marker.to_str().unwrap()).unwrap()
    );
    std::fs::write(&f.config.bootstrap.path, peer).unwrap();
    f.config.bootstrap.sha256 = hash(&f.config.bootstrap.path);
    f.save();
    let state = f.state();
    let permit = state.try_admit(f.model.to_str().unwrap()).unwrap();
    let running = std::thread::spawn(move || permit.inspect());
    let deadline = Instant::now() + Duration::from_secs(2);
    while !marker.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(2));
    }
    let observed = marker.exists();
    let cleanup = state.retire(Duration::from_secs(2)).unwrap();
    assert!(observed);
    assert!(cleanup.is_some_and(|c| c.verified));
    assert_eq!(running.join().unwrap().unwrap_err().code, "CATALOG_RETIRED");
}

#[test]
fn leading_dash_folder_uses_unambiguous_argv() {
    let mut f = Fixture::new(None);
    let renamed = f.dir.join("models/--help");
    std::fs::rename(&f.model, &renamed).unwrap();
    f.model = renamed;
    let state = f.state();
    assert_eq!(f.inspect(&state).unwrap()["model"], "--help");
    state.retire(Duration::from_secs(2)).unwrap();
}

#[test]
fn delayed_complete_or_partial_tail_after_valid_report_is_rejected() {
    let original = Fixture::new(None);
    let original_state = original.state();
    let report = original.inspect(&original_state).unwrap();
    original_state.retire(Duration::from_secs(1)).unwrap();
    let encoded = serde_json::to_string(&serde_json::to_string(&report).unwrap()).unwrap();
    for tail in ["{}\n", "{"] {
        let peer=format!("import sys,time\nsys.stdout.buffer.write(({encoded}+'\\n').encode());sys.stdout.buffer.flush()\ntime.sleep(0.03)\nsys.stdout.write({});sys.stdout.flush()",serde_json::to_string(tail).unwrap());
        let f = Fixture::new(Some(&peer));
        let state = f.state();
        assert_eq!(
            f.inspect(&state).unwrap_err().code,
            "CATALOG_PROTOCOL_FAILED"
        );
        assert!(
            state
                .retire(Duration::from_secs(2))
                .unwrap()
                .unwrap()
                .verified
        );
    }
}
#[test]
fn valid_report_with_descendant_retaining_pipe_cannot_report_success() {
    let original = Fixture::new(None);
    let original_state = original.state();
    let report = original.inspect(&original_state).unwrap();
    original_state.retire(Duration::from_secs(1)).unwrap();
    let encoded = serde_json::to_string(&serde_json::to_string(&report).unwrap()).unwrap();
    let peer=format!("import sys,subprocess\nsubprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)'])\nsys.stdout.buffer.write(({encoded}+'\\n').encode());sys.stdout.buffer.flush()");
    let mut f = Fixture::new(Some(&peer));
    f.config.work_timeout_ms = 150;
    f.save();
    let state = f.state();
    assert_eq!(
        f.inspect(&state).unwrap_err().code,
        "CATALOG_TRANSPORT_FAILED"
    );
    assert!(
        state
            .retire(Duration::from_secs(2))
            .unwrap()
            .unwrap()
            .job_empty
    );
}
#[test]
fn malformed_manifest_cannot_add_sources_roots_or_unknown_fields() {
    let mut f = Fixture::new(None);
    f.config.sources.insert("engine.py".into(), "0".repeat(64));
    f.save();
    assert!(CatalogState::from_config(&f.path).is_err());
    f.config.sources.remove("engine.py");
    f.config.root_grants = vec![f.dir.join("models"); 9];
    f.save();
    assert!(CatalogState::from_config(&f.path).is_err());
    std::fs::write(&f.path, b"{\"schema_version\":1,\"schema_version\":1}").unwrap();
    assert!(CatalogState::from_config(&f.path).is_err());
}

struct ChildGuard(std::process::Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
