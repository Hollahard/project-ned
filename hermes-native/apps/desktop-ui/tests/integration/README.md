# Retained settings integration check

Run from the activated project virtual environment with Node 24 and the pinned Hermes checkout's already installed development dependencies:

```powershell
$env:HERMES_UPSTREAM_ROOT = '<absolute pinned Hermes repository>'
node .\hermes-native\apps\desktop-ui\tests\integration\run.mjs
```

The runner uses the desktop UI package containing this test directory and the sibling `services/control-worker` and `services/inference/src`. Optional explicit overrides are `HERMES_NATIVE_DESKTOP`, `HERMES_CONTROL_WORKER_ROOT`, and `HERMES_INFERENCE_SRC`. Set `HERMES_BASE_PYTHON` to a trusted base interpreter, or let the runner obtain the base interpreter from the active virtual environment using an isolated, no-site process. No path to a particular developer machine or stage is embedded.

The pinned upstream inspection runs before and after the suite. The test runner imports already installed Vitest, React, jsdom and React Testing Library from that checkout. It does not install dependencies or write upstream files. Vite caches, temporary paths, JSON results and isolated SQLite state stay in ignored `.cache` and `.runs` directories beside this README. Each run creates fresh state directories; a single persistence test explicitly reopens its own directory. Test state can be inspected after the run.

Nine checks exercise the real retained plugin context, inventory, contribution registry and settings route helpers, plus the native profile component and client. Two checks start the real Python control worker over a test-only bounded JSONL transport, with `-I -S -B -X utf8`, explicit source/state directories and only the Windows directory environment variables. They verify create, update, confirmation before deletion, restart persistence and optimistic revision conflicts. Remaining checks verify enable/disable decisions, cleanup, unavailable behavior, retry after transient busy admission, sanitized errors, StrictMode stale responses and deletion followed by list failure.

Unrelated Hermes REST, socket and notification services are explicit tripwires. No `window.hermesDesktop` connection, stock Hermes backend, Tabby runtime, model or GPU process is provided. The Node transport owns and retires only its test worker. Readiness/request/cleanup waits are bounded. The production transport remains Rust-owned.

This suite proves settings contribution registration, retained route resolution, rendered controls and real worker persistence. It does not prove complete Settings navigation, WebView2 layout/focus, Tauri IPC transport, the Windows process Job or model inference. Those require the native fixture and resource-host checks.
