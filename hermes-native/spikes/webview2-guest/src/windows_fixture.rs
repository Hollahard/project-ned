use hermes_webview2_guest_spike::{allows_navigation, validate_snapshot, Snapshot};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    error::Error,
    fs,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tao::{
    event::Event,
    event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy},
    platform::run_return::EventLoopExtRunReturn,
    window::{Window, WindowBuilder},
};
use wry::{
    dpi::{PhysicalPosition, PhysicalSize},
    NewWindowResponse, PageLoadEvent, Rect, WebContext, WebView, WebViewBuilder, WebViewExtWindows,
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[derive(Debug)]
enum FixtureEvent {
    Loaded {
        guest: usize,
        url: String,
    },
    Evaluated {
        phase: &'static str,
        value: String,
    },
    PopupDenied {
        guest: usize,
        url: String,
    },
    Navigation {
        guest: usize,
        url: String,
        allowed: bool,
    },
}

struct FixtureServer {
    origin: String,
    stop: Arc<AtomicBool>,
    paths: Arc<Mutex<Vec<String>>>,
    thread: Option<thread::JoinHandle<()>>,
}

impl FixtureServer {
    fn start() -> Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        let origin = format!("http://{}", listener.local_addr()?);
        listener.set_nonblocking(true)?;
        let stop = Arc::new(AtomicBool::new(false));
        let paths = Arc::new(Mutex::new(Vec::new()));
        let thread_stop = stop.clone();
        let thread_paths = paths.clone();
        let server_thread = thread::spawn(move || {
            let mut clients: Vec<thread::JoinHandle<()>> = Vec::new();
            let mut drain_deadline = None;
            loop {
                clients = clients
                    .into_iter()
                    .filter_map(|client| {
                        if client.is_finished() {
                            let _ = client.join();
                            None
                        } else {
                            Some(client)
                        }
                    })
                    .collect();
                if thread_stop.load(Ordering::Acquire) {
                    let deadline = drain_deadline
                        .get_or_insert_with(|| Instant::now() + Duration::from_secs(2));
                    if Instant::now() >= *deadline {
                        break;
                    }
                }
                match listener.accept() {
                    Ok((stream, _)) => {
                        // Speculative Chromium connections must not block the other guest.
                        // Both the worker count and each complete-header read are bounded.
                        if clients.len() >= 8 {
                            continue;
                        }
                        let client_paths = thread_paths.clone();
                        clients.push(thread::spawn(move || serve_fixture(stream, client_paths)));
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        // After guest teardown, finish requests already queued on
                        // our listener before the final evidence snapshot.
                        if thread_stop.load(Ordering::Acquire) {
                            break;
                        }
                        thread::sleep(Duration::from_millis(5));
                    }
                    Err(_) => break,
                }
            }
            for client in clients {
                let _ = client.join();
            }
        });
        Ok(Self {
            origin,
            stop,
            paths,
            thread: Some(server_thread),
        })
    }

    fn finish(&mut self) -> Result<Vec<String>> {
        self.stop.store(true, Ordering::Release);
        if let Some(server_thread) = self.thread.take() {
            server_thread
                .join()
                .map_err(|_| "fixture HTTP server thread failed")?;
        }
        Ok(self.paths.lock().map_err(|_| "fixture path lock")?.clone())
    }
}

fn serve_fixture(mut stream: TcpStream, paths: Arc<Mutex<Vec<String>>>) {
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut header = Vec::new();
    let mut buffer = [0u8; 2048];
    while !header.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
        if Instant::now() >= deadline || header.len() >= 8192 {
            return;
        }
        match stream.read(&mut buffer) {
            Ok(0) => return,
            Ok(length) => header.extend_from_slice(&buffer[..length]),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) => {}
            Err(_) => return,
        }
    }
    let request = String::from_utf8_lossy(&header);
    let path = request
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("invalid")
        .to_owned();
    paths.lock().expect("fixture path lock").push(path);
    let body = "<!doctype html><html><head><title>Hermes disposable guest fixture</title></head><body>Local native feasibility fixture</body></html>";
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'\r\nCache-Control: no-store\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()
    );
    let _ = stream.write_all(response.as_bytes());
}

impl Drop for FixtureServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(server_thread) = self.thread.take() {
            let _ = server_thread.join();
        }
    }
}

