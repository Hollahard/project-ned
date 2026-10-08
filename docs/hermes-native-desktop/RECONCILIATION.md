# Reconciliation: existing Friday prototype and retained Hermes implementation

This document records how the resumed implementation fits the [approved Hermes architecture](./ARCHITECTURE.md). The [implementation checkpoint](./IMPLEMENTATION-CHECKPOINT.md) records the verified results. It does not replace or retroactively amend the original [documentation checkpoint](./CHECKPOINT.md).

## Selected application boundary

Project_Ned already contains a separate Project Friday Tauri/React application and FastAPI core. That is useful engineering work, but it is not the installed official Hermes Desktop source. The chosen Hermes approach preserves the official renderer/shared client and Python agent; it does not grow the smaller Friday interface until it resembles Hermes.

The implementation therefore lives under [hermes-native](../../hermes-native/README.md). Original `apps/desktop`, its nested `Ned` prototype, and `services/core` remain separate. Reuse is decided per responsibility after source/contract review; a similar feature name is insufficient evidence of equivalence.

| Responsibility | Existing Project_Ned evidence | Reconciled treatment |
| --- | --- | --- |
| Interface | [`apps/desktop/src/App.tsx`](../../apps/desktop/src/App.tsx) defines its own chat/session/runtime/profile view. | Keep as the Friday prototype. Build the pinned Hermes renderer unchanged through the new wrapper. |
| Browser development behavior | [`tauriClient.ts:16`](../../apps/desktop/src/services/tauriClient.ts#L16) checks for Tauri; its browser branch returns synthetic runtime, model/session and Gaming data from line 24. | Browser screenshots or displayed VRAM numbers from this branch are not live inference evidence. New Hermes adapters report unsupported/unbound capabilities explicitly. |
| Prompt submission | [`App.tsx:115`](../../apps/desktop/src/App.tsx#L115) uses a 400 ms timer and a fixed assistant response. | It does not prove a model turn, token streaming, Hermes gateway handling or tool execution. Preserve the real Hermes shared-client path. |
| Native integration | [`src-tauri/src/lib.rs:23`](../../apps/desktop/src-tauri/src/lib.rs#L23) constructs the Friday supervisor; command registration begins at line 68. | Useful Tauri experience, but this does not implement the upstream `hermesDesktop` contract. New host bindings need their own capability and ownership matrix. |
| Proxy boundary | [`proxy.rs:156`](../../apps/desktop/src-tauri/src/proxy.rs#L156) holds native credentials and proxies Friday/Tabby requests. | Preserve the idea of keeping credentials out of renderer state. Revalidate actual auth carriers, route semantics, endpoint scope and model-control ownership before reusing code. |
| Python service | [`friday/api/app.py:40`](../../services/core/src/friday/api/app.py#L40) assembles a separate FastAPI agent/tools/memory application. | It is not the retained Hermes agent. Port useful extension logic behind Hermes provider/broker seams rather than replacing the original core. |
| Process ownership | [`processes.rs:280`](../../apps/desktop/src-tauri/src/processes.rs#L280) and 331 spawn Friday Core/Tabby; [`runtime.rs`](../../apps/desktop/src-tauri/src/runtime.rs) coordinates them. | Ownership ideas are reusable; the current launch path requires changes before it satisfies the approved native invariants. Use the isolated resource-host as the reviewed replacement seam. |
| Gaming Mode | [`friday/inference/gaming_mode.py:76`](../../services/core/src/friday/inference/gaming_mode.py#L76) catches unload failure and later marks mode active at line 93. The UI banner at `App.tsx:313` claims evacuation under two seconds. | These strings and flags cannot certify GPU release. The new architecture requires verified resource state, durable admission and honest failure/uncertainty states. |

These are source findings, not a claim that every Friday component is mocked. The Rust supervisor, HTTP proxy, FastAPI routes, policy, memory and tests are real implementations of that separate application's contracts. Their validity must be assessed within those contracts; passing them does not establish Hermes feature parity.

## Process and credential differences that prevent a direct substitution

The existing `processes.rs` calls `reap_stale_port` before both spawn paths. At lines 225–254 it identifies listeners through `netstat` and invokes `taskkill` by PID. The new host must only terminate its own jobs/handles; a matching port does not establish ownership. No part of the new spike invokes that cleanup path.

The old launch sequence calls `Command::spawn()` before `AssignProcessToJobObject` (`processes.rs:320–323` and 359–362). A child may execute before job assignment. Its `.envs(&sanitized)` calls at 315/354 also do not themselves clear the ambient process environment. An allowlisted map applied with `.envs` is therefore not equivalent to a fresh environment block. These points are concrete reuse gaps; this reconciliation does not edit the existing implementation or invalidate unrelated tests.

The new [resource host](../../hermes-native/services/resource-host/README.md) passes an explicit `CreateProcessW` application path and environment block, creates the child suspended, assigns an owned Job Object, then resumes it. It serializes that sequence with permanent retirement. Separate groups preserve backend and inference lifetimes. The [backend-host proof](../../hermes-native/services/backend-host/README.md) additionally establishes explicit standard-handle inheritance, concurrent pipe draining, readiness parsing, authenticated observed identity and bounded owned cleanup. Consolidate those needs into one production owner rather than retaining two competing supervisors.

The managed Tabby overlay is also a distinct contract. Stock token-file generation/logging is unsuitable for the architecture's ephemeral environment-only credential policy. The new overlay has synthetic canary tests, explicit API/admin separation and hash-guarded effective drafting observation. An arbitrary server answering the same routes does not become trusted because its version string matches.

## What was retained and what was added

| Layer | Retained input | Added implementation and present limit |
| --- | --- | --- |
| Renderer | Official Hermes desktop React/TypeScript and shared source at `649d6c0` | Entry wrapper, typed host subset, capability manifest and pinned-source/dependency checks. Production bundle passes; runtime completeness remains open. |
| Gateway client | Original JSON-RPC channel and WebSocket client | Characterization harness for correlation, reverse requests, replay, reconnect, cancellation and a real local wire exchange. Full backend handlers remain outside this harness. |
| Native lifecycle | Behavioral requirements from the Electron host and architecture | Windows Job ownership, readiness fixture, ConPTY and isolated WebView2 guest primitives. Tauri registration and all host families are not yet implemented. |
| Agent | Official Hermes Python design and frozen gateway contract | Startup safety audit and proposed managed diagnostic policy. The installed application was not launched or modified for this proof. |
| Inference | Pinned Tabby V3 source and actual emitter/settings behavior | Strict control/lease state machine, managed auth/config/observation overlay and upstream AST tests. Hardware qualification is pending. |
| Product extensions | Existing Hermes Local Models/memory integration seams | Architecture only for complete saved profiles, quantization jobs, vector memory and durable Gaming Mode; no completed UI feature is implied. |

The wrapper currently supports only selected connection/API/version methods and backend/connection/boot/power events; consult its [capability manifest](../../hermes-native/apps/desktop-ui/host-capabilities.json) for the exact list. Browser guests, terminal, filesystem/Git, remote routing, credentials/OAuth, multi-window/overlays/HUD, clipboard/capture/audio, plugins and update/bootstrap families require explicit implementation. A feasibility label remains visible; missing methods are not fabricated.

Preservation accounting must distinguish unchanged eligible agent/renderer files from the deliberately replaced Electron host. The stronger proposed 85% unchanged-source guardrail remains an acceptance measure, not a percentage achieved by these new files. A bundle with 2,986 retained inputs demonstrates source feasibility; it does not measure complete behavioral parity or the whole-application replacement denominator.

## Startup policy requires deliberate divergence

The original CLI has legitimate standalone/multiprofile duties that do not fit a proof constrained to no credential files and no global process cleanup. `--isolated` is attach/discovery opt-out, not a sandbox. The [checkpoint's startup evidence](./IMPLEMENTATION-CHECKPOINT.md#m2-backend-host-fixture-and-the-stock-startup-blocker) identifies unconditional host-token publication, orphan-MCP sweeping, update/dependency bootstrap, project dotenv imports and background work.

Do not work around those findings by launching against the user's existing home, creating a fake readiness response, or calling a monkeypatched process stock Hermes. A new managed mode needs an explicit versioned policy and audited source seams. Its first proof should exercise only permitted real handlers, with all excluded startup services listed. Full chat/settings/history parity comes after those behaviors are intentionally restored under the new ownership model.

## Integration order and acceptance

1. Preserve the original dirty-file boundary and retain independent source manifests for the new namespace. Snapshot the final 26-group worktree run at `2026-10-08T03:19:38.3833881Z`, including the expanded 29-test backend-host suite, without relabeling it application success. Retain the earlier 23-group staging run and separate initial 24-test backend-host proof as historical evidence.
2. Integrate the typed transport with one native owner and an authenticated disposable backend fixture. Exercise connection identity, event subscription disposal, startup timeout/failure, restart generations and owned cleanup through the unchanged shared client.
3. Audit and implement the managed real-handler diagnostic separately. Prove no token-file/global-reaper/updater escape, bounded authenticated readiness, isolated filesystem scope and original response semantics. Expand to real session/settings/history behavior only as each gate passes.
4. Complete visible WebView2 and retained xterm tests. Inventory every remaining Electron-dependent host family and give each a runnable Windows acceptance case before declaring M2/M3 parity.
5. Qualify the reviewed V3 runtime on the supplied model with exact effective settings and cleanup evidence. Record GPU observations separately from synthetic/AST tests; qualify V2 independently.
6. Add saved-profile persistence/UI, vector recall and durable Gaming Mode behind the architecture's existing extension seams. Package and sign only after the real application, update/rollback and clean-Windows installer gates pass.

The architecture's original ordering still applies: a narrow M2 ownership fixture can de-risk integration while M1 remains open, but it cannot waive critical M1 exits. The next checkpoint should name each gate's actual evidence rather than relabeling the milestones complete.

## Historical documentation navigation

The original architecture, evidence, review and documentation verification files remain immutable in this staging task. A future documentation integration may add one navigation line to their index: “Implementation continuation: [checkpoint](./IMPLEMENTATION-CHECKPOINT.md) and [reconciliation](./RECONCILIATION.md).” That is a proposed link, not an edit already applied to the historical index.
