# Hermes Native Desktop engineering specification

**Start with [the complete architecture and roadmap](./ARCHITECTURE.md).** For current implementation progress, read [the native catalog checkpoint](./NATIVE-CATALOG-CHECKPOINT.md), [the model catalog checkpoint](./MODEL-CATALOG-CHECKPOINT.md), [the owned backend checkpoint](./OWNED-BACKEND-CHECKPOINT.md), [the native profiles checkpoint](./NATIVE-PROFILES-CHECKPOINT.md) and [the implementation overview](../../hermes-native/README.md).

The original specification was prepared on 7 October 2026 from installed official Hermes source at `649d6c0391029f35959cfbc240eb3534a6667cf5`, with official Hermes, TabbyAPI, ExLlama, Tauri and database references. The separate `hermes-webui` installation is identified but is not the official desktop baseline.

## Selected approach

- Keep the existing React/TypeScript interface, as agreed, and the Python agent core.
- Replace Electron's host with Rust/Tauri 2 and explicit Windows browser, terminal and OS adapters.
- Add a dedicated broker over separately pinned ExLlamaV3 and legacy ExLlamaV2 TabbyAPI runtime packs.
- Add SQLite/`sqlite-vec` memory through a provider plugin; retain PostgreSQL/pgvector as an alternative adapter.
- Provide saved model settings, manual inference tests, measurements and offline quantization jobs.
- Provide Gaming GPU-off and certified small-model modes with a persistent admission barrier, measured release and logical session restoration.

The selected TabbyAPI baseline rejects V2, so the proposed V3/V2 runtime-pack split remains necessary; source evidence and the design are in architecture sections 8–9. A native Windows `.exe` is the distribution target. Tauri renders the retained interface in a WebView; large inference dependencies remain separately versioned packs.

## Current implementation boundary

The retained renderer now mounts in the Tauri shell and shows a genuine backend-unavailable recovery dialog. Real preview watchers deliver changes to their owning native window/document. A separate Rust-owned CPU Python service persists local model settings with the reused inference schema, strict bounded IPC, optimistic revisions and atomic SQLite initialization.

The actual retained settings form passed 29 native checks covering navigation, validation, CRUD with confirmed deletion and separate owned metadata inspection. The full native suite passed 142 assertions; the foundation runner passed 48 groups and 478 component tests. Separate native checks verified unavailable behavior and persistence across shell launches. Configured workers and their outer fixture Jobs verified process/pipe cleanup. The source guard still reports 2,986 unchanged retained inputs and 110 pinned direct dependencies.

Hermes agent startup, chat/tools, integrated inference, browser/terminal parity, vector memory, Gaming Mode and installer packaging remain open. The Mistral and Qwen3 EXL3 GPU smoke tests are separate recorded observations, not connections between the new settings UI and a running model. Hidden DOM checks and source reuse do not prove full visual or behavioral parity.

## Document map

| Artifact | Purpose |
| --- | --- |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Current-design analysis, implementation-independent contracts, feature designs, Windows migration, twenty work packages and test gates |
| [EVIDENCE.md](./EVIDENCE.md) | Source anchors, official references and source/comment discrepancies |
| [FEATURE-REVIEW.md](./FEATURE-REVIEW.md) | Independent additional-feature review begun after the first 15 planned sections; seven findings and follow-up verification |
| [CHECKPOINT.md](./CHECKPOINT.md) | Historical boundary of the completed research/specification deliverable |
| [VERIFICATION.md](./VERIFICATION.md) | Verification scope of the original documentation deliverable |
| [IMPLEMENTATION-CHECKPOINT.md](./IMPLEMENTATION-CHECKPOINT.md) | Historical implementation foundation and independent feasibility components |
| [RECONCILIATION.md](./RECONCILIATION.md) | Relationship between the architecture and implementation milestones |
| [LIVE-RUNTIME-CHECKPOINT.md](./LIVE-RUNTIME-CHECKPOINT.md) | One opt-in EXL3 GPU qualification and unchanged retained HTTP-handler subset |
| [NATIVE-BINDING-CHECKPOINT.md](./NATIVE-BINDING-CHECKPOINT.md) | Historical first Tauri IPC/event/ACL proof and the then-observed missing-preview bootstrap gate |
| [NATIVE-PROFILES-CHECKPOINT.md](./NATIVE-PROFILES-CHECKPOINT.md) | Integrated preview, retained bootstrap and Rust-owned CPU profile settings evidence |
| [OWNED-BACKEND-CHECKPOINT.md](./OWNED-BACKEND-CHECKPOINT.md) | Rust-owned retained HTTP diagnostic, socket ownership before authentication and failure-cleanup evidence |
| [MODEL-CATALOG-CHECKPOINT.md](./MODEL-CATALOG-CHECKPOINT.md) | Bounded read-only artifact metadata/header inspection, partial reports and actual model observations |
| [NATIVE-CATALOG-CHECKPOINT.md](./NATIVE-CATALOG-CHECKPOINT.md) | Integrated owned inspection, retained profile-form behavior and final regression evidence |
| [NEXT-BACKEND-INTEGRATION.md](./NEXT-BACKEND-INTEGRATION.md) | Proposed retained backend/gateway integration sequence and source-side-effect audit |
| [NATIVE-SOCKET-TEST-PLAN.md](./NATIVE-SOCKET-TEST-PLAN.md) | Proposed socket/ownership/client acceptance boundaries |
| [QWEN3-RUNTIME-CHECKPOINT.md](./QWEN3-RUNTIME-CHECKPOINT.md) | Second opt-in EXL3 model load/generation/unload and measured owned cleanup |
| [baseline-inventory.json](./baseline-inventory.json) | Static baseline of 252 RPC methods, 13 server requests, 77 notifications and 259 literal preload channels |
| [contracts/gateway-baseline.openrpc.json](./contracts/gateway-baseline.openrpc.json) | Complete pinned method/request/event schemas; upstream license beside them |
| [source-manifest.json](./source-manifest.json) | Hashes of inspected source evidence |
| [retention-baseline.json](./retention-baseline.json) | Frozen hashes and denominator for source-preservation measurement |
| [review-checkpoint.json](./review-checkpoint.json) | Original draft hash and section/word-count checkpoint at review dispatch |

## Engineering conclusions that remain applicable

Browser guests, native terminals, desktop plugins and updates require explicit parity work. Keeping React alone does not preserve Electron APIs. The preview-bootstrap blocker in the first native checkpoint has now been resolved; this closes that specific gate, not the remainder of the bridge.

Vector memory needs canonical-source validation and reconciliation because deletion/rewind paths can bypass provider callbacks. Gaming Mode must account for local speech and auxiliary GPU consumers as well as the main LLM. Suspending a process, clearing an allocator cache or observing process exit is not itself proof of released VRAM.

The independent feature review's seven findings are integrated in architecture section 19. The plan targets required Windows behavior with a proposed guardrail of at least 85% unchanged eligible Python/renderer files. Changes to the replaced host are reported separately; neither file reuse nor the current 2,986-input build guard demonstrates whole-application parity.

The original specification remains a completed research deliverable. Implementation now exists separately under `hermes-native/`, with the latest results and remaining gates recorded in dated checkpoints. Historical test counts and GPU observations remain attributed to their original runs.