#[derive(Default)]
struct Evidence {
    loaded: [bool; 2],
    started: bool,
    awaiting_navigation: bool,
    awaiting_popup: bool,
    awaiting_denial: bool,
    snapshots: BTreeMap<&'static str, Snapshot>,
    navigation_events: Vec<Value>,
    popup: Option<Value>,
    controls: Option<Value>,
    completed: bool,
}

const READ_SNAPSHOT: &str = r#"({
    origin: location.origin,
    path: location.pathname,
    document_url: document.URL,
    cookie: document.cookie,
    storage: localStorage.getItem('partition'),
    hermes_bridge: typeof window.hermesDesktop,
    tauri_bridge: typeof window.__TAURI_INTERNALS__,
    ipc_bridge: typeof window.ipc
})"#;

fn evaluate(
    view: &WebView,
    proxy: &EventLoopProxy<FixtureEvent>,
    phase: &'static str,
    marker: Option<&str>,
) -> Result<()> {
    // Only host-controlled literal markers are interpolated; no untrusted renderer source.
    let prefix = marker.map_or_else(String::new, |value| {
        format!("document.cookie='partition={value}; Path=/; SameSite=Strict'; localStorage.setItem('partition','{value}');")
    });
    let source = format!("(() => {{ try {{ {prefix} return {READ_SNAPSHOT}; }} catch (error) {{ return {{fixture_error: String(error), origin: location.origin, path: location.pathname, document_url: document.URL}}; }} }})()");
    let callback_proxy = proxy.clone();
    view.evaluate_script_with_callback(&source, move |value| {
        let _ = callback_proxy.send_event(FixtureEvent::Evaluated { phase, value });
    })?;
    Ok(())
}

fn controller_visible(view: &WebView) -> Result<bool> {
    let controller = view.controller();
    let mut visible = Default::default();
    // SAFETY: controller is owned by this UI thread and the out pointer remains valid for the call.
    unsafe { controller.IsVisible(&mut visible)? };
    Ok(visible.as_bool())
}

fn verify_controls(view: &WebView, parent: &Window) -> Result<Value> {
    view.set_bounds(Rect {
        position: PhysicalPosition::new(13, 17).into(),
        size: PhysicalSize::new(301, 211).into(),
    })?;
    let bounds = view.bounds()?;
    let position = bounds.position.to_physical::<i32>(parent.scale_factor());
    let size = bounds.size.to_physical::<u32>(parent.scale_factor());
    if position != PhysicalPosition::new(13, 17) || size != PhysicalSize::new(301, 211) {
        return Err(format!("native bounds mismatch: {bounds:?}").into());
    }
    view.set_visible(false)?;
    let hidden = !controller_visible(view)?;
    view.set_visible(true)?;
    let shown = controller_visible(view)?;
    let parent_hidden = !parent.is_visible();
    if !hidden || !shown || !parent_hidden {
        return Err("native controller hide/show readback mismatch".into());
    }
    Ok(json!({
        "bounds_pixels": {"x": position.x, "y": position.y, "width": size.width, "height": size.height},
        "hidden_readback": hidden, "shown_readback": shown,
        "parent_hidden_readback": parent_hidden,
        "visually_verified": false
    }))
}

