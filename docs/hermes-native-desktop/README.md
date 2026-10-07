# Hermes Native Desktop engineering specification

**Start with [the complete architecture and roadmap](./ARCHITECTURE.md).** It covers the installed Hermes Desktop design, the implementation-agnostic behavior contract, and the proposed Python/Rust/Tauri 2 Windows application.

Prepared on 7 October 2026 from the installed official Hermes source at commit `649d6c0391029f35959cfbc240eb3534a6667cf5`, with research from the official Hermes, TabbyAPI, ExLlama, Tauri and database documentation. The separate `hermes-webui` installation is identified but is not used as the official desktop baseline.

## Selected approach

- Keep the existing React/TypeScript interface, as agreed, and the Python agent core.
- Replace Electron's host with Rust/Tauri 2 and explicit Windows browser, terminal and OS adapters.
- Extend the existing Local Models interface with a dedicated broker over separately pinned ExLlamaV3 and legacy ExLlamaV2 TabbyAPI runtime packs.
- Add SQLite/`sqlite-vec` memory through a provider plugin; PostgreSQL/pgvector remains an alternative storage adapter.
- Add saved model profiles, manual inference tests, measurements and offline quantization jobs.
- Add Gaming GPU-off and certified small-model modes with a persistent admission barrier, actual release verification and logical session restoration.

Current TabbyAPI main rejects V2, so one unmodified current runtime cannot satisfy both engine requirements. The proposed pack split and its source evidence are detailed in sections 8–9. A native `.exe` is the distribution target; Tauri's interface is still a webview, and the large inference dependencies are versioned runtime packs.

## Document map

| Artifact | Purpose |
|---|---|
| [CHECKPOINT.md](./CHECKPOINT.md) | Completed documentation boundary, commit scope and instructions for a future explicit continuation |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Twenty sections: current design, domain contracts, feature designs, Windows migration, twenty work packages, milestones, test matrix and risks |
| [EVIDENCE.md](./EVIDENCE.md) | Source paths/line anchors, official references and source/comment discrepancies |
| [FEATURE-REVIEW.md](./FEATURE-REVIEW.md) | Independent additional-feature review started after the first 15 planned sections; seven findings and follow-up verification |
| [VERIFICATION.md](./VERIFICATION.md) | What was verified for this documentation deliverable and what remains future implementation testing |
| [baseline-inventory.json](./baseline-inventory.json) | Static inventory of 252 RPC methods, 13 server requests, 77 notifications and 259 literal preload channels |
| [contracts/gateway-baseline.openrpc.json](./contracts/gateway-baseline.openrpc.json) | Complete pinned baseline method/request/event schemas for implementation-independent reference; upstream license included beside it |
| [source-manifest.json](./source-manifest.json) | Hashes of inspected source evidence |
| [retention-baseline.json](./retention-baseline.json) | Frozen file hashes and denominator for source-preservation measurement |
| [review-checkpoint.json](./review-checkpoint.json) | Draft hash and section/word-count checkpoint at review dispatch |

## Important engineering conclusions

Browser guests, native terminals, desktop plugins and update behavior require explicit parity work. Keeping React alone does not preserve Electron APIs. Vector memory needs canonical-source validation and reconciliation because deletion/rewind paths can bypass provider callbacks. Gaming Mode must include local speech and auxiliary GPU consumers as well as the main LLM. Suspending a process or clearing an allocator cache is not equivalent to releasing its VRAM.

The independent review's seven findings are integrated in section 19. The plan targets all required Windows behavior, with a stronger proposed guardrail of at least 85% unchanged eligible Python/renderer files. Whole-application changes, including the replaced host, are reported separately; file reuse is not proof of behavioral parity.

This package is the completed research/specification deliverable. It does not contain a built replacement `.exe`, downloaded models or verified GPU performance. No installed application code was changed. The implementation begins with the M0 baseline and M1 native/GPU feasibility gates defined in the roadmap.
