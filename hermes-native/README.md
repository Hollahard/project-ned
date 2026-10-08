# Hermes Native: retained UI and owned local settings

This directory implements the [approved architecture](../docs/hermes-native-desktop/ARCHITECTURE.md): retain Hermes's React/TypeScript interface and Python core, replace Electron with a Rust/Tauri 2 Windows host, and add dedicated ExLlama runtime packs, saved model profiles, vector memory and Gaming Mode.

The retained renderer now mounts in the Tauri shell and shows its actual backend-unavailable recovery dialog. Its **Local model profiles** settings contribution has passed real native form/IPC/SQLite checks. A Rust-owned CPU worker provides bounded schema validation and profile persistence, with verified process cleanup. Native preview watches also have a real producer and window/document ownership.

**This is not yet an installable replacement desktop.** Hermes agent startup, conversations/tools, production inference routing, the complete native bridge and visual parity remain open. Existing `apps/desktop`, `services/core`, installed Hermes/Tabby source and user state remain separate.

| Component | What exists | What it does not establish |
| --- | --- | --- |
| [desktop-ui](apps/desktop-ui/README.md) | Unchanged pinned renderer/shared client, 16-method adapter, five event subscriptions, retained settings contribution, metadata inspection and 12 integration cases | Complete Hermes behavior or visual/focus parity |
| [desktop-shell](apps/desktop-shell/README.md) | Tauri 2 native dispatch/ACL, retained bootstrap, real preview events and 29 native profile/inspection checks | Hermes backend connection, complete host API, signed distribution or installer |
| [preview-watch](services/preview-watch/README.md) | Real file/directory watches, native grants and owner/document lifetime fences | General filesystem/Git or a production source picker; default shell currently grants no roots |
| [control-host](services/control-host/README.md) | Rust-owned CPU worker, pinned host configuration, permit before scheduling, finite correlated IPC and verified Job/pipe cleanup | Hermes gateway, model launch, runtime broker or VRAM evacuation |
| [control-worker](services/control-worker/README.md) | Existing inference schema reused without HTTP/CUDA imports; named SQLite settings, optimistic revisions and atomic initialization | Model-file validation, benchmarks, weight quantization or vector memory |
| [gateway contracts](tests/gateway/README.md) | Original shared client exercised with deterministic fixtures and real loopback WebSocket exchange | Full Python handler parity, authentication or production route ownership |
| [resource-host](services/resource-host/README.md) | Rust Job ownership, suspended startup, explicit environment, bounded captured/framed I/O and permanent retirement | A complete durable coordinator or measured GPU release |
| [owned-http](services/owned-http/README.md) | Socket-to-Job ownership before credentials, finite bounded HTTP and a Rust-owned retained-handler diagnostic | Production HTTP/streaming chat or a Hermes gateway connection |
| [backend-host](services/backend-host/README.md) | Atomic Windows process ownership, captured I/O, authenticated fixture readiness and cleanup | Stock Hermes startup or full retained HTTP/WebSocket behavior |
| [terminal-host](services/terminal-host/README.md) | Real ConPTY Unicode I/O, resizing, bounded buffering and owned tree cleanup | Retained xterm/Tauri integration or a hard native teardown deadline |
| [WebView2 guest](spikes/webview2-guest/README.md) | Hidden child views, storage isolation, navigation, popup denial and native state readbacks | Visible composition, focus, capture, docking or browser parity |
| [catalog-host](services/catalog-host/README.md) | Separate pinned CPU inspector, explicit root grants, native admission and verified cleanup | Model loading, arbitrary path grants or runtime qualification |
| [model-catalog](services/model-catalog/README.md) | Read-only model metadata, shard/header consistency, finite diagnostics and explicit partial results | Load compatibility, full weight hashes or model registration |
| [inference](services/inference/README.md) | Immutable load settings, strict V3 observation/SSE, generation leases and an isolated pure-schema import boundary | Integrated model/runtime ownership, V2 qualification or application profiling |
| [managed V3 overlay](runtime-packs/tabby-v3/README.md) | Environment-only authentication, safe request logging and explicit observations in a hash-guarded candidate | A deployed runtime pack or whole-system secrecy/compatibility certification |

## Current integration and evidence