impl Evidence {
    fn handle(
        &mut self,
        event: FixtureEvent,
        views: &[WebView; 2],
        proxy: &EventLoopProxy<FixtureEvent>,
        origin: &str,
        parent: &Window,
    ) -> Result<()> {
        match event {
            FixtureEvent::Loaded { guest, url } => {
                if url == format!("{origin}/initial") {
                    self.loaded[guest] = true;
                    if self.loaded.iter().all(|loaded| *loaded) && !self.started {
                        self.started = true;
                        evaluate(&views[0], proxy, "a_written", Some("A"))?;
                    }
                } else if guest == 0
                    && url == format!("{origin}/navigated")
                    && self.awaiting_navigation
                {
                    self.awaiting_navigation = false;
                    evaluate(&views[0], proxy, "after_navigation", None)?;
                }
            }
            FixtureEvent::Evaluated { phase, value } => {
                let snapshot: Snapshot = serde_json::from_str(&value).map_err(|error| {
                    format!("invalid JS snapshot at {phase}: {error}; value={value}")
                })?;
                let (path, marker) = match phase {
                    "b_clean" => ("/initial", None),
                    "b_written" => ("/initial", Some("B")),
                    "after_navigation" | "after_blocked_navigation" => ("/navigated", Some("A")),
                    "a_written" | "a_recheck" => ("/initial", Some("A")),
                    _ => return Err("unexpected fixture evaluation phase".into()),
                };
                validate_snapshot(&snapshot, origin, path, marker)?;
                if self.snapshots.insert(phase, snapshot).is_some() {
                    return Err("duplicate fixture evaluation".into());
                }
                match phase {
                    "a_written" => evaluate(&views[1], proxy, "b_clean", None)?,
                    "b_clean" => evaluate(&views[1], proxy, "b_written", Some("B"))?,
                    "b_written" => evaluate(&views[0], proxy, "a_recheck", None)?,
                    "a_recheck" => {
                        self.controls = Some(verify_controls(&views[0], parent)?);
                        self.awaiting_navigation = true;
                        views[0].load_url(&format!("{origin}/navigated"))?;
                    }
                    "after_navigation" => {
                        self.awaiting_popup = true;
                        views[0].evaluate_script("window.open('/popup', '_blank');")?;
                    }
                    "after_blocked_navigation" => {
                        if views[0].url()? != format!("{origin}/navigated") {
                            return Err("blocked navigation changed native current URL".into());
                        }
                        self.completed = true;
                    }
                    _ => {}
                }
            }
            FixtureEvent::PopupDenied { guest, url } => {
                if guest != 0 || !self.awaiting_popup || url != format!("{origin}/popup") {
                    return Err("unexpected popup request".into());
                }
                self.awaiting_popup = false;
                self.popup = Some(json!({"requested_url": url, "callback_response": "deny"}));
                self.awaiting_denial = true;
                // Local-only denied URL. The navigation policy rejects before any connection.
                views[0].load_url("http://127.0.0.1:9/outside-fixture")?;
            }
            FixtureEvent::Navigation {
                guest,
                url,
                allowed,
            } => {
                self.navigation_events
                    .push(json!({"guest": guest, "url": url, "allowed": allowed}));
                if !allowed {
                    if guest != 0
                        || !self.awaiting_denial
                        || url != "http://127.0.0.1:9/outside-fixture"
                    {
                        return Err("unexpected denied navigation".into());
                    }
                    self.awaiting_denial = false;
                    evaluate(&views[0], proxy, "after_blocked_navigation", None)?;
                }
            }
        }
        Ok(())
    }
}

