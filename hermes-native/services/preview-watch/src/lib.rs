//! Bounded local filesystem observation. Native host code grants roots and owns each
//! watcher; renderer arguments can request a watch but cannot grant filesystem access.
//! This observes metadata only. It is not a file-read capability or an OS sandbox.

mod paths;

use serde::Serialize;
use std::collections::BTreeMap;
use std::fmt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::Duration;

pub use paths::TrustedRoots;

static NEXT_OWNER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum WatchError {
    InvalidPath,
    PathDenied,
    SensitivePath,
    ReparsePoint,
    Missing,
    WrongKind,
    Io,
    LimitExceeded,
    Retired,
    InvalidOptions,
}

impl fmt::Display for WatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "preview watch: {self:?}")
    }
}
impl std::error::Error for WatchError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreviewWatch {
    pub id: String,
    pub path: String,
}

/// Wire-compatible with the retained HermesPreviewFileChanged payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreviewFileChanged {
    pub id: String,
    pub path: String,
    pub url: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WatchFailure {
    pub id: String,
    pub error: WatchError,
}

#[derive(Debug, Clone, Copy)]
pub struct WatchOptions {
    pub poll_interval: Duration,
    pub max_watches: usize,
    pub max_directory_entries: usize,
}

impl Default for WatchOptions {
    fn default() -> Self {
        Self {
            poll_interval: Duration::from_millis(250),
            max_watches: 64,
            max_directory_entries: 4096,
        }
    }
}

impl WatchOptions {
    fn validate(self) -> Result<Self, WatchError> {
        if !(Duration::from_millis(50)..=Duration::from_secs(5)).contains(&self.poll_interval)
            || !(1..=128).contains(&self.max_watches)
            || !(1..=16384).contains(&self.max_directory_entries)
        {
            return Err(WatchError::InvalidOptions);
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy)]
enum Kind {
    File,
    Directory,
}

struct Watch {
    path: PathBuf,
    kind: Kind,
    event: PreviewFileChanged,
    snapshot: paths::Snapshot,
    faulted: bool,
}

#[derive(Default)]
struct State {
    retired: bool,
    next_id: u64,
    watches: BTreeMap<String, Watch>,
    pending: BTreeMap<String, PreviewFileChanged>,
    failures: BTreeMap<String, WatchFailure>,
}

struct Shared {
    roots: TrustedRoots,
    options: WatchOptions,
    state: Mutex<State>,
    wake: Condvar,
}

/// One native window/session owner. Keep this in a host-controlled registry.
/// Never deserialize it, its roots, or an owner identity from renderer arguments.
/// A new owner gets a new instance; retirement is permanent, including cloned Arcs.
pub struct PreviewWatchOwner {
    owner_number: u64,
    shared: Arc<Shared>,
    worker: Mutex<Option<JoinHandle<()>>>,
}

impl PreviewWatchOwner {
    pub fn new(roots: TrustedRoots, options: WatchOptions) -> Result<Self, WatchError> {
        let shared = Arc::new(Shared {
            roots,
            options: options.validate()?,
            state: Mutex::new(State::default()),
            wake: Condvar::new(),
        });
        let worker_shared = shared.clone();
        let worker = thread::Builder::new()
            .name("hermes-preview-watch".into())
            .spawn(move || observe(worker_shared))
            .map_err(|_| WatchError::Io)?;
        Ok(Self {
            owner_number: NEXT_OWNER.fetch_add(1, Ordering::Relaxed),
            shared,
            worker: Mutex::new(Some(worker)),
        })
    }

    pub fn watch_file(&self, path_or_file_url: &str) -> Result<PreviewWatch, WatchError> {
        self.register(path_or_file_url, Kind::File)
    }

    pub fn watch_directory(&self, absolute_path: &str) -> Result<PreviewWatch, WatchError> {
        self.register(absolute_path, Kind::Directory)
    }

    fn register(&self, raw: &str, kind: Kind) -> Result<PreviewWatch, WatchError> {
        let mut state = self.state()?;
        if state.retired {
            return Err(WatchError::Retired);
        }
        if state.watches.len() >= self.shared.options.max_watches {
            return Err(WatchError::LimitExceeded);
        }
        let path = self.shared.roots.resolve(raw)?;
        let snapshot =
            self.shared
                .roots
                .snapshot(&path, kind, self.shared.options.max_directory_entries)?;
        if snapshot.is_missing() {
            return Err(WatchError::Missing);
        }
        state.next_id = state
            .next_id
            .checked_add(1)
            .ok_or(WatchError::LimitExceeded)?;
        let id = format!("preview-{}-{}", self.owner_number, state.next_id);
        let display = paths::display_path(&path)?;
        let url = url::Url::from_file_path(&display)
            .map_err(|_| WatchError::InvalidPath)?
            .to_string();
        let event = PreviewFileChanged {
            id: id.clone(),
            path: display.clone(),
            url,
        };
        state.watches.insert(
            id.clone(),
            Watch {
                path,
                kind,
                event,
                snapshot,
                faulted: false,
            },
        );
        Ok(PreviewWatch { id, path: display })
    }

