#![cfg(all(windows, feature = "test-fixture"))]
use hermes_owned_ws::{Event, Limits, OwnedWebSocket};
use hermes_resource_host::{CaptureLimits, CapturedWorker, WorkerGroup, WorkerSpec};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Mutex, Once};
use std::time::{Duration, Instant};
const TOKEN: &str = "synthetic-token-canary-41";
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Fixture {
    group: WorkerGroup,
    worker: CapturedWorker,
    port: u16,
    count: PathBuf,
    root: PathBuf,
    cleanup_verified: AtomicBool,
}
impl Fixture {
    fn new(mode: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "hermes-ws-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).unwrap();
        let count = root.join("count.txt");
        let group = WorkerGroup::new().unwrap();
        let environment = ["SYSTEMROOT", "WINDIR"]
            .into_iter()
            .filter_map(|key| std::env::var_os(key).map(|value| (key.to_owned(), value)))
            .collect::<BTreeMap<_, _>>();
        let worker = group
            .spawn_captured(
                &WorkerSpec {
                    executable: PathBuf::from(env!("CARGO_BIN_EXE_owned-ws-fixture")),
                    working_directory: root.clone(),
                    arguments: vec![mode.into(), count.as_os_str().to_owned()],
                    environment,
                },
                CaptureLimits::default(),
            )
            .unwrap();
        let port = worker.wait_ready(Duration::from_secs(3)).unwrap();
        Self {
            group,
            worker,
            port,
            count,
            root,
            cleanup_verified: AtomicBool::new(false),
        }
    }
    fn connect(&self) -> OwnedWebSocket<'_> {
        OwnedWebSocket::connect(&self.group, self.port, TOKEN, Limits::default()).unwrap()
    }
    fn retire(&self) {
        self.group
            .retire_captured(&self.worker, 88, Duration::from_secs(3))
            .unwrap();
        assert_eq!(self.group.active_count().unwrap(), 0);
        self.cleanup_verified.store(true, Ordering::Release);
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if !self.cleanup_verified.load(Ordering::Acquire) {
            let cleanup = self
                .group
                .retire_captured(&self.worker, 88, Duration::from_secs(3));
            if !std::thread::panicking() {
                assert!(cleanup.is_ok(), "owned fixture cleanup was not verified");
            }
        }
        for path in [&self.count, &self.count.with_extension("auth")] {
            let _ = std::fs::remove_file(path);
        }
        let _ = std::fs::remove_dir(&self.root);
    }
}
#[test]
fn root_and_descendant_echo_text_binary_and_clean_close() {
    for mode in ["echo", "descendant"] {
        let f = Fixture::new(mode);
        let mut ws = f.connect();
        ws.send_text("synthetic-payload-canary\nsecond-line")
            .unwrap();
        assert!(
            matches!(ws.read().unwrap(),Event::Text(s) if s=="synthetic-payload-canary\nsecond-line")
        );
        ws.send_binary(&[0, 1, 2, 255]).unwrap();
        assert!(matches!(ws.read().unwrap(),Event::Binary(v) if v==[0,1,2,255]));
        let report = ws.close().unwrap();
        assert!(report.peer_close_observed && report.connection_closed);
        assert_eq!(
            std::fs::read(f.count.with_extension("auth")).unwrap(),
            b"verified"
        );
        f.retire();
    }
}
#[test]
fn unrelated_listener_receives_zero_bytes_and_survives() {
    let own = Fixture::new("echo");
    let other = Fixture::new("echo");
    let error = OwnedWebSocket::connect(
        &own.group,
        other.port,
        "never-transmit-canary",
        Limits::default(),
    )
    .err()
    .unwrap();
    assert_eq!(error.code(), "WS_OWNER_OR_CONNECT_FAILED");
    let deadline = Instant::now() + Duration::from_secs(2);
    while !other.count.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(2));
    }
    assert_eq!(std::fs::read_to_string(&other.count).unwrap(), "0");
    assert!(!other.count.with_extension("auth").exists());
    own.retire();
    assert!(other
        .worker
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    let mut ws = other.connect();
    ws.close().unwrap();
}
#[test]
fn auth_failure_redirect_extensions_subprotocol_and_duplicate_upgrade_fail() {
    for mode in ["redirect", "extension", "subprotocol", "duplicate"] {
        let f = Fixture::new(mode);
        assert_eq!(
            OwnedWebSocket::connect(&f.group, f.port, TOKEN, Limits::default())
                .err()
                .unwrap()
                .code(),
            "WS_UPGRADE_FAILED"
        );
    }
    let f = Fixture::new("echo");
    assert!(OwnedWebSocket::connect(&f.group, f.port, "wrong-token", Limits::default()).is_err());
    assert!(!f.count.with_extension("auth").exists());
}
#[test]
fn coalesced_first_frame_and_fragment_boundaries_are_preserved() {
    let f = Fixture::new("coalesced");
    let mut ws = f.connect();
    assert!(matches!(ws.read().unwrap(),Event::Text(s) if s=="coalesced-first"));
    ws.close().unwrap();
    let f = Fixture::new("controls");
    let mut ws = f.connect();
    assert!(matches!(ws.read().unwrap(),Event::Ping(v) if v==b"synthetic-ping-canary"));
    assert!(matches!(ws.read().unwrap(),Event::Pong(v) if v==b"pong"));
    assert!(matches!(ws.read().unwrap(),Event::Text(s) if s=="part-two"));
    ws.close().unwrap();
}
#[test]
fn malformed_oversized_and_slow_peers_fail_closed_within_total_deadline() {
    for mode in [
        "oversize",
        "fragmentoversize",
        "abrupt",
        "invalidutf8",
        "badclose",
        "slowread",
        "fragmentflood",
    ] {
        let f = Fixture::new(mode);
        let limits = Limits {
            operation_timeout: Duration::from_millis(150),
            max_message_bytes: 1024,
            max_frame_bytes: 1024,
            ..Limits::default()
        };
        let mut ws = OwnedWebSocket::connect(&f.group, f.port, TOKEN, limits).unwrap();
        let now = Instant::now();
        assert!(ws.read().is_err(), "{mode}");
        assert!(now.elapsed() < Duration::from_secs(1));
        assert!(ws.send_text("after-error").is_err());
        f.retire();
    }
    for mode in ["slowupgrade", "hugeheaders"] {
        let f = Fixture::new(mode);
        let limits = Limits {
            connect_timeout: Duration::from_millis(150),
            max_header_bytes: 512,
            ..Limits::default()
        };
        let now = Instant::now();
        assert!(OwnedWebSocket::connect(&f.group, f.port, TOKEN, limits).is_err());
        assert!(now.elapsed() < Duration::from_secs(1));
    }
}
#[test]
fn close_timeout_control_flood_and_retirement_never_claim_success() {
    for mode in ["closehold", "controlflood"] {
        let f = Fixture::new(mode);
        let limits = Limits {
            close_timeout: Duration::from_millis(150),
            ..Limits::default()
        };
        let mut ws = OwnedWebSocket::connect(&f.group, f.port, TOKEN, limits).unwrap();
        let now = Instant::now();
        assert!(ws.close().is_err());
        assert!(now.elapsed() < Duration::from_secs(1));
    }
    let f = Fixture::new("echo");
    let mut ws = f.connect();
    f.retire();
    assert!(ws.send_text("after-retirement").is_err());
}
static LOG_TRUNCATED: AtomicBool = AtomicBool::new(false);
static LOGS: Mutex<Vec<String>> = Mutex::new(Vec::new());
static LOGGER: TraceLogger = TraceLogger;
static INIT: Once = Once::new();
struct TraceLogger;
impl log::Log for TraceLogger {
    fn enabled(&self, _: &log::Metadata<'_>) -> bool {
        true
    }
    fn log(&self, record: &log::Record<'_>) {
        let mut logs = LOGS.lock().unwrap();
        if logs.len() < 10000 {
            logs.push(record.args().to_string());
        } else {
            LOG_TRUNCATED.store(true, Ordering::Release);
        }
    }
    fn flush(&self) {}
}
#[test]
fn trace_logger_and_owned_files_never_contain_credential_or_payload_canaries() {
    INIT.call_once(|| {
        log::set_logger(&LOGGER).unwrap();
        log::set_max_level(log::LevelFilter::Trace);
    });
    let f = Fixture::new("echo");
    let mut ws = f.connect();
    ws.send_text("synthetic-payload-canary").unwrap();
    assert!(matches!(ws.read().unwrap(), Event::Text(_)));
    ws.close().unwrap();
    let peer = Fixture::new("peerclose");
    let mut peer_ws = peer.connect();
    assert!(matches!(
        peer_ws.read().unwrap(),
        Event::Close { code: Some(1000) }
    ));
    assert!(peer_ws.close().unwrap().peer_close_observed);
    assert!(!LOG_TRUNCATED.load(Ordering::Acquire));
    let logs = LOGS.lock().unwrap();
    assert!(!logs.is_empty());
    for line in logs.iter() {
        assert!(
            !line.contains(TOKEN)
                && !line.contains("synthetic-payload-canary")
                && !line.contains("synthetic-close-canary")
                && !line.contains("token=")
        );
    }
    for entry in std::fs::read_dir(&f.root).unwrap() {
        let bytes = std::fs::read(entry.unwrap().path()).unwrap();
        assert!(!String::from_utf8_lossy(&bytes).contains(TOKEN));
    }
}

