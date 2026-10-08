# Hermes Native: implementation foundation

This directory continues the [approved architecture](../docs/hermes-native-desktop/ARCHITECTURE.md) with isolated, tested feasibility components. The target is the retained Hermes React/TypeScript interface and Python core, a Rust/Tauri 2 Windows host, dedicated ExLlama runtime packs, saved model profiles, vector memory and Gaming Mode.

**This is not yet an installable replacement desktop.** The renderer builds unchanged; native and inference primitives are tested independently. They are not yet connected into an application. Existing `apps/desktop`, `services/core`, installed Hermes/Tabby source and user state remain separate.

| Component | What exists | What it does not establish |
| --- | --- | --- |
| [desktop-ui](apps/desktop-ui/README.md) | Unchanged pinned renderer build, typed host subset, bootstrap and event tests | Working Hermes startup, complete native bridge or visual parity |
| [gateway contracts](tests/gateway/README.md) | Original shared client exercised with deterministic fixtures and real loopback WebSocket exchange | Full Python handler parity, authentication or production route ownership |
| [resource-host](services/resource-host/README.md) | Rust Job ownership, suspended startup, isolated environment, permanent retirement and crash cleanup | Durable coordinator, authenticated IPC or measured VRAM evacuation |
| [backend-host](services/backend-host/README.md) | Atomic Windows process ownership, bounded captured I/O, authenticated fixture readiness and cleanup | Actual Hermes startup, full retained HTTP/WebSocket behavior or a production supervisor |
| [terminal-host](services/terminal-host/README.md) | Real ConPTY Unicode I/O, resizing, bounded buffering and owned tree cleanup | Retained xterm/Tauri integration or a hard native teardown deadline |
| [WebView2 guest](spikes/webview2-guest/README.md) | Real hidden child views, storage isolation, navigation, popup denial and native state readbacks | Focus, visible composition, capture, docking or production browser parity |
| [inference](services/inference/README.md) | Immutable load snapshots, strict V3 observation and SSE handling, serialized generation leases | Live GPU qualification, V2 support, saved-profile UI or host-wide ownership |
| [managed V3 overlay](runtime-packs/tabby-v3/README.md) | Environment-only auth, safe request logging and explicit managed observations in a hash-guarded candidate | A deployed runtime pack or whole-system secrecy/compatibility certification |

## Verify

Use Windows, an activated Python 3.12 development environment, Node 24, Rust and the pinned Hermes checkout with its dependencies provisioned. The scripts do not install into the upstream checkout. Cargo lockfiles are committed; use `cargo fetch --locked` separately if a new machine lacks the cached dependencies needed by the offline checks.

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
./hermes-native/scripts/Verify-Foundation.ps1 -UpstreamRoot 'G:\Personal_Assistant\hermes\hermes-agent' -TabbySource 'G:\Project_Ned\runtime\tabbyAPI' -BuildRenderer -NativeFixtures
```

Logs and the generated check summary stay under ignored `hermes-native/.checks/`. Native fixtures create only their own disposable processes and profiles; they do not load models. Windows sandbox restrictions may require scoped permission to run native ownership tests and canonical-path checks. Passing synthetic inference tests is not GPU evidence.

The baseline is Hermes `649d6c0391029f35959cfbc240eb3534a6667cf5`. The managed V3 pack builds from Tabby `2fd6cc76203a66e13042daf7d76e5898b21c1ad8` with an explicitly versioned overlay; the source commit alone does not identify the resulting managed pack.

## Continue

Read the [implementation checkpoint](../docs/hermes-native-desktop/IMPLEMENTATION-CHECKPOINT.md) for verification, remaining gates and the next coherent integration step. M0 still needs baseline interaction/visual captures, and M1 remains open until the full native browser and V3/V2 runtime gates are resolved. Model/profile persistence, vector memory, complete Gaming Mode, Tauri binding and an NSIS `.exe` installer are subsequent work; none is implied by the fixture executables.
