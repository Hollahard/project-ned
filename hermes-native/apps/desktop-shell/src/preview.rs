//! Native-only preview capability. The renderer selects paths inside an existing
//! grant; it cannot create a grant or select the owner that receives events.

use hermes_preview_watch::{PreviewWatchOwner, TrustedRoots, WatchError, WatchOptions};
use serde::Serialize;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use tauri::{WebviewWindow, WindowEvent};

#[derive(Debug, Serialize)]
pub struct PreviewHostError {
    pub code: &'static str,
    pub capability: String,
}

impl std::fmt::Display for PreviewHostError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.capability)
    }
}

impl std::error::Error for PreviewHostError {}

fn error(code: &'static str, capability: &str) -> PreviewHostError {
    PreviewHostError {
        code,
        capability: capability.into(),
    }
}

fn watch_error(reason: WatchError, method: &str) -> PreviewHostError {
    let code = match reason {
        WatchError::InvalidPath => "HERMES_PREVIEW_INVALID_PATH",
        WatchError::PathDenied => "HERMES_PREVIEW_PATH_DENIED",
        WatchError::SensitivePath => "HERMES_PREVIEW_SENSITIVE_PATH",
        WatchError::ReparsePoint => "HERMES_PREVIEW_REPARSE_POINT",
        WatchError::Missing => "HERMES_PREVIEW_PATH_MISSING",
        WatchError::WrongKind => "HERMES_PREVIEW_WRONG_KIND",
        WatchError::Io => "HERMES_PREVIEW_IO_FAILED",
        WatchError::LimitExceeded => "HERMES_PREVIEW_LIMIT_EXCEEDED",
        WatchError::Retired => "HERMES_PREVIEW_OWNER_RETIRED",
        WatchError::InvalidOptions => "HERMES_PREVIEW_INVALID_OPTIONS",
    };
    error(code, method)
}

pub fn supports(method: &str) -> bool {
    matches!(
        method,
        "watchPreviewFile" | "watchDirectory" | "stopPreviewFileWatch"
    )
}

struct Inner {
    window: WebviewWindow,
    hwnd: isize,
    owner: PreviewWatchOwner,
    live: AtomicBool,
    wake: (Mutex<bool>, Condvar),
    dispatched: AtomicU64,
    faults: AtomicU64,
    document_id: Mutex<Option<String>>,
    #[cfg(feature = "binding-fixture")]
    captured_event: Mutex<Option<Value>>,
    #[cfg(feature = "binding-fixture")]
    fixture: Mutex<Option<FixtureFiles>>,
    #[cfg(feature = "binding-fixture")]
    fixture_root: Option<PathBuf>,
    #[cfg(feature = "binding-fixture")]
    observer: Mutex<Option<WebviewWindow>>,
}

type Pump = Mutex<Option<JoinHandle<()>>>;

/// Manage one instance for the exact main window lifetime. Do not transfer it
/// to another same-label window. Navigation/replacement must retire this instance
/// before the new renderer is admitted. Destroyed also retires automatically.
pub struct PreviewState {
    inner: Arc<Inner>,
    pump: Arc<Pump>,
}

