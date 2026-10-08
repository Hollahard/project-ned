# Implementation checkpoint: verified foundations, integration incomplete

Checkpoint: 8 October 2026 UTC, following the explicitly resumed implementation work. Read this with the [approved architecture](./ARCHITECTURE.md), [reconciliation](./RECONCILIATION.md), and [implementation package](../../hermes-native/README.md).

The selected design remains the existing Hermes React/TypeScript renderer and Python agent, hosted by Rust/Tauri 2 on Windows. Separate managed TabbyAPI runtime packs will supply ExLlamaV3 and legacy V2. Vector memory, saved model profiles and Gaming Mode remain product work. The present deliverable is tested implementation foundations: it is not an installed replacement desktop, a complete Tauri integration, or a distributable application `.exe`.

The original [documentation-only checkpoint](./CHECKPOINT.md) is historical and remains unchanged. Its statement that implementation had not started describes that earlier stopping point. This document records the subsequent work without rewriting the earlier evidence.

## Source and delivery boundary

| Item | Identity or scope |
| --- | --- |
| Retained Hermes baseline | `649d6c0391029f35959cfbc240eb3534a6667cf5` |
| V3 Tabby source | `2fd6cc76203a66e13042daf7d76e5898b21c1ad8` |
| Managed V3 observation contract | `hermes-native-observation-v1` |
| Managed runtime identifier | `tabby-v3:2fd6cc76203a66e13042daf7d76e5898b21c1ad8:hermes-native-observation-v1` |
| Implementation namespace | `hermes-native/`, separate from the existing Friday `apps/desktop` and `services/core` |
| Working evidence | Isolated staging under `G:\Project_Ned\.soak_workspace\`; installed Hermes/Tabby trees were reference inputs |
| Delivery branch | `codex/hermes-native-foundation`; the evidence snapshot fingerprints the 80 verified implementation files |

The overlay identifier does not attest a whole environment. The builder's source/overlay hashes, engine wheels, Python/Torch/CUDA versions and the eventual pack manifest must agree before live admission. The renderer wrapper's source check also does not establish a final preservation percentage for the complete application; continue using the architecture's frozen denominators.

The original dirty files are excluded from this implementation scope: `apps/desktop/src-tauri/src/lib.rs`, `apps/desktop/src-tauri/src/proxy.rs`, `apps/desktop/src-tauri/tauri.conf.json`, and `apps/desktop/vite.config.ts`. They remain user work. No reset, overwrite or integration into those files is implied by this checkpoint.

## Verified component results

The final managed-worktree run of the [foundation verifier](../../hermes-native/scripts/Verify-Foundation.ps1) completed **26 check groups and 256 component tests successfully at `2026-10-08T03:19:38.3833881Z`**. Renderer building and native fixtures were enabled; GPU tests were explicitly not requested. This includes backend-host tests, lint and formatting. The [portable verification snapshot](./implementation-evidence/foundation-verification.json) records tool versions, log hashes, component counts and 80 source fingerprints normalized to Git LF newlines. The machine logs remain in ignored `hermes-native/.checks/`; the timestamp identifies a verification run, not a release.

Earlier evidence remains historical: the assembled staging run passed 23 groups at `2026-10-08T03:14:25.9614102Z`, and the initial backend-host suite passed 24 tests separately. The final run adds backend-host to the consolidated verifier and uses its expanded 29-test suite, including additional cleanup-failure coverage. It does not retroactively expand those earlier runs.

| Component | Verified result | Remaining boundary |
| --- | --- | --- |
| [Retained renderer wrapper](../../hermes-native/apps/desktop-ui/README.md) | 15 tests: 12 adapter tests and 3 baseline guards; upstream typecheck and production bundle passed. The bundle retained 2,986 selected source inputs and checked 110 direct dependency versions. | No live Hermes startup or complete native bridge. Compilation is not visual or interaction parity. |
| [Gateway contracts](../../hermes-native/tests/gateway/README.md) | 19 tests of the unchanged shared JSON-RPC/WebSocket client, including an actual owned loopback WebSocket exchange. | Deterministic payloads do not exercise all 252 methods or the real Python handlers/authentication. |
| [Rust resource ownership](../../hermes-native/services/resource-host/README.md) | 8 tests, including owner crash, descendants, unrelated-process survival and suspended-spawn versus permanent-retirement synchronization; formatting and Clippy passed. | No durable resource coordinator, captured readiness channel or VRAM-release measurement. |
| [ConPTY terminal host](../../hermes-native/services/terminal-host/README.md) | 7 actual native tests; Unicode/VT byte transport, resize, bounded buffering and owned cleanup. | No retained xterm/Tauri connection or guaranteed hard deadline for every native teardown path. The component README preserves a nonreproduced timeout and subsequent repeated passes. |
| [WebView2 guest](../../hermes-native/spikes/webview2-guest/README.md) | 5 tests and a real hidden native run. Separate data directories isolate cookies/localStorage at the same fixture origin; navigation, evaluation, denied popups, bounds and visibility readbacks passed. | No visible composition, focus, keyboard/input forwarding, screenshot, docking, download or production Tauri ACL proof. |
| [Inference control](../../hermes-native/services/inference/README.md) | 112 tests, including 13 pinned-source AST characterizations, plus lint/format checks. | Mock HTTP transport and harmless upstream AST stubs do not qualify an engine, GPU or runtime pack. |
| [Managed V3 overlay](../../hermes-native/runtime-packs/tabby-v3/README.md) | 61 tests with pinned-source characterization enabled; lint/format and the pinned configuration-schema validator passed. | A reviewed overlay candidate is not an installed or fully certified runtime. |
| [Backend-host fixture](../../hermes-native/services/backend-host/README.md) | 29 tests passed in the final 26-group run, including actual authenticated loopback HTTP through an owned Windows child and cleanup-failure cases. | Installed Hermes was not launched; fixture responses are synthetic. |

The [renderer build report](./implementation-evidence/retained-renderer-build.json) records source aggregate `7a6c24f0b7dd1383baac61169eafedb7cb212229f1775b9eb667b6a167e7b968`. The [final-worktree WebView report](./implementation-evidence/webview-native-verification.json) records WebView2 `154.0.4258.62` and a 491 ms fixture run; the component also retains its earlier 612 ms staging report. These durations are fixture observations, not desktop startup latency or performance promises. The outer runner observed fixture exit; a complete WebView helper-process inventory was unavailable.

## What the new components establish

The renderer wrapper injects a typed `hermesDesktop` subset before the unchanged upstream entry point evaluates its stores. The proposed native transport is `hermes_host_request` with `{method,args}` and `hermes:host:event` with `{name,payload}`. Rust command registration is still absent. Unsupported methods are absent or explicitly unavailable; no catch-all success, fake connection or fabricated model state fills a missing host family.

The Rust resource host starts children suspended, assigns its own non-inheritable Job Object, then resumes execution. Its lifecycle mutex covers create/assign/resume and retirement. Once retirement begins, the group cannot spawn again, including after a kernel termination error. Processes are controlled through owned handles, with explicit environments and literal arguments. A Job Object provides lifetime control; it does not restrict filesystem or network access.

The inference controller serializes control operations and generation leases, verifies model identity against the absolute `/props` path, and handles interrupted or uncertain load/unload operations conservatively. Same-model parameter changes require an unload/reload transaction because upstream can short-circuit a load for the already-loaded directory. Chunk size must be 256-aligned. Reported cache aliases follow actual upstream behavior rather than permissive user-input normalization.

Managed observation requires `parameters.hermes_native_draft_enabled` to be the boolean `false` before readiness. Missing/null/wrong-type observations reject stock or incompatible runtimes; enabled drafting and observed draft SSE components reject this unsupported configuration. The overlay derives the field from effective draft-model or n-gram settings. A stock `draft: null` response cannot establish disabled drafting. These checks are control-contract evidence, not independent attestation of a server returning the data.

## M2 backend-host fixture and the stock-startup blocker

The separate backend-host proof uses an atomic Windows `JOB_LIST` and a narrow inherited `HANDLE_LIST`, drains stdout/stderr concurrently, and parses complete bounded readiness lines. The accepted upstream sentinels are `HERMES_BACKEND_READY port=N` and the legacy `HERMES_DASHBOARD_READY port=N`; dual announcements must agree. A port announcement is followed by authenticated application/identity checks. Windows venv redirectors can launch a different serving PID, so the fixture verifies that observed PID belongs to the already-owned job without adopting or killing it by PID.

The fixture tests early exit, malformed/conflicting/truncated readiness, output limits, stderr flooding, credential rejection, environment/handle isolation, descendant cleanup, independent-job survival and cleanup-verification failures. Raw child log contents are not persisted. This Python launcher is a proof of captured-pipe requirements; production should consolidate those requirements into the Rust host rather than create competing process owners.

**Stock `hermes serve --host 127.0.0.1 --port 0 --isolated` is not a cleared zero-persistence/no-global-reaping launch mode.** The following findings are from the pinned source, not effects observed by launching the installed application:

| Source anchor at Hermes `649d6c0` | Consequence for the proposed isolated proof |
| --- | --- |
| [`hermes_cli/web_server.py:1465`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/hermes_cli/web_server.py#L1465); `_publish_host_rendezvous` at 1320–1371 | Publication runs even with `--isolated`; the function has no isolation bypass and may claim/reclaim a host lock. |
| [`gateway/host_rendezvous.py:498`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/gateway/host_rendezvous.py#L498) | The generated session credential is written to `host-serve.token`. A fresh home confines that file but does not satisfy zero credential persistence. |
| [`hermes_cli/web_server.py:1410`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/hermes_cli/web_server.py#L1410) | Orphan-MCP sweeping is unconditional. Omitting the desktop-owned flag avoids a different sweep, not this one. |
| [`hermes_bootstrap.py:588`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/hermes_bootstrap.py#L588), through 613 | Launch preparation, recovery and dependency activation precede ordinary CLI dispatch. Disabling lazy installs does not prove all runtime-store/lease writes are disabled. |
| [`hermes_cli/web_server.py:220`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/hermes_cli/web_server.py#L220), 283–304 and 1630–1632 | Hosted-room recovery, local-runtime/free-tier bootstrap and auth keepalive require explicit policy; they are not excluded by a fresh home alone. |
| [`tui_gateway/server.py:55`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/tui_gateway/server.py#L55), 421; [`chat_ws.py:705`](https://github.com/NousResearch/hermes-agent/blob/649d6c0391029f35959cfbc240eb3534a6667cf5/hermes_cli/web_routers/chat_ws.py#L705) | Gateway import loads project dotenv and starts an idle-session reaper; the first gateway WebSocket can trigger deferred MCP discovery. Direct web-server import alone is insufficient isolation. |

A future managed diagnostic entry point must explicitly replace startup orchestration in a hash-guarded copy, keep the installed source unchanged, prohibit all global orphan sweeps and token-file publication, exclude updater/installer paths, and audit import-time/background hooks. It should initially allow only audited read-only handlers before dispatch. That mode is a retained-handler subset, not stock-startup or full Chat/Settings/History parity. The [backend-host README](../../hermes-native/services/backend-host/README.md) describes the proposed seam and remaining audit.

## Milestone status and next coherent step

| Milestone | Checkpoint status | Exit work still required |
| --- | --- | --- |
| M0 baseline | Partial | Actual baseline screenshots/interaction recordings, runnable Windows acceptance cases and final licensed dependency inventory. Source inventories and retained-client characterization already exist. |
| M1 feasibility | Partial | Visible browser/input/capture behavior, retained xterm integration, full native boundary decisions, real V3 qualification, independent V2 qualification and all auxiliary GPU producers. |
| M2 shell/host | Foundation started | Register authenticated native commands/events; integrate owned startup/readiness, connection/profile routing and unchanged client; then prove real Chat/Settings/History workflows under the reviewed managed policy. |
| M3–M8 product work | Not completed by these fixtures | Full native parity, catalog/runtime registry, profile persistence/UI/quantization, vector memory, durable Gaming Mode, signed updates and installer/migration. |

The next coherent integration slice is a single owned host path: retained adapter → validated native request/event transport → owned backend startup and authenticated readiness → unchanged shared client with audited session-list/reconnect behavior. First use the harmless fixture to prove failure/cleanup boundaries. Bring in the reviewed real-handler diagnostic separately and label its evidence. Then expand to actual session and settings workflows without replacing the upstream UI.

Gaming Mode still needs a durable admission latch, all GPU producer registration, cooperative cancellation and checkpointing, bounded unload/escalation, post-cleanup telemetry, certified small-model selection and restoration. No result here establishes instant VRAM evacuation or GPU hibernation.

## GPU evidence: pending external qualification

No real model load, generation, unload, OOM or VRAM-release result is incorporated in this checkpoint. A separately prepared bounded model-proof harness is under review. The selected model path and installed dependency versions are inputs to that proof, not proof that it ran successfully. The integration owner must append the actual managed-pack manifest, exact model identity, hardware/runtime versions, authentication checks, effective settings, bounded generation, cleanup observations and raw measured samples before marking any GPU gate passed.

Do not infer V2 support from a V3 result. The architecture's legacy V2 candidate remains a separate runtime and certification task. Do not infer a working desktop or complete Gaming Mode from either engine proof.

## Reproducing the foundation checks

Use Windows with PowerShell 7+, an activated Python 3.12 development environment, Node 24, Rust, WebView2, and provisioned dependencies for the pinned Hermes and Tabby source. The verifier requires both source paths so real-upstream characterization does not silently skip:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
./hermes-native/scripts/Verify-Foundation.ps1 `
  -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' `
  -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' `
  -BuildRenderer -NativeFixtures
```

The wrapper reads the installed upstream dependency tree; it does not provision a fresh independent frontend environment. Direct dependency versions and retained lockfile hashes are checked, but every installed transitive file is not attested. Rust checks use lockfiles/offline mode; a new machine must provision cached crates and required formatter/Clippy components separately. Python test tools and dependencies must already be present. Sandbox-denied native/path checks were rerun with narrowly scoped permission; a denied run is not a passing test.

Logs, temporary test directories and generated bundles stay in package-owned ignored locations. The consolidated runner records optional omissions explicitly and does not invoke GPU tests. Its final worktree run includes backend-host's 29 tests and separate lint/format groups. These checks do not install, update or replace an application.

## Live runtime continuation

See [the live runtime checkpoint](LIVE-RUNTIME-CHECKPOINT.md) for measured EXL3 load/generation/unload and the retained configuration/session HTTP subset. The foundation evidence above remains historical; the replacement desktop, full startup, V2 and feature UI gates remain open.

The [native binding continuation](NATIVE-BINDING-CHECKPOINT.md) adds a verified Tauri transport slice; retained bootstrap remains blocked at a missing native event method.