#[test]
fn blocked_write_and_read_retirement_are_bounded_without_retry() {
    let f = Fixture::new("noread");
    let limits = Limits {
        operation_timeout: Duration::from_millis(150),
        ..Limits::default()
    };
    let mut ws = OwnedWebSocket::connect(&f.group, f.port, TOKEN, limits).unwrap();
    // Successful sends may fit Windows socket buffers even while the peer
    // does not read. Fill only a finite amount until a write actually blocks.
    let payload = vec![7; 1048576];
    let mut failed = false;
    for _ in 0..32 {
        let started = Instant::now();
        if ws.send_binary(&payload).is_err() {
            assert!(started.elapsed() < Duration::from_secs(1));
            failed = true;
            break;
        }
    }
    assert!(
        failed,
        "finite writes must reach the nonreading peer's bounded buffers"
    );
    assert!(ws.send_text("retry-denied").is_err());
    let f = Fixture::new("echo");
    let mut ws = f.connect();
    std::thread::scope(|scope| {
        let read = scope.spawn(move || ws.read().is_err());
        std::thread::sleep(Duration::from_millis(20));
        let now = Instant::now();
        f.retire();
        assert!(read.join().unwrap());
        assert!(now.elapsed() < Duration::from_secs(1));
    });
}
#[test]
fn local_oversized_send_is_rejected_without_changing_healthy_socket() {
    let f = Fixture::new("echo");
    let limits = Limits {
        max_message_bytes: 1024,
        max_frame_bytes: 1024,
        ..Limits::default()
    };
    let mut ws = OwnedWebSocket::connect(&f.group, f.port, TOKEN, limits).unwrap();
    assert_eq!(
        ws.send_text(&"x".repeat(1025)).unwrap_err().code(),
        "WS_MESSAGE_LIMIT"
    );
    ws.send_text("still-healthy").unwrap();
    assert!(matches!(ws.read().unwrap(),Event::Text(s) if s=="still-healthy"));
    ws.close().unwrap();
}

#[test]
fn peer_initiated_close_is_observed_and_verified_separately_from_job_retirement() {
    let f = Fixture::new("peerclose");
    let mut ws = f.connect();
    assert!(matches!(
        ws.read().unwrap(),
        Event::Close { code: Some(1000) }
    ));
    let close = ws.close().unwrap();
    assert!(close.connection_closed && close.peer_close_observed);
    assert!(f
        .worker
        .worker()
        .wait_timeout(Duration::ZERO)
        .unwrap()
        .is_none());
    f.retire();
}