impl PreviewState {
    pub fn new(window: WebviewWindow) -> Result<Self, PreviewHostError> {
        // Native setup may run before the bundled page has finished navigating.
        // Origin is checked at every request, never guessed during construction.
        if window.label() != "main" {
            return Err(error("HERMES_HOST_FORBIDDEN", "preview-owner"));
        }
        let hwnd = native_identity(&window)?;
        let roots: Vec<PathBuf>;
        #[cfg(feature = "binding-fixture")]
        let fixture_root =
            std::env::var_os("HERMES_NATIVE_PREVIEW_FIXTURE_ROOT").map(PathBuf::from);
        #[cfg(feature = "binding-fixture")]
        {
            roots = fixture_root.iter().cloned().collect();
        }
        #[cfg(not(feature = "binding-fixture"))]
        {
            // No native picker/source routing exists yet. A production renderer
            // has no filesystem grants and cannot manufacture them through IPC.
            roots = Vec::new();
        }
        let owner = PreviewWatchOwner::new(
            TrustedRoots::from_host_paths(roots).map_err(|e| watch_error(e, "preview-owner"))?,
            WatchOptions::default(),
        )
        .map_err(|e| watch_error(e, "preview-owner"))?;
        let inner = Arc::new(Inner {
            window: window.clone(),
            hwnd,
            owner,
            live: AtomicBool::new(true),
            wake: (Mutex::new(false), Condvar::new()),
            dispatched: AtomicU64::new(0),
            faults: AtomicU64::new(0),
            document_id: Mutex::new(None),
            #[cfg(feature = "binding-fixture")]
            captured_event: Mutex::new(None),
            #[cfg(feature = "binding-fixture")]
            fixture: Mutex::new(None),
            #[cfg(feature = "binding-fixture")]
            fixture_root,
            #[cfg(feature = "binding-fixture")]
            observer: Mutex::new(None),
        });
        let pump_inner = inner.clone();
        let handle = thread::Builder::new()
            .name("hermes-preview-dispatch".into())
            .spawn(move || pump_events(pump_inner))
            .map_err(|_| error("HERMES_PREVIEW_DISPATCH_FAILED", "preview-owner"))?;
        let pump = Arc::new(Mutex::new(Some(handle)));
        let weak_inner = Arc::downgrade(&inner);
        let weak_pump = Arc::downgrade(&pump);
        window.on_window_event(move |event| {
            if matches!(event, WindowEvent::Destroyed) {
                if let (Some(inner), Some(pump)) = (weak_inner.upgrade(), weak_pump.upgrade()) {
                    retire(&inner, &pump);
                }
            }
        });
        Ok(Self { inner, pump })
    }

    pub fn dispatch(
        &self,
        caller: &WebviewWindow,
        method: &str,
        args: &[Value],
        document_id: Option<&str>,
    ) -> Result<Value, PreviewHostError> {
        self.check_caller(caller)?;
        self.bind_document(document_id)?;
        if !supports(method) || args.len() != 1 {
            return Err(error("HERMES_HOST_INVALID_REQUEST", method));
        }
        let raw = args[0]
            .as_str()
            .filter(|value| value.len() <= 32767)
            .ok_or_else(|| error("HERMES_HOST_INVALID_REQUEST", method))?;
        match method {
            "watchPreviewFile" => match self.inner.owner.watch_file(raw) {
                Ok(watch) => Ok(json!(watch)),
                Err(WatchError::Missing) => Ok(
                    json!({"ok":false,"error":"ENOENT","message":"Preview file does not exist.","path":raw}),
                ),
                Err(reason) => Err(watch_error(reason, method)),
            },
            "watchDirectory" => self
                .inner
                .owner
                .watch_directory(raw)
                .map(|watch| json!(watch))
                .map_err(|reason| watch_error(reason, method)),
            "stopPreviewFileWatch" => self
                .inner
                .owner
                .stop(raw)
                .map(Value::Bool)
                .map_err(|reason| watch_error(reason, method)),
            _ => Err(error("HERMES_HOST_INVALID_REQUEST", method)),
        }
    }

    pub fn retire(&self) {
        retire(&self.inner, &self.pump);
    }

    fn bind_document(&self, value: Option<&str>) -> Result<(), PreviewHostError> {
        let value = value
            .filter(|value| valid_document_id(value))
            .ok_or_else(|| error("HERMES_PREVIEW_INVALID_DOCUMENT", "preview-owner"))?;
        let mut bound = self
            .inner
            .document_id
            .lock()
            .map_err(|_| error("HERMES_PREVIEW_OWNER_RETIRED", "preview-owner"))?;
        match bound.as_deref() {
            Some(existing) if existing != value => {
                drop(bound);
                self.retire();
                Err(error("HERMES_PREVIEW_DOCUMENT_MISMATCH", "preview-owner"))
            }
            Some(_) => Ok(()),
            None => {
                *bound = Some(value.to_owned());
                Ok(())
            }
        }
    }

    fn check_caller(&self, caller: &WebviewWindow) -> Result<(), PreviewHostError> {
        if !self.inner.live.load(Ordering::Acquire) {
            return Err(error("HERMES_PREVIEW_OWNER_RETIRED", "preview-owner"));
        }
        self.check_identity(caller)?;
        if !self.inner.live.load(Ordering::Acquire) {
            return Err(error("HERMES_PREVIEW_OWNER_RETIRED", "preview-owner"));
        }
        Ok(())
    }