    /// Only this owner can stop this id. Clears queued delivery before returning.
    pub fn stop(&self, id: &str) -> Result<bool, WatchError> {
        let mut state = self.state()?;
        state.pending.remove(id);
        state.failures.remove(id);
        Ok(state.watches.remove(id).is_some())
    }

    /// Emit only to the native owner of this instance. The callback must be brief
    /// and MUST NOT re-enter this instance. Holding the lock across delivery makes
    /// stop/retire barriers: no callback starts after either returns.
    /// Events already delivered to a renderer cannot be retracted.
    pub fn dispatch_pending(
        &self,
        mut deliver: impl FnMut(&PreviewFileChanged),
    ) -> Result<usize, WatchError> {
        let mut state = self.state()?;
        if state.retired {
            return Ok(0);
        }
        let events = std::mem::take(&mut state.pending);
        let count = events.len();
        for event in events.values() {
            deliver(event);
        }
        Ok(count)
    }

    /// A watch with a failure stays faulted until explicitly stopped. The host
    /// should surface/log this state; it must not report a still-healthy watch.
    pub fn take_failures(&self) -> Result<Vec<WatchFailure>, WatchError> {
        Ok(std::mem::take(&mut self.state()?.failures)
            .into_values()
            .collect())
    }

    pub fn watch_count(&self) -> Result<usize, WatchError> {
        Ok(self.state()?.watches.len())
    }

    /// Proactively call on native owner destruction/navigation/replacement. Drop
    /// is a final safeguard. It wakes and joins the worker, with no polling delay.
    /// Local filesystem calls themselves have OS-governed completion latency.
    pub fn retire(&self) -> Result<(), WatchError> {
        {
            let mut state = self.state()?;
            state.retired = true;
            state.watches.clear();
            state.pending.clear();
            state.failures.clear();
            self.shared.wake.notify_all();
        }
        if let Some(worker) = self.worker.lock().map_err(|_| WatchError::Retired)?.take() {
            worker.join().map_err(|_| WatchError::Retired)?;
        }
        Ok(())
    }

    fn state(&self) -> Result<MutexGuard<'_, State>, WatchError> {
        self.shared.state.lock().map_err(|_| WatchError::Retired)
    }
}

impl Drop for PreviewWatchOwner {
    fn drop(&mut self) {
        // A panicking external delivery callback may poison the mutex. Retire the
        // worker anyway so dropping the owner cannot leak a filesystem observer.
        {
            let mut state = self.shared.state.lock().unwrap_or_else(|e| e.into_inner());
            state.retired = true;
            state.watches.clear();
            state.pending.clear();
            self.shared.wake.notify_all();
        }
        if let Some(worker) = self
            .worker
            .get_mut()
            .unwrap_or_else(|e| e.into_inner())
            .take()
        {
            let _ = worker.join();
        }
    }
}

fn observe(shared: Arc<Shared>) {
    let Ok(mut state) = shared.state.lock() else {
        return;
    };
    loop {
        if state.retired {
            return;
        }
        let Ok((next, _)) = shared
            .wake
            .wait_timeout(state, shared.options.poll_interval)
        else {
            return;
        };
        state = next;
        if state.retired {
            return;
        }
        // At most max_watches scans, each at most max_directory_entries entries;
        // no recursive walks, reads of file contents, or filesystem event storm.
        let mut events = Vec::new();
        let mut failures = Vec::new();
        for (id, watch) in &mut state.watches {
            if watch.faulted {
                continue;
            }
            match shared.roots.snapshot(
                &watch.path,
                watch.kind,
                shared.options.max_directory_entries,
            ) {
                Ok(snapshot) => {
                    if snapshot != watch.snapshot && !snapshot.is_missing() {
                        events.push(watch.event.clone());
                    }
                    watch.snapshot = snapshot;
                }
                Err(error) => {
                    watch.faulted = true;
                    failures.push(WatchFailure {
                        id: id.clone(),
                        error,
                    });
                }
            }
        }
        for event in events {
            state.pending.insert(event.id.clone(), event);
        }
        for failure in failures {
            state.pending.remove(&failure.id);
            state.failures.insert(failure.id.clone(), failure);
        }
    }
}
