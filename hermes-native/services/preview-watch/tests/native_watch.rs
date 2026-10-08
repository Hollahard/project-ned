use hermes_preview_watch::{
    PreviewFileChanged, PreviewWatchOwner, TrustedRoots, WatchError, WatchOptions,
};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

static NEXT: AtomicU64 = AtomicU64::new(1);
const POLL: Duration = Duration::from_millis(50);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let parent = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".checks");
        fs::create_dir_all(&parent).unwrap();
        let path = parent.join(format!(
            "fixture-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn owner(&self) -> PreviewWatchOwner {
        PreviewWatchOwner::new(
            TrustedRoots::from_host_paths([self.0.clone()]).unwrap(),
            WatchOptions {
                poll_interval: POLL,
                ..WatchOptions::default()
            },
        )
        .unwrap()
    }

    fn file(&self, name: &str) -> PathBuf {
        let path = self.0.join(name);
        fs::write(&path, b"initial").unwrap();
        path
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // This absolute path was created by this fixture under this crate's
        // .checks. No computed user path or external tree is deleted.
        let expected = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".checks");
        assert_eq!(self.0.parent(), Some(expected.as_path()));
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn changes(owner: &PreviewWatchOwner) -> Vec<PreviewFileChanged> {
    let mut events = Vec::new();
    owner
        .dispatch_pending(|event| events.push(event.clone()))
        .unwrap();
    events
}

fn await_change(owner: &PreviewWatchOwner) -> PreviewFileChanged {
    let deadline = Instant::now() + Duration::from_secs(4);
    loop {
        let events = changes(owner);
        if !events.is_empty() {
            assert_eq!(events.len(), 1);
            return events[0].clone();
        }
        assert!(
            Instant::now() < deadline,
            "filesystem change not observed; failures={:?}",
            owner.take_failures().unwrap()
        );
        thread::sleep(Duration::from_millis(10));
    }
}

fn quiet(owner: &PreviewWatchOwner) {
    thread::sleep(POLL * 4);
    assert!(changes(owner).is_empty());
}

#[test]
fn actual_file_edit_emits_wire_payload_with_unicode_file_url() {
    let fixture = Fixture::new();
    let file = fixture.file("preview 漢字 #.txt");
    let owner = fixture.owner();
    let watch = owner
        .watch_file(url::Url::from_file_path(&file).unwrap().as_str())
        .unwrap();
    assert!(changes(&owner).is_empty());
    fs::write(&file, b"a real, longer edit").unwrap();
    let event = await_change(&owner);
    assert_eq!(event.id, watch.id);
    assert_eq!(event.path, watch.path);
    assert_eq!(
        url::Url::parse(&event.url).unwrap().to_file_path().unwrap(),
        file
    );
    let json = serde_json::to_value(&event).unwrap();
    assert_eq!(json.as_object().unwrap().len(), 3);
    quiet(&owner);
}

#[test]
fn events_and_stop_are_owner_scoped_even_for_same_file() {
    let fixture = Fixture::new();
    let file = fixture.file("same.txt");
    let first = fixture.owner();
    let second = fixture.owner();
    let a = first.watch_file(file.to_str().unwrap()).unwrap();
    let b = second.watch_file(file.to_str().unwrap()).unwrap();
    assert_ne!(a.id, b.id);
    assert!(!second.stop(&a.id).unwrap());
    fs::write(&file, b"changed").unwrap();
    assert_eq!(await_change(&first).id, a.id);
    assert_eq!(await_change(&second).id, b.id);
    first.retire().unwrap();
    fs::write(&file, b"changed again after owner teardown").unwrap();
    assert_eq!(await_change(&second).id, b.id);
    assert!(changes(&first).is_empty());
}

#[test]
fn stop_cancels_pending_delivery_and_rejects_repeat_stop() {
    let fixture = Fixture::new();
    let file = fixture.file("stop.txt");
    let owner = fixture.owner();
    let watch = owner.watch_file(file.to_str().unwrap()).unwrap();
    fs::write(&file, b"changed and queued").unwrap();
    thread::sleep(POLL * 4);
    assert!(owner.stop(&watch.id).unwrap());
    assert!(!owner.stop(&watch.id).unwrap());
    quiet(&owner);
    assert_eq!(owner.watch_count().unwrap(), 0);
}

#[test]
fn retirement_is_permanent_and_wakes_worker_without_poll_delay() {
    let fixture = Fixture::new();
    let file = fixture.file("retire.txt");
    let owner = PreviewWatchOwner::new(
        TrustedRoots::from_host_paths([fixture.0.clone()]).unwrap(),
        WatchOptions {
            poll_interval: Duration::from_secs(5),
            ..WatchOptions::default()
        },
    )
    .unwrap();
    owner.watch_file(file.to_str().unwrap()).unwrap();
    let start = Instant::now();
    owner.retire().unwrap();
    assert!(start.elapsed() < Duration::from_secs(1));
    owner.retire().unwrap();
    assert_eq!(owner.watch_count().unwrap(), 0);
    assert_eq!(
        owner.watch_file(file.to_str().unwrap()),
        Err(WatchError::Retired)
    );
}

#[test]
fn directory_observes_immediate_create_rename_delete_and_file_edit() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    let watch = owner.watch_directory(fixture.0.to_str().unwrap()).unwrap();
    let file = fixture.file("first.txt");
    assert_eq!(await_change(&owner).id, watch.id);
    fs::write(&file, b"longer new contents").unwrap();
    await_change(&owner);
    let renamed = fixture.0.join("renamed.txt");
    fs::rename(&file, &renamed).unwrap();
    await_change(&owner);
    fs::remove_file(&renamed).unwrap();
    await_change(&owner);
}