    fn check_identity(&self, caller: &WebviewWindow) -> Result<(), PreviewHostError> {
        trusted_origin(caller)?;
        if native_identity(caller)? != self.inner.hwnd
            || native_identity(&self.inner.window)? != self.inner.hwnd
        {
            return Err(error("HERMES_HOST_FORBIDDEN", "preview-owner"));
        }
        Ok(())
    }
}

impl Drop for PreviewState {
    fn drop(&mut self) {
        self.retire();
    }
}

fn trusted_origin(window: &WebviewWindow) -> Result<(), PreviewHostError> {
    if window.label() != "main"
        || !window
            .url()
            .is_ok_and(|url| crate::policy::local_origin(&url))
    {
        return Err(error("HERMES_HOST_FORBIDDEN", "renderer-origin"));
    }
    Ok(())
}

fn native_identity(window: &WebviewWindow) -> Result<isize, PreviewHostError> {
    #[cfg(windows)]
    {
        window
            .hwnd()
            .map(|handle| handle.0 as isize)
            .map_err(|_| error("HERMES_HOST_FORBIDDEN", "preview-owner"))
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Err(error("HERMES_HOST_CAPABILITY_UNAVAILABLE", "preview-owner"))
    }
}

fn retire(inner: &Inner, pump: &Pump) {
    inner.live.store(false, Ordering::Release);
    {
        let mut stopped = inner.wake.0.lock().unwrap_or_else(|e| e.into_inner());
        *stopped = true;
        inner.wake.1.notify_all();
    }
    if inner.owner.retire().is_err() {
        eprintln!("HERMES_PREVIEW_OWNER_RETIRE_FAILED");
    }
    if let Some(handle) = pump.lock().unwrap_or_else(|e| e.into_inner()).take() {
        if handle.join().is_err() {
            eprintln!("HERMES_PREVIEW_DISPATCH_RETIRE_FAILED");
        }
    }
}

fn pump_events(inner: Arc<Inner>) {
    loop {
        let stopped = inner.wake.0.lock().unwrap_or_else(|e| e.into_inner());
        if *stopped || !inner.live.load(Ordering::Acquire) {
            return;
        }
        let (stopped, _) = inner
            .wake
            .1
            .wait_timeout(stopped, Duration::from_millis(50))
            .unwrap_or_else(|e| e.into_inner());
        if *stopped || !inner.live.load(Ordering::Acquire) {
            return;
        }
        drop(stopped);
        // Never call url()/hwnd() here: they can synchronously marshal to the UI
        // thread, while a UI-thread destruction callback must join this worker.
        let mut failed = false;
        if inner
            .owner
            .dispatch_pending(|payload| {
                if !inner.live.load(Ordering::Acquire) {
                    return;
                }
                if deliver_to_owner(
                    &inner,
                    json!({"name":"preview-file-changed","payload":payload}),
                )
                .is_ok()
                {
                    inner.dispatched.fetch_add(1, Ordering::Relaxed);
                } else {
                    failed = true;
                }
            })
            .is_err()
        {
            failed = true;
        }
        match inner.owner.take_failures() {
            Ok(failures) => {
                for fault in failures {
                    inner.faults.fetch_add(1, Ordering::Relaxed);
                    eprintln!("HERMES_PREVIEW_WATCH_FAULT {:?}", fault.error);
                    if inner.live.load(Ordering::Acquire)
                        && deliver_to_owner(
                            &inner,
                            json!({"name":"preview-watch-failed","payload":fault}),
                        )
                        .is_err()
                    {
                        failed = true;
                    }
                }
            }
            Err(_) => failed = true,
        }
        if failed {
            inner.live.store(false, Ordering::Release);
            let _ = inner.owner.retire();
            eprintln!("HERMES_PREVIEW_DISPATCH_FAILED");
            return;
        }
    }
}

fn valid_document_id(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
}

fn delivery_script(packet: &Value) -> Result<String, serde_json::Error> {
    let json = serde_json::to_string(packet)?
        .replace('\u{2028}', "\\u2028")
        .replace('\u{2029}', "\\u2029");
    // Only a serialized JSON value enters the fixed script. A quoted filename
    // or payload cannot become executable source. This is an event receiver,
    // never a native action, and is not authenticatable inside its own renderer.
    Ok(format!(
        "globalThis.__HERMES_NATIVE_EVENT_RECEIVER__?.({json});"
    ))
}