fn execute(output: &std::path::Path) -> Result<Value> {
    let started_at = Instant::now();
    let deadline = started_at + Duration::from_secs(45);
    let mut server = FixtureServer::start()?;
    let mut event_loop = EventLoopBuilder::<FixtureEvent>::with_user_event().build();
    let window = WindowBuilder::new()
        .with_title("Hermes isolated guest feasibility fixture")
        .with_visible(false)
        .with_inner_size(tao::dpi::PhysicalSize::new(800, 600))
        .build(&event_loop)?;
    let proxy = event_loop.create_proxy();
    let mut contexts = [
        WebContext::new(Some(output.join("profile-a"))),
        WebContext::new(Some(output.join("profile-b"))),
    ];
    let mut built_views = Vec::new();
    for (guest, context) in contexts.iter_mut().enumerate() {
        let loaded_proxy = proxy.clone();
        let navigation_proxy = proxy.clone();
        let popup_proxy = proxy.clone();
        let allowed_origin = server.origin.clone();
        let view = WebViewBuilder::new_with_web_context(context)
            .with_url(format!("{}/initial", server.origin))
            .with_bounds(Rect {
                position: PhysicalPosition::new((guest * 400) as i32, 0).into(),
                size: PhysicalSize::new(400, 300).into(),
            })
            .with_visible(true)
            .with_devtools(false)
            .with_clipboard(false)
            .with_navigation_handler(move |url| {
                let allowed = allows_navigation(&allowed_origin, &url);
                let _ = navigation_proxy.send_event(FixtureEvent::Navigation {
                    guest,
                    url,
                    allowed,
                });
                allowed
            })
            .with_new_window_req_handler(move |url, _features| {
                let _ = popup_proxy.send_event(FixtureEvent::PopupDenied { guest, url });
                NewWindowResponse::Deny
            })
            .with_on_page_load_handler(move |event, url| {
                if matches!(event, PageLoadEvent::Finished) {
                    let _ = loaded_proxy.send_event(FixtureEvent::Loaded { guest, url });
                }
            })
            // Deliberately NO IPC handler, initialization script, Tauri or Hermes bridge.
            .build_as_child(&window)?;
        built_views.push(view);
    }
    let views: [WebView; 2] = built_views.try_into().map_err(|_| "expected two guests")?;
    let mut evidence = Evidence::default();
    let mut failure = None;
    event_loop.run_return(|event, _, control_flow| {
        *control_flow = ControlFlow::WaitUntil(deadline);
        if Instant::now() >= deadline {
            failure = Some("45 second native fixture deadline expired".to_owned());
        } else if let Event::UserEvent(event) = event {
            if let Err(error) = evidence.handle(event, &views, &proxy, &server.origin, &window) {
                failure = Some(error.to_string());
            }
        }
        if failure.is_some() || evidence.completed {
            *control_flow = ControlFlow::Exit;
        }
    });
    // End owned guest activity and drain accepted/queued requests before deciding
    // whether a denied popup ever reached the server during this complete run.
    // The outer process watchdog still bounds native WebView teardown.
    drop(views);
    drop(contexts);
    drop(window);
    let requested_paths = server.finish()?;
    if requested_paths.iter().any(|path| path == "/popup") {
        failure = Some("denied popup reached the fixture HTTP server".into());
    }
    let passed = failure.is_none() && evidence.completed;
    let report = json!({
        "status": if passed { "passed" } else { "failed" },
        "scope": "hidden-native-webview2-fixture-only",
        "elapsed_ms": started_at.elapsed().as_millis(),
        "wry_version": "0.57.0",
        "tao_version": "0.37.1",
        "webview2_runtime": wry::webview_version().ok(),
        "fixture_origin": server.origin,
        "separate_owned_data_directories": ["profile-a", "profile-b"],
        "snapshots": evidence.snapshots,
        "native_controls": evidence.controls,
        "popup_denial": evidence.popup,
        "navigation_events": evidence.navigation_events,
        "fixture_http_requests": requested_paths,
        "failure": failure,
        "unverified": ["visual composition", "focus and shortcuts", "input forwarding", "screenshots", "dock placement", "downloads", "authentication", "production renderer integration", "Tauri command ACL integration"],
        "guest_bridge_policy": "No IPC handler or Hermes/Tauri bridge installed. Only host-controlled JS evaluation reads fixture results."
    });
    Ok(report)
}

pub fn run() -> Result<()> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() != 1 {
        return Err("usage: hermes-webview2-guest-spike.exe ABSOLUTE_NEW_OUTPUT_DIRECTORY".into());
    }
    let output = PathBuf::from(&arguments[0]);
    if !output.is_absolute() {
        return Err("output directory must be absolute".into());
    }
    // create_dir fails on an existing directory; never reuse a user browser profile.
    fs::create_dir(&output)?;
    fs::write(
        output.join(".fixture-owned"),
        "Hermes disposable WebView2 fixture\n",
    )?;
    let report = match execute(&output) {
        Ok(report) => report,
        Err(error) => json!({"status": "failed", "failure": error.to_string()}),
    };
    fs::write(
        output.join("report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    if report["status"] != "passed" {
        return Err(format!(
            "native fixture failed; see {}",
            output.join("report.json").display()
        )
        .into());
    }
    println!(
        "INFO: native guest fixture passed; evidence: {}",
        output.join("report.json").display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speculative_socket_does_not_block_partial_header_request() {
        let mut server = FixtureServer::start().unwrap();
        let address = server.origin.strip_prefix("http://").unwrap();
        let idle = TcpStream::connect(address).unwrap();
        let mut active = TcpStream::connect(address).unwrap();
        active
            .set_read_timeout(Some(Duration::from_millis(50)))
            .unwrap();
        active.write_all(b"GET /par").unwrap();
        let mut premature = [0u8; 64];
        let error = active
            .read(&mut premature)
            .expect_err("incomplete headers must not get a response");
        assert!(matches!(
            error.kind(),
            std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
        ));
        active
            .write_all(b"tial HTTP/1.1\r\nHost: fixture\r\n\r\n")
            .unwrap();
        active
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut response = String::new();
        active.read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK\r\n"));
        // The speculative connection is still alive; the old serial 250 ms
        // server had to time it out before it could serve the active guest.
        idle.set_nonblocking(true).unwrap();
        let error = idle
            .peek(&mut premature)
            .expect_err("idle socket must remain open");
        assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
        drop(idle);
        assert_eq!(server.finish().unwrap(), vec!["/partial"]);
    }
}
