#![cfg(all(windows, feature = "test-fixture"))]
use hermes_owned_http::{Limits, Method, OwnedHttpClient};
use hermes_resource_host::{CaptureLimits, CapturedWorker, WorkerGroup, WorkerSpec};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture {
    group: WorkerGroup,
    worker: CapturedWorker,
    port: u16,
    count: PathBuf,
    root: PathBuf,
}
impl Fixture {
    fn new(mode: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "hermes-http-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).unwrap();
        let count = root.join("received-count.txt");
        let group = WorkerGroup::new().unwrap();
        let mut environment = BTreeMap::new();
        for key in ["SystemRoot", "WINDIR"] {
            if let Some(value) = std::env::var_os(key) {
                environment.insert(key.to_owned(), value);
            }
        }
        let worker = group
            .spawn_captured(
                &WorkerSpec {
                    executable: PathBuf::from(env!("CARGO_BIN_EXE_owned-http-fixture")),
                    arguments: vec![mode.into(), count.as_os_str().to_owned()],
                    working_directory: root.clone(),
                    environment,
                },
                CaptureLimits::default(),
            )
            .unwrap();
        let port = worker.wait_ready(Duration::from_secs(5)).unwrap();
        Self {
            group,
            worker,
            port,
            count,
            root,
        }
    }
    fn retire(&self) {
        let report = self
            .group
            .retire_captured(&self.worker, 77, Duration::from_secs(3))
            .unwrap();
        assert_eq!(report.exit_code, 77);
        assert_eq!(self.group.active_count().unwrap(), 0);
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = self
            .group
            .retire_captured(&self.worker, 77, Duration::from_secs(3));
        let _ = std::fs::remove_file(&self.count);
        let _ = std::fs::remove_dir(&self.root);
    }
}

#[test]
fn owned_root_and_descendant_all_supported_framings() {
    for mode in ["good", "descendant", "chunked", "close"] {
        let fixture = Fixture::new(mode);
        assert!(fixture
            .group
            .contains_observed_pid(fixture.worker.id())
            .unwrap());
        assert!(!fixture
            .group
            .contains_observed_pid(std::process::id())
            .unwrap());
        assert!(!fixture.group.contains_observed_pid(0).unwrap());
        let client = OwnedHttpClient::new(&fixture.group, fixture.port, Limits::default()).unwrap();
        let response = client
            .request(
                Method::Get,
                "/api/config",
                &[("X-Hermes-Session-Token", "own-canary")],
                None,
            )
            .unwrap();
        assert_eq!(response.status_code(), 200);
        assert_eq!(response.body(), br#"{"ok":true}"#);
        fixture.retire();
        assert!(!fixture
            .group
            .contains_observed_pid(fixture.worker.id())
            .unwrap());
    }
}

#[test]
fn unrelated_established_listener_receives_no_http_bytes_and_survives() {
    let own = Fixture::new("good");
    let other = Fixture::new("good");
    let client = OwnedHttpClient::new(&own.group, other.port, Limits::default()).unwrap();
    let error = client
        .request(
            Method::Get,
            "/api/config",
            &[("X-Hermes-Session-Token", "must-never-transmit-canary")],
            None,
        )
        .err()
        .unwrap();
    assert_eq!(error.code(), "HTTP_OWNER_DENIED");
    let deadline = Instant::now() + Duration::from_secs(2);
    while !other.count.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(std::fs::read_to_string(&other.count).unwrap(), "0");
    own.retire();
    assert!(other
        .worker
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    let response = OwnedHttpClient::new(&other.group, other.port, Limits::default())
        .unwrap()
        .request(Method::Get, "/api/config", &[], None)
        .unwrap();
    assert_eq!(response.status_code(), 200);
}

#[test]
fn malformed_oversized_ambiguous_redirect_truncated_and_extra_responses_fail_closed() {
    for (mode, code) in [
        ("malformed", "HTTP_MALFORMED"),
        ("oversize", "HTTP_BODY_LIMIT"),
        ("dupe", "HTTP_DUPLICATE_HEADER"),
        ("redirect", "HTTP_REDIRECT_DENIED"),
        ("truncated", "HTTP_TRUNCATED"),
        ("trailing", "HTTP_TRAILING_BYTES"),
        ("tecl", "HTTP_AMBIGUOUS_FRAMING"),
        ("trailer", "HTTP_HEADER_LIMIT"),
        ("hugeheaders", "HTTP_HEADER_LIMIT"),
        ("chunkoversize", "HTTP_BODY_LIMIT"),
        ("closeoversize", "HTTP_BODY_LIMIT"),
    ] {
        let fixture = Fixture::new(mode);
        let client = OwnedHttpClient::new(&fixture.group, fixture.port, Limits::default()).unwrap();
        let error = client
            .request(Method::Get, "/api/config", &[], None)
            .err()
            .unwrap();
        assert_eq!(error.code(), code, "mode {mode}");
        fixture.retire();
    }
}

#[test]
fn slow_trickle_cannot_extend_absolute_deadline() {
    for mode in ["slow", "holdclose"] {
        let fixture = Fixture::new(mode);
        let limits = Limits {
            timeout: Duration::from_millis(180),
            ..Limits::default()
        };
        let client = OwnedHttpClient::new(&fixture.group, fixture.port, limits).unwrap();
        let start = Instant::now();
        assert!(client
            .request(Method::Get, "/api/config", &[], None)
            .is_err());
        assert!(start.elapsed() < Duration::from_secs(2));
        fixture.retire();
    }
}

#[test]
fn allowed_post_duplicate_auth_and_local_validation_preserve_contract() {
    let fixture = Fixture::new("good");
    let client = OwnedHttpClient::new(&fixture.group, fixture.port, Limits::default()).unwrap();
    assert!(client
        .request(Method::Get, "http://example.com", &[], None)
        .is_err());
    assert!(!fixture.count.exists());
    let response = client
        .request(
            Method::Post,
            "/api/config",
            &[
                ("X-Hermes-Session-Token", "first"),
                ("X-Hermes-Session-Token", "second"),
            ],
            Some(b"{}"),
        )
        .unwrap();
    assert_eq!(response.status_code(), 200);
    fixture.retire();
}
