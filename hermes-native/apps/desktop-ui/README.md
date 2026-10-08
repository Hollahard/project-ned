# Retained Hermes renderer and local profile settings

This package builds the **unchanged pinned Hermes renderer and shared client**, then installs a typed native-host adapter and a separate local-model settings contribution. The Windows Tauri shell has mounted the retained root and contribution shell, displayed the real **backend unavailable** recovery dialog, and exercised the actual settings form through native IPC and SQLite. Hermes chat, agent execution and inference remain disconnected. This is a development integration, not a usable replacement desktop or visual-parity claim.

The pinned upstream revision is `649d6c0391029f35959cfbc240eb3534a6667cf5`. Existing Project Friday UI and user modifications are outside this package. No upstream source or dependency installation is changed. Node 24 uses the already installed upstream build tools; 110 direct dependencies are checked against exact package versions. Retained sources and the transitive lockfile are hashed before and after a build. That does not attest every installed transitive package byte.

## Run and verify

Activate the project environment and select the pinned upstream checkout. From this package:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
if (-not $env:VIRTUAL_ENV) { throw 'Virtual environment inactive' }
$env:HERMES_UPSTREAM_ROOT = 'G:\Personal_Assistant\hermes\hermes-agent'
npm test
npm run verify:upstream
npm run typecheck
npm run test:integration
npm run build
```

No `npm install` is needed for the wrapper. Missing or mismatched installed dependencies fail validation. Untracked upstream source/assets, including ignored files that Vite could bundle, are rejected. Output stays in `dist/`, caches in `.cache/`, and generated typecheck configuration in `.checks/`. The integration suite uses its own ignored test state and caches.

The upstream Vite configuration retains React/ReactDOM resolution, compiler, Tailwind, assets, code splitting and shared-client aliases. The wrapper changes the entry point, adds explicit native-module aliases and the settings contribution, isolates output/cache, disables dotenv reads and reduces build logging. Building does not start the Electron main process, Hermes backend or model.

## Native adapter boundary

`src/host-adapter.ts` derives its explicit subset from the pinned `Window['hermesDesktop']` contract. The [Tauri shell](../desktop-shell/README.md) injects `window.__HERMES_NATIVE_TRANSPORT__` before upstream module side effects run.

| Surface | Current behavior |
| --- | --- |
| 13 backend/bootstrap methods | `api`, `getConnection`, `getConnectionFor`, `getGatewayWsUrl`, `getGatewayWsUrlFor`, `revalidateConnection`, `touchBackend`, `getVersion`, `getBootProgress`, `getRecentLogs`, `getBootstrapState`, `resetBootstrap`, `revealLogs` are forwarded and explicitly reject as unavailable while their production owners remain absent. |
| 3 preview methods | `watchPreviewFile`, `watchDirectory`, `stopPreviewFileWatch` reach a real Rust watcher and lifetime owner. Successful registration requires a native grant. The current default shell has no filesystem grants; fixtures use an explicit private root. |
| 5 retained event subscriptions | `backend-exit`, `connection-applied`, `boot-progress`, `power-resume`, `preview-file-changed`. Subscription transport is real. Preview changes have a real watcher producer; the four lifecycle channels do not imply a running backend or power integration. |

Host requests use `hermes_host_request`. The injected transport adds a per-document identifier. Lifecycle events use `hermes:host:event`; preview events are delivered to the exact owning WebView/document and filtered out of the application-wide event bus. Full document replacement retires the preview owner; hash routing preserves it. Native validation and ownership checks remain necessary: renderer validation is not a security boundary.

Arguments are captured before yielding, preserving profile/connection scope, multipart buffers and explicit null/false values. Event subscriptions support unsubscribe and late-setup disposal. `eventSubscriptionReady()` exposes registration failure. Known serialized capability errors become JavaScript `Error` objects with a readable fixed message; arbitrary child text is not interpolated. Missing host families remain absent. There is no catch-all success proxy, fabricated connection or fabricated model state. [host-capabilities.json](host-capabilities.json) records the finite scope.

The wrapper's feasibility notice remains visible. A mounted shell and honest recovery panel establish bootstrap progress; they do not establish working chat, a backend connection or complete native compatibility.

## Local model profiles

`src/model-profiles-plugin.tsx` registers **Local model profiles** through Hermes's existing plugin context, settings contribution registry and enable/disable inventory. Its route is:

```text
#/settings?tab=plugins&plugin=native-model-profiles%3Aprofiles
```

The contribution calls a separate `hermes_control_request {operation,payload}` command through `src/control-client.ts`. It does not supply a Hermes `getConnection` result or reuse the agent gateway. Its seven operations are `runtime.status`, `profiles.schema`, `profiles.validate`, `profiles.list`, `profiles.get`, `profiles.save` and `profiles.delete`.

The [Rust control host](../../services/control-host/README.md) owns one [CPU Python worker](../../services/control-worker/README.md) in a private Windows Job. A permit is acquired before queueing work. Unknown methods/fields, malformed replies and uncertain transport failures are rejected; mutations are never automatically retried. The worker imports the existing inference `LoadProfile` schema and stores named settings in its own SQLite database, with optimistic revisions, bounded records and atomic initial schema creation. These records are separate from Hermes conversations, connection profiles and future vector memory.

The form covers model name/folder, context, KV-cache size/precision, prefill chunk, batch size and vision. Validation checks schema only. Saving neither opens model files nor measures compatibility, available VRAM or speed. KV-cache precision is distinct from weight quantization; this UI does not quantize model weights or start an ExLlama runtime.

No control service starts unless the native host has an explicit valid `HERMES_NATIVE_CONTROL_CONFIG`. Renderer input cannot choose the interpreter, source roots, database directory, environment or owner-only shutdown method. See the shell's configuration instructions. When unavailable or busy, the form reports a fixed error; Retry connection can recover transient admission contention. Generation fencing prevents stale asynchronous responses from replacing current component state.

## Evidence and remaining gates

The deterministic adapter/baseline tests check the contract, disposal, error normalization and unchanged upstream inputs. Nine integration cases use the real retained registry/route helpers and component; two use the actual isolated Python worker to verify CRUD, optimistic conflict handling and persistence across worker restart. Remaining cases cover plugin lifecycle, errors, busy retry and stale UI state. See [integration scope and invocation](tests/integration/README.md).

Native hidden-WebView checks establish retained bootstrap with the real backend-unavailable dialog and native preview ownership/delivery behavior. The profile observer passed **22 checks**: actual recovery-dialog dismissal, retained settings navigation, React form input, validation, create/list/read/update, explicit delete confirmation and final absence of the fixture record. Read-only calls through the same native control channel confirmed normalized saved fields and advancing revisions. No React crash, uncaught error or unhandled rejection was observed.

Separate native control modes passed **4 unavailable, 13 create and 13 reopen checks**, including persistence across native shell launches and optimistic conflicts. Each configured run verified cooperative worker shutdown, root exit code zero, empty Job membership and both pipe EOFs; the outer native fixture Job also cleaned up. These results exercise an explicitly configured CPU worker, not Hermes agent startup or inference. A hidden window and DOM checks do not prove visual fidelity, accessibility/focus behavior or normal desktop usability.

Open gates include Hermes backend startup/JSON-RPC and source routing; guest browser/partitions/automation; ConPTY; general filesystem/Git; Hermes profile/connection persistence; credentials/OAuth; additional windows/overlays/HUD/pets; notifications/clipboard/capture; themes; update/install/recovery; real inference/catalog integration; vector memory; model profiling/benchmarking and Gaming Mode VRAM evacuation. Reproducible payloads, signed Windows packaging and the rest of the native bridge are also pending.