#[test]
fn delete_and_recreate_and_replace_are_observed_without_handle_rebinding() {
    let fixture = Fixture::new();
    let file = fixture.file("replace.txt");
    let owner = fixture.owner();
    owner.watch_file(file.to_str().unwrap()).unwrap();
    fs::remove_file(&file).unwrap();
    quiet(&owner); // Same upstream file-watch contract: no missing-file event.
    fs::write(&file, b"recreated").unwrap();
    await_change(&owner);
    let replacement = fixture.file("replacement.tmp");
    fs::write(&replacement, b"replacement, different size").unwrap();
    fs::rename(&replacement, &file).unwrap();
    await_change(&owner);
}

#[test]
fn file_watch_ignores_sibling_edit_and_directory_watch_is_not_recursive() {
    let fixture = Fixture::new();
    let file = fixture.file("target.txt");
    let sibling = fixture.file("sibling.txt");
    let subdir = fixture.0.join("child");
    fs::create_dir(&subdir).unwrap();
    let nested = subdir.join("nested.txt");
    fs::write(&nested, b"initial").unwrap();
    let owner = fixture.owner();
    owner.watch_file(file.to_str().unwrap()).unwrap();
    fs::write(&sibling, b"sibling changed").unwrap();
    quiet(&owner);
    owner.watch_directory(fixture.0.to_str().unwrap()).unwrap();
    fs::write(&nested, b"nested changed length").unwrap();
    quiet(&owner);
}

#[test]
fn no_grants_and_outside_paths_fail_before_existence_probe() {
    let fixture = Fixture::new();
    let outside = Fixture::new();
    let outside_file = outside.file("outside.txt");
    let owner = fixture.owner();
    assert_eq!(
        owner.watch_file(outside_file.to_str().unwrap()),
        Err(WatchError::PathDenied)
    );
    assert_eq!(
        owner.watch_file(outside.0.join("missing.txt").to_str().unwrap()),
        Err(WatchError::PathDenied)
    );
    let empty = PreviewWatchOwner::new(
        TrustedRoots::from_host_paths([]).unwrap(),
        WatchOptions::default(),
    )
    .unwrap();
    assert_eq!(
        empty.watch_file(fixture.file("inside.txt").to_str().unwrap()),
        Err(WatchError::PathDenied)
    );
    assert_eq!(empty.dispatch_pending(|_| panic!("no event")).unwrap(), 0);
}

