# Disposable WebView2 guest feasibility fixture

This Windows-only spike checks the native guest boundary required to replace Hermes Desktop's Electron `<webview>`. It does not integrate the retained renderer or claim browser feature parity.

The fixture creates a hidden Tao parent window and two Wry child WebViews. Each uses a fresh `WebContext` data directory under a newly created `.checks/run-<id>/` folder. Both visit the **same** loopback HTTP origin. It never opens installed browser profiles or starts Hermes, Python services, an inference server, or GPU models.

The guest has **no IPC handler, initialization script, Hermes bridge, or Tauri bridge**. Native `evaluate_script_with_callback` reads host-defined snapshots from the local fixture. Popup and navigation decisions are native callbacks. The local HTTP page has a restrictive CSP and no remote resources. This fixture is not a production browsing security policy: production subresource requests, redirects, downloads, permission prompts, remote authentication, and guest-to-host isolation still need separate review and tests.

## Run

Use a Windows PowerShell terminal in this directory with the project's virtual environment active:

```powershell
. G:\Project_Ned\.venv\Scripts\Activate.ps1
cargo test --offline --locked --quiet
cargo build --offline --locked --quiet
./Run-Fixture.ps1
```

The runner uses `Start-Process -WindowStyle Hidden` and a 75-second deadline. The native event loop has a separate 45-second deadline; the runner also bounds synchronous WebView construction. On timeout it terminates only its newly created fixture process tree. The executable requires a new absolute output directory and refuses to reuse existing directories. Each run retains its own temporary profiles and `report.json` under ignored `.checks/` for diagnosis. Do not use an existing browser profile as output. If Windows sandbox restrictions deny GUI/WebView initialization, record the failure and rerun this exact bounded fixture with approved permissions.

## Evidence gates

A passing report requires:

- Guest A writes cookie and localStorage marker A; guest B is empty at the same origin.
- Guest B writes marker B; guest A still reads marker A.
- Host JS evaluation returns typed snapshots with all three bridge globals absent.
- Native bounds read back the requested rectangle; WebView2 controller visibility reads false and then true while the parent remains hidden.
- Host navigation to a second local page retains A's storage.
- `window.open` reaches the native popup handler, which returns deny, and `/popup` is never fetched.
- A second loopback origin is rejected by the navigation callback and the current native URL/document remains unchanged.

Unit tests exercise evidence failure conditions, navigation allowlist edge cases and speculative/partial HTTP requests. They cannot substitute for the native report. A production bundle or compile success also cannot substitute for native execution. The fixture drops both guest WebViews and their contexts, then stops and drains its owned HTTP listener before collecting the final request list, so teardown requests cannot escape the popup-fetch evidence check. The outer watchdog also bounds that native teardown.

The checked-in [native run evidence](evidence/native-run.json) passed on this Windows host with WebView2 **154.0.4258.62** in **612 ms**. It includes source hashes, all six JS snapshots with their document URLs, native bounds and visibility readbacks, and observed navigation/popup callbacks. Five unit tests, the offline locked build, and `cargo clippy --offline --locked --all-targets --quiet -- -D warnings` passed. Formatting and Clippy needed scoped escalation because the sandbox denied Rust manifest/formatter access; native execution itself passed inside the normal sandbox. The runner observed the fixture process exit. A separate system process inventory was unavailable in the sandbox, so this evidence does not certify that every WebView2 helper process had already exited at that instant.

Revalidation exposed a fixture bug: one synchronous 250 ms HTTP read could close a speculative browser connection before guest B sent its headers, producing an error document and a null snapshot. The server now handles at most eight connections independently, reads complete headers with a two-second per-connection deadline, and drains workers at shutdown. A regression preserves the idle speculative connection while another client sends a partial request. Snapshot validation also rejects an error document even if navigation metadata still names the requested URL; script failures return explicit diagnostic data instead of an unexplained null.

## Unverified work

The hidden fixture does not prove visible composition, focus, keyboard shortcuts, input forwarding, screenshot capture, dock placement, download UX, authentication, the retained Hermes renderer, or Tauri command ACL integration. Controller visibility is a native state readback, not a visual inspection. It uses separate data directories; profile names within a shared WebView2 environment and persistence across application restarts are separate tests.

Pinned API references: [Wry 0.57.0 WebViewBuilder](https://docs.rs/wry/0.57.0/wry/struct.WebViewBuilder.html), [WebContext](https://docs.rs/wry/0.57.0/wry/struct.WebContext.html), [WebViewExtWindows](https://docs.rs/wry/0.57.0/wry/trait.WebViewExtWindows.html), [Tao 0.37.1 event loop](https://docs.rs/tao/0.37.1/tao/event_loop/index.html). Source signatures were verified against the locally cached crates used by this build.