[The native catalog checkpoint](../docs/hermes-native-desktop/NATIVE-CATALOG-CHECKPOINT.md) records integrated profile-form inspection, 142 native assertions and 478 foundation tests. [The model catalog checkpoint](../docs/hermes-native-desktop/MODEL-CATALOG-CHECKPOINT.md) records the latest read-only artifact inspection and three user-model observations. [The owned backend checkpoint](../docs/hermes-native-desktop/OWNED-BACKEND-CHECKPOINT.md) records the Rust-owned retained HTTP diagnostic: 12 live assertions and verified cleanup after intentional failure. The production shell remains backend-unavailable. [The native profiles checkpoint](../docs/hermes-native-desktop/NATIVE-PROFILES-CHECKPOINT.md) records the retained UI milestone. The new settings service is separate from Hermes's gateway and from its conversation/connection-profile stores. It never fabricates a successful `getConnection`, loads a model, or treats schema validation as artifact/VRAM verification.

The real native profile run dismissed the actual recovery dialog, navigated the retained settings route, entered React controls and verified create/list/read/update/confirmed delete through Tauri and SQLite. Separate native runs verified unavailable behavior and profile persistence across shell launches. Configured workers stopped cooperatively with root exit zero, empty Job membership and both pipe EOFs. The outer fixture Job also verified cleanup.

The pinned source/dependency guard still reports **2,986 unchanged retained source inputs** at Hermes `649d6c0391029f35959cfbc240eb3534a6667cf5`, with 110 direct dependencies checked. This is source-preservation evidence, not proof of complete behavioral parity. Tests run in fresh owned state and hidden WebView profiles; they do not establish visual, accessibility or keyboard/focus parity.

## Verify

Use Windows, an activated Python 3.12 development environment, Node 24, Rust and the pinned Hermes checkout with its dependencies provisioned. Scripts do not install into upstream. Cargo lockfiles are committed; use `cargo fetch --locked` separately when a machine lacks cached dependencies for offline checks.

The foundation runner covers the current component groups; the retained HTTP diagnostic and full native UI suite have separate runners:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
./hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -BuildRenderer -NativeFixtures
```

Use the current [desktop UI](apps/desktop-ui/README.md), [desktop shell](apps/desktop-shell/README.md), [control host](services/control-host/README.md), [control worker](services/control-worker/README.md) and [preview watcher](services/preview-watch/README.md) instructions for the added integration suites. The foundation runner alone does not establish the complete native profile flow.

Native fixtures create only their explicitly owned processes, state and profiles. Windows sandbox restrictions can require scoped execution for native ownership and canonical-path checks. The profile service is opt-in through a host-selected hash-pinned manifest; renderer inputs cannot select its interpreter, code, environment or database. Configuration, state rules and reproducible commands are documented in the shell/control-host packages. No credentials belong in those files.

## Earlier observations and remaining work

The [live runtime checkpoint](../docs/hermes-native-desktop/LIVE-RUNTIME-CHECKPOINT.md) records the first successful Mistral EXL3 model load/generation/unload and a limited unchanged retained HTTP-handler proof. A separate [Qwen3 runtime checkpoint](../docs/hermes-native-desktop/QWEN3-RUNTIME-CHECKPOINT.md) verifies a second model at 2,048 context, including generation, unload and owned cleanup. [Model-proof](spikes/model-proof/README.md) and [backend diagnostics](services/backend-host/diagnostics/README.md) remain opt-in. These GPU observations are separate from the CPU settings worker and do not imply integrated inference. The managed V3 candidate uses Tabby `2fd6cc76203a66e13042daf7d76e5898b21c1ad8` plus an explicitly versioned overlay; the source commit alone does not identify the managed pack.

The [implementation foundation](../docs/hermes-native-desktop/IMPLEMENTATION-CHECKPOINT.md) and [first native binding checkpoint](../docs/hermes-native-desktop/NATIVE-BINDING-CHECKPOINT.md) remain historical records. The earlier missing-`onPreviewFileChanged` bootstrap gate has been resolved by the real preview subscription/producer and explicit bootstrap error methods. Its old empty-root observation must not be read as the current state.

M0 still needs baseline interaction/visual captures. M1 remains open for full native browser behavior, runtime/owner integration and V3/V2 qualification. Saved local settings are now implemented; manual inference profiling, artifact registration/load qualification, quantization jobs, vector memory, complete Gaming Mode admission/draining/recovery, fallback switching, hibernation and an NSIS Windows installer remain future work. A compiled development executable or successful unload observation does not close those gates.
