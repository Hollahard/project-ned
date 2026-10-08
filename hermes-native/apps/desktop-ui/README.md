# Retained Hermes renderer feasibility slice

This package builds the **unchanged pinned Hermes renderer and shared client** with a small native-host compatibility entry. It does not start Hermes, TabbyAPI, a model, a browser window or a GPU worker. It is not a usable replacement desktop yet.

The pinned source revision is `649d6c0391029f35959cfbc240eb3534a6667cf5`. Existing Project Friday UI and user modifications are outside this package. No upstream source or dependency installation is changed. Node 24's native TypeScript config loader uses the installed upstream build dependencies; 110 direct dependencies are checked against their exact package versions. Upstream lockfile and retained source hashes are checked before and after a build. This checks the direct dependency baseline and unchanged transitive lockfile, not every installed transitive package's integrity.

## Run

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
if (-not $env:VIRTUAL_ENV) { throw 'Virtual environment inactive' }
$env:HERMES_UPSTREAM_ROOT = 'G:\Personal_Assistant\hermes\hermes-agent'
# From this package directory:
npm test
npm run verify:upstream
npm run typecheck
npm run build
```

No `npm install` is needed for this wrapper. It deliberately uses the pinned source checkout's already-installed dependencies; missing or mismatched versions fail with an actionable error. Untracked source and asset files, including gitignored files that Vite could still bundle, are rejected before baseline validation. Future packaging must create a reproducible immutable payload from the same upstream lock, rather than rely on an external user installation.

Build output is confined to `dist/`, cache to `.cache/` and typecheck configuration to `.checks/`. The Vite configuration is loaded unchanged, preserving React/ReactDOM resolution, compiler, Tailwind, emoji/public assets, code splitting and shared-client aliases. The only behavior changes are the wrapper entry, isolated output/cache, disabling dotenv reads and quiet logging. No Electron main process is bundled or started by this command.

## Implemented subset and pending native binding

`src/host-adapter.ts` derives its subset from the pinned `Window['hermesDesktop']` TypeScript contract. It explicitly forwards these methods:

- `api`
- `getConnection`, `getConnectionFor`
- `getGatewayWsUrl`, `getGatewayWsUrlFor`
- `revalidateConnection`, `touchBackend`, `getVersion`
- Event subscriptions: backend exit, connection applied, boot progress, power resume

The future native integration injects `window.__HERMES_NATIVE_TRANSPORT__` before the wrapper starts. It uses command `hermes_host_request` with `{method,args}` and channel `hermes:host:event` with `{name,payload}`. **No Rust Tauri registration is present in this slice.** Native code must independently validate/authorize commands, route ownership, authentication and API endpoints; renderer validation is not a security boundary.

The adapter captures arguments before yielding so an active profile change cannot move a pending operation. It preserves native errors, multipart buffers and explicit null/false values. Subscriptions support unsubscribe and late-setup disposal. The integration may await `eventSubscriptionReady()` after registration; event setup failures are also reported to a diagnostic sink and never fabricated into backend-exit events. When no transport exists, supported-but-unbound methods throw/reject `HERMES_HOST_CAPABILITY_UNAVAILABLE`. Missing methods are absent. There is no catch-all success proxy, fake connection or fabricated GPU data. See `host-capabilities.json` for the explicit scope.

The bridge is installed before upstream `main.tsx` evaluates its store side effects. An always-visible feasibility label describes the incomplete host. An upstream module may fail to initialize because a required host family is not implemented; that is an honest remaining compatibility failure, not a reason to fake a response.

## Missing parity gates

Native WebView2 guest browser (partitions/navigation/capture/automation/popout), ConPTY terminal, filesystem/Git, profile and connection persistence, credentials/OAuth, windows/overlays/HUD/pets, notifications, clipboard/capture, themes, updates/install/recovery, and the remainder of the upstream native bridge are not implemented here. Backend JSON-RPC wiring and live Tauri binding remain separate gates. A successful bundle proves source/dependency feasibility only; it does not prove that Hermes boots, visual parity, native behavior, tool execution, inference or VRAM evacuation works.

The 15 tests comprise 12 deterministic adapter contract tests and three baseline-guard tests. The latter create and remove only their own temporary Git repositories; they do not modify upstream. Adapter regressions cover repeated stale unsubscribe and explicit version-request connection/profile scope. `dist/feasibility-report.json` records the verified source and dependency baseline and explicitly unverified runtime/visual state.

## Native binding continuation

The independent [desktop-shell](../desktop-shell/README.md) now injects this transport in Tauri. Native methods remain explicitly unavailable while the runtime owner is absent. Actual retained import stops at missing `onPreviewFileChanged`; see the [native checkpoint](../../../docs/hermes-native-desktop/NATIVE-BINDING-CHECKPOINT.md). The source/dependency build evidence above remains unchanged.