#[test]
fn path_syntax_missing_and_wrong_kind_are_explicit_errors() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    let file = fixture.file("file.txt");
    assert_eq!(
        owner.watch_file(file.join("missing-child.txt").to_str().unwrap()),
        Err(WatchError::Missing)
    );
    for path in [
        "",
        "relative.txt",
        "https://example.com/file",
        "file://server/share/file",
        "file:///C:/file?secret=1",
        "C:\\file:stream",
        "\\\\?\\C:\\file",
        "C:\\NUL",
    ] {
        assert_eq!(
            owner.watch_file(path),
            Err(WatchError::InvalidPath),
            "{path}"
        );
    }
    assert_eq!(
        owner.watch_file(fixture.0.join("absent.txt").to_str().unwrap()),
        Err(WatchError::Missing)
    );
    assert_eq!(
        owner.watch_file(fixture.0.to_str().unwrap()),
        Err(WatchError::WrongKind)
    );
    assert_eq!(
        owner.watch_directory(file.to_str().unwrap()),
        Err(WatchError::WrongKind)
    );
    let parent_escape = fixture.0.join("..").join("outside.txt");
    assert_eq!(
        owner.watch_file(parent_escape.to_str().unwrap()),
        Err(WatchError::InvalidPath)
    );
}

#[test]
fn sensitive_files_are_denied_and_excluded_from_directory_changes() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    owner.watch_directory(fixture.0.to_str().unwrap()).unwrap();
    for name in [".env", ".env.local", ".npmrc", "id_rsa", "key.pem"] {
        let file = fixture.file(name);
        assert_eq!(
            owner.watch_file(file.to_str().unwrap()),
            Err(WatchError::SensitivePath)
        );
    }
    quiet(&owner);
    let sample = fixture.file(".env.example");
    owner.watch_file(sample.to_str().unwrap()).unwrap();
}

#[test]
fn watch_and_directory_limits_fail_closed_and_pending_is_coalesced() {
    let fixture = Fixture::new();
    let first = fixture.file("a.txt");
    let second = fixture.file("b.txt");
    let owner = PreviewWatchOwner::new(
        TrustedRoots::from_host_paths([fixture.0.clone()]).unwrap(),
        WatchOptions {
            poll_interval: POLL,
            max_watches: 1,
            max_directory_entries: 1,
        },
    )
    .unwrap();
    assert_eq!(
        owner.watch_directory(fixture.0.to_str().unwrap()),
        Err(WatchError::LimitExceeded)
    );
    owner.watch_file(first.to_str().unwrap()).unwrap();
    assert_eq!(
        owner.watch_file(second.to_str().unwrap()),
        Err(WatchError::LimitExceeded)
    );
    for index in 0..8 {
        fs::write(&first, format!("change {index}, {}", "x".repeat(index))).unwrap();
        thread::sleep(POLL * 2);
    }
    assert_eq!(changes(&owner).len(), 1);
}

#[test]
fn a_directory_exceeding_limit_faults_once_and_does_not_fabricate_events() {
    let fixture = Fixture::new();
    fixture.file("a.txt");
    let owner = PreviewWatchOwner::new(
        TrustedRoots::from_host_paths([fixture.0.clone()]).unwrap(),
        WatchOptions {
            poll_interval: POLL,
            max_directory_entries: 1,
            ..WatchOptions::default()
        },
    )
    .unwrap();
    let watch = owner.watch_directory(fixture.0.to_str().unwrap()).unwrap();
    fixture.file("b.txt");
    quiet(&owner);
    let failures = owner.take_failures().unwrap();
    assert_eq!(failures.len(), 1);
    assert_eq!(failures[0].id, watch.id);
    assert_eq!(failures[0].error, WatchError::LimitExceeded);
    quiet(&owner);
    assert!(owner.take_failures().unwrap().is_empty());
}