fn deliver_to_owner(inner: &Inner, envelope: Value) -> Result<(), ()> {
    // Tauri emit and even emit_to can reach another view's ANY listener. Use the
    // original WebviewWindow dispatcher (native webview id), never the app bus.
    let document_id = inner
        .document_id
        .lock()
        .map_err(|_| ())?
        .clone()
        .ok_or(())?;
    let packet = json!({"documentId":document_id,"event":envelope});
    #[cfg(feature = "binding-fixture")]
    if packet["event"]["name"] == "preview-file-changed" {
        *inner.captured_event.lock().map_err(|_| ())? = Some(packet.clone());
    }
    inner
        .window
        .eval(delivery_script(&packet).map_err(|_| ())?)
        .map_err(|_| ())
}

#[cfg(feature = "binding-fixture")]
struct FixtureFiles {
    file: std::fs::File,
    directory: PathBuf,
    writes: u32,
}

#[cfg(feature = "binding-fixture")]
impl PreviewState {
    /// Called only from the cfg-gated native proof command. No renderer path is
    /// accepted. All writes target files this fixture created with create_new.
    pub fn fixture_phase(
        &self,
        caller: &WebviewWindow,
        phase: &str,
    ) -> Result<Value, PreviewHostError> {
        use std::io::{Seek, SeekFrom, Write};
        // These two cfg-only phases deliberately inspect a retired SAME native
        // view for the reload proof. They cannot register watches or grant roots.
        if matches!(phase, "preview-replay-stale" | "preview-retired-stats") {
            self.check_identity(caller)?;
            if self.inner.live.load(Ordering::Acquire) {
                return Err(error("HERMES_PREVIEW_FIXTURE_NOT_RETIRED", "fixture"));
            }
            if phase == "preview-retired-stats" {
                return Ok(
                    json!({"retired":true,"watchCount":self.inner.owner.watch_count().map_err(|e| watch_error(e, "fixture"))?}),
                );
            }
            let packet = self
                .inner
                .captured_event
                .lock()
                .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?
                .clone()
                .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_NO_CAPTURED_EVENT", "fixture"))?;
            let script = delivery_script(&packet)
                .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
            self.inner
                .window
                .eval(script)
                .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
            return Ok(Value::Null);
        }
        self.check_caller(caller)?;
        if phase == "preview-retire" {
            self.retire();
            return Ok(Value::Null);
        }
        if phase == "preview-stats" {
            return Ok(json!({
                "dispatched": self.inner.dispatched.load(Ordering::Relaxed),
                "faults": self.inner.faults.load(Ordering::Relaxed),
                "watchCount": self.inner.owner.watch_count().map_err(|e| watch_error(e, "fixture"))?
            }));
        }
        let root = self
            .inner
            .fixture_root
            .as_ref()
            .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_ROOT_REQUIRED", "fixture"))?;
        if phase.starts_with("preview-observer-") {
            use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
            let mut observer = self
                .inner
                .observer
                .lock()
                .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
            return match phase {
                "preview-observer-create" => {
                    if observer.is_some() {
                        return Err(error("HERMES_PREVIEW_FIXTURE_ALREADY_PREPARED", "fixture"));
                    }
                    let profile = root.join("preview-observer-profile");
                    std::fs::create_dir(&profile)
                        .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
                    let window = WebviewWindowBuilder::new(
                        self.inner.window.app_handle(),
                        "preview-observer",
                        WebviewUrl::App("preview-observer.html".into()),
                    )
                    .visible(false)
                    .data_directory(profile)
                    .on_navigation(|url| {
                        crate::policy::local_origin(url) && url.path() == "/preview-observer.html"
                    })
                    .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                    .build()
                    .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
                    *observer = Some(window);
                    Ok(Value::Null)
                }
                "preview-observer-stats" => {
                    let window = observer
                        .as_ref()
                        .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_NOT_PREPARED", "fixture"))?;
                    let url = window
                        .url()
                        .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
                    let fragment = url.fragment().unwrap_or("");
                    let counters = fragment
                        .strip_prefix("ready-")
                        .and_then(|value| value.split_once('-'));
                    let count = counters.and_then(|(preview, _)| preview.parse::<u64>().ok());
                    let controls = counters.and_then(|(_, control)| control.parse::<u64>().ok());
                    Ok(
                        json!({"ready":count.is_some() && controls.is_some(),"count":count,"controls":controls}),
                    )
                }
                "preview-observer-close" => {
                    let window = observer
                        .take()
                        .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_NOT_PREPARED", "fixture"))?;
                    window
                        .destroy()
                        .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
                    Ok(Value::Null)
                }
                _ => Err(error("HERMES_FIXTURE_INVALID_PHASE", "fixture")),
            };
        }
        let mut files = self
            .inner
            .fixture
            .lock()
            .map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
        let io_error = |_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture");
        match phase {
            "preview-prepare" => {
                if files.is_some() {
                    return Err(error("HERMES_PREVIEW_FIXTURE_ALREADY_PREPARED", "fixture"));
                }
                let path = root.join("preview-proof.txt");
                let directory = root.join("preview-directory-proof");
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&path)
                    .map_err(io_error)?;
                file.write_all(b"initial native fixture")
                    .map_err(io_error)?;
                file.sync_all().map_err(io_error)?;
                std::fs::create_dir(&directory).map_err(io_error)?;
                let result = json!({"path":path,"url":tauri::Url::from_file_path(&path).map_err(|_| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?.as_str(),"directory":directory});
                *files = Some(FixtureFiles {
                    file,
                    directory,
                    writes: 0,
                });
                Ok(result)
            }
            "preview-write" => {
                let files = files
                    .as_mut()
                    .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_NOT_PREPARED", "fixture"))?;
                if files.writes >= 16 {
                    return Err(error("HERMES_PREVIEW_FIXTURE_WRITE_LIMIT", "fixture"));
                }
                files.writes = files
                    .writes
                    .checked_add(1)
                    .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_FAILED", "fixture"))?;
                files.file.seek(SeekFrom::Start(0)).map_err(io_error)?;
                files.file.set_len(0).map_err(io_error)?;
                files
                    .file
                    .write_all(
                        format!(
                            "actual native file edit {} {}",
                            files.writes,
                            "x".repeat(files.writes as usize)
                        )
                        .as_bytes(),
                    )
                    .map_err(io_error)?;
                files.file.sync_all().map_err(io_error)?;
                Ok(Value::Null)
            }
            "preview-directory-write" => {
                let files = files
                    .as_mut()
                    .ok_or_else(|| error("HERMES_PREVIEW_FIXTURE_NOT_PREPARED", "fixture"))?;
                // Fixed fixture child, create_new rejects any preexisting file.
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(files.directory.join("new-native-entry.txt"))
                    .map_err(io_error)?;
                file.write_all(b"directory entry churn").map_err(io_error)?;
                file.sync_all().map_err(io_error)?;
                Ok(Value::Null)
            }
            _ => Err(error("HERMES_FIXTURE_INVALID_PHASE", "fixture")),
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn document_id_is_bounded_routing_data_not_an_arbitrary_script() {
        assert!(super::valid_document_id(
            "00112233-4455-6677-8899-aabbccddeeff"
        ));
        for invalid in [
            "",
            "not-a-uuid",
            "00112233-4455-6677-8899-aabbccddeezz",
            "0011223344455-6677-8899-aabbccddeeff",
        ] {
            assert!(!super::valid_document_id(invalid));
        }
    }
    #[test]
    fn native_delivery_serializes_data_without_interpolating_script_fragments() {
        let payload = serde_json::json!({"name":"preview-file-changed","payload":{"id":"watch","path":"\";throw Error('injection');//\u{2028}\u{2029}","url":"file:///fixture"}});
        let script = super::delivery_script(&payload).unwrap();
        let encoded = script
            .strip_prefix("globalThis.__HERMES_NATIVE_EVENT_RECEIVER__?.(")
            .unwrap()
            .strip_suffix(");")
            .unwrap();
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(encoded).unwrap(),
            payload
        );
        assert!(!script.contains(['\u{2028}', '\u{2029}']));
    }
}