#[test]
fn concurrent_stop_is_a_delivery_barrier() {
    let fixture = Fixture::new();
    let file = fixture.file("concurrent.txt");
    let owner = Arc::new(fixture.owner());
    let watch = owner.watch_file(file.to_str().unwrap()).unwrap();
    fs::write(file, b"queue an event").unwrap();
    thread::sleep(POLL * 4);
    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let clone = owner.clone();
    let delivery = thread::spawn(move || {
        clone
            .dispatch_pending(|_| {
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            })
            .unwrap()
    });
    entered_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let clone = owner.clone();
    let stop = thread::spawn(move || clone.stop(&watch.id).unwrap());
    thread::sleep(POLL);
    assert!(!stop.is_finished());
    release_tx.send(()).unwrap();
    assert_eq!(delivery.join().unwrap(), 1);
    assert!(stop.join().unwrap());
    quiet(&owner);
}

#[test]
fn invalid_options_fail_before_worker_creation() {
    for options in [
        WatchOptions {
            poll_interval: Duration::ZERO,
            ..WatchOptions::default()
        },
        WatchOptions {
            max_watches: 129,
            ..WatchOptions::default()
        },
        WatchOptions {
            max_directory_entries: 0,
            ..WatchOptions::default()
        },
    ] {
        assert!(matches!(
            PreviewWatchOwner::new(TrustedRoots::from_host_paths([]).unwrap(), options),
            Err(WatchError::InvalidOptions)
        ));
    }
}

#[cfg(windows)]
#[test]
fn native_symlink_and_replacement_reparse_points_fail_closed() {
    use std::os::windows::fs::symlink_dir;
    let fixture = Fixture::new();
    let outside = Fixture::new();
    outside.file("private.txt");
    let link = fixture.0.join("linked");
    symlink_dir(&outside.0, &link).expect("native fixture requires Windows symlink permission");
    let owner = fixture.owner();
    assert_eq!(
        owner.watch_file(link.join("private.txt").to_str().unwrap()),
        Err(WatchError::ReparsePoint)
    );
    assert!(matches!(
        TrustedRoots::from_host_paths([link.clone()]),
        Err(WatchError::ReparsePoint)
    ));
    fs::remove_dir(&link).unwrap();

    let original = fixture.0.join("replaced");
    fs::create_dir(&original).unwrap();
    let target = original.join("private.txt");
    fs::write(&target, b"granted file").unwrap();
    let watch = owner.watch_file(target.to_str().unwrap()).unwrap();
    fs::rename(&original, fixture.0.join("old-directory")).unwrap();
    symlink_dir(&outside.0, &original).unwrap();
    quiet(&owner);
    let failures = owner.take_failures().unwrap();
    assert_eq!(failures.len(), 1);
    assert_eq!(failures[0].id, watch.id);
    assert_eq!(failures[0].error, WatchError::ReparsePoint);
    fs::remove_dir(&original).unwrap();
}

#[test]
fn drop_is_a_retirement_barrier_even_after_callback_panic() {
    let fixture = Fixture::new();
    let file = fixture.file("panic.txt");
    let owner = fixture.owner();
    owner.watch_file(file.to_str().unwrap()).unwrap();
    fs::write(&file, b"queue before callback panic").unwrap();
    thread::sleep(POLL * 4);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        owner
            .dispatch_pending(|_| panic!("fixture delivery panic"))
            .unwrap();
    }));
    assert!(result.is_err());
    let started = Instant::now();
    drop(owner);
    assert!(started.elapsed() < Duration::from_secs(1));
}
