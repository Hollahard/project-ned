# Changelog

All notable changes to **Project Friday (Project Ned)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-07

### Initial Release: Sovereign Windows Desktop Agent Harness (RTX 5090 Blackwell)

Project Friday v1.0.0 delivers a sovereign, offline-first AI desktop agent platform engineered specifically for the NVIDIA GeForce RTX 5090 (32 GB GDDR7) on Windows 11. Built with a Tauri 2 Rust supervisor, a Python FastAPI core, local TabbyAPI + ExLlamaV3 inference, and strict kernel-enforced process sandboxing.

### Added

#### Phase 1: Local Inference Qualification (`8cea925`)
- Qualified TabbyAPI + ExLlamaV3 on NVIDIA GeForce RTX 5090 (Blackwell `sm_120`, 32 GB GDDR7).
- Supported local 24B–30B EXL3 quantized models with streaming throughput (~94.5 tokens/sec).
- Verified zero memory leaks across 20 consecutive load/unload stress cycles.
- Formulated and documented ADR-0001 (Pinned Inference Runtime).

#### Phase 2: Core Headless Integration (`9713054`)
- Bidirectional WebSocket event hub for turn requests and real-time streaming envelopes.
- Non-blocking turn cancellation (`session.cancel()`).
- Dead inference resilience with graceful connection recovery.
- Per-launch Bearer token authentication on all Core API routes.

#### Phase 3: Tauri 2 Supervisor & Reverse Proxy (`cd36496`)
- Host-level supervisor process guardian in Rust (`apps/desktop/src-tauri`).
- Windows Job Object containment with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and breakaway prevention.
- Loopback reverse proxy shielding inference and admin tokens from WebViews.
- Native Win32 system modal dialog approvals (`MB_SYSTEMMODAL`, `MB_DEFBUTTON2`).
- Cryptographic HMAC-SHA256 single-use capability token exchange with strict 120s TTL.

#### Phase 4: Desktop UI Shell & Messaging Layout (`8e6fbab`)
- Modern desktop client built with React 19, Vite, and Tailwind CSS.
- Multi-turn conversational timeline with markdown rendering and syntax highlighting.
- Real-time token context budget gauge and generation latency counters.
- Streaming assistant deltas and thinking/reasoning inspection drawer.

#### Phase 5: Hardware Telemetry, Settings & Gaming Mode (`4bebb61`)
- NVML real-time hardware telemetry provider for GPU utilization, VRAM, and wattage.
- One-click Gaming Mode: aborts in-flight turns and evacuates model from VRAM to release memory for gaming.
- Comprehensive desktop settings drawer for model profiles, KV-cache quantization, and approval policies.

#### Phase 6: Core Tool System & Policy Guardrails (`985c1d9`)
- Unified tool registry with strict JSON schema validation.
- NTFS boundary enforcement using native `GetFinalPathNameByHandleW` to reject directory traversal and junction attacks.
- Read-only filesystem tools (`filesystem.read`, `filesystem.list`) and Git tools (`git.status`, `git.diff`).

#### Phase 7: Write Tools, Terminal Exec & PowerShell AST Defense (`7567f8f`)
- `filesystem.write`, `filesystem.patch`, `filesystem.delete` native write tools with policy-gated approval.
- `terminal.exec` with PowerShell Constrained Language Mode and AST parser.
- AST validation blocks `-EncodedCommand`, `-ExecutionPolicy Bypass`, reflection, scriptblocks, and pipeline chaining.
- Verify-on-stop rule: last write in a turn is confirmed before the agent loop concludes.
- Git checkpoint before first write in a turn; file snapshot for non-repo targets.

#### Phase 8: MCP Host, Job Object Client & Tool Adapter (`b88acf6`)
- Native JSON-RPC 2.0 stdio MCP client wrapping external plugins behind the tool policy engine.
- MCP child processes run inside the Friday Job Object — no MCP server escapes the process cage.
- Per-server namespace prefixing (`mcp.<server>.<tool>`) and automatic health checks.
- Dynamic tool discovery and schema adapter for seamless agent loop integration.
- MCP is an extension host — not the implementation of filesystem, terminal, git, or memory.

#### Phase 9: 4-Tier Memory, FTS5 Scoped Joins & Injection Defense (`b924d0e`)
- 4-tier persistent memory architecture: Working, Episodic, Semantic, Procedural — all SQLite WAL + FTS5.
- Scoped FTS5 joins prevent cross-session memory bleed.
- Injection defense: web pages, tool results, MCP output, and retrieved memory injected as `user`/`tool` role — never into the system prompt.
- Memory writes that change approval posture, credentials, or paths require explicit native approval.

#### Phase 10: Inert Data Gating (10A) & Sandbox Host (10B) (`8a76c16`)
- Inert data gating: untrusted content (files, web pages, MCP output) sandboxed before injection; cannot promote untrusted content into policy.
- Workspace `SKILL.md` is never auto-loaded — skill create/update requires native dialog approval and diff review.
- A skill cannot grant tools or roots the creating session did not already have.
- Sandbox host isolates skill execution environment from the core agent process.

#### Phase 11: Sovereign Task Scheduler (`5eb9688`)
- Offline cron, interval, and one-shot scheduled job execution.
- Frozen permission snapshots: immutable capability grants assigned at job creation time.
- Atomic SQLite lease claiming with fencing tokens preventing duplicate multi-worker execution.
- Network-off enforcement during unattended scheduled background executions.

#### Phase 12: Subagent Delegation with Monotonic Permissions (`c7ba4ed`)
- Depth-1 delegation limit strictly preventing recursive agent cascades.
- Monotonic authority: child permissions must strictly be a subset of parent permissions.
- Hard anti-recursion barriers: child subagents are denied access to `subagent.*`, `schedule.*`, `policy.*`, and `system.shutdown`.
- Budget watchdog atomically reserving token, turn, and wall-clock allocations from the parent budget.

#### Phase 13: Local Sovereign Telemetry & Langfuse Mirroring (`8e25164`)
- Dual-sink observability: durably logs sovereign local JSONL traces while optionally mirroring to Langfuse.
- Real-time RTX 5090 hardware telemetry snapshotting on every generation observation.
- Automatic redacting of secrets, capability tokens, and sensitive headers; 64 KiB payload boundaries.

#### Phase 14: Terminal Sandboxing & Security Red-Team (`7f7978b`)
- `terminal.exec` tool with constrained PowerShell language mode and AST validation.
- AST parsing blocks reflection, dynamic invoke, scriptblocks, and pipeline chaining.
- 12-vector red-team security test suite proving complete defense against path escapes, process breakaways, token tampering, and privilege escalations.

#### Phase 15: Tauri Packaging & First-Launch Wizard (`c74a6c6`)
- Production desktop bundle configuration for Windows NSIS (`.exe`) and MSI (`.msi`).
- 5-step First-Launch onboarding wizard in React 19:
  - Hardware preflight diagnostics detecting RTX 5090 Blackwell and Windows Job Object support.
  - Workspace scaffolding (`.agents/skills`, `.agents/memory`, `storage`, `config`, `logs`).
  - Model selection, Q6 KV-cache preset, and sovereign configuration generation.

#### Phase 16: Continuous Soak & Endurance Harness (`cc4967a`)
- Fast regression soak test suite (`tests/soak/test_soak_endurance.py`) completing 50 agent turns in 1.35s under `@pytest.mark.soak`.
- Standalone long-run endurance runner (`tests/soak/run_8hr_soak.py`) with Win32 minute telemetry sampling and scripted fault injections (gaming mode, mid-turn cancel, session teardown, MCP restart, model OOM, frozen network-off).
- Desktop supervisor soak contract in Rust (`apps/desktop/src-tauri/tests/test_supervisor_soak.rs`) verifying zero handle leaks, Rust Job Object membership, and sidecar exit reaping.
- Formulated and documented ADR-0002 (Continuous Soak and Endurance Testing Architecture).

### Security
- Host-level sandboxing ensures child processes cannot break away from Windows Job Object containment.
- All high-risk actions require Win32 native system modal approvals; Web UI cannot bypass or auto-approve.
- Capability tokens are single-use, bounded by HMAC-SHA256, and bound to deterministic canonical argument hashes.
- Path operations strictly enforce NTFS boundary containment via `GetFinalPathNameByHandleW`.

### Known Limitations
- **Secrets at rest**: Langfuse and local credentials reside in `.env` (gitignored). Windows DPAPI / Credential Manager integration is targeted for v1.1.
- **Interactive fault injections**: `host_sleep_resume` and `host_lock_unlock` fault injections require an interactive desktop session and are marked `SKIPPED` in headless CI runs.
- **Single resident model**: Gaming Mode operates via cancellation and VRAM release rather than concurrent model swap. Dual-model residency is unsupported in v1.
- **Cloud fallback**: Per-turn cloud inference opt-in is enforced by policy but has no v1 UI surface. Silent failover is blocked by design.

---

## [Unreleased] — v1.1 Backlog

### Planned
- **DPAPI / Credential Manager**: Migrate secrets from `.env` to Windows DPAPI or Credential Manager at rest.
- **AppContainer Process Containment**: Next-level isolation beyond Job Objects for MCP servers and skill sandboxes.
- **Role-Model Hot-Swap UI**: In-app model switching without restart; load/unload race resolution.
- **Cloud Inference Opt-In UI**: Per-turn cloud fallback surface with explicit user consent flow.
- **Interactive Fault Injection**: Automated `host_sleep_resume` and `host_lock_unlock` soak coverage.
- **Messaging Gateways**: Email and Slack integration (explicit post-v1 scope boundary).
- **Computer Use**: GUI automation via screen capture and structured click (post-v1).
- **Voice I/O**: Speech input/output integration (post-v1).
- **Browser Automation**: Web agent capability (post-v1).

---

[1.0.0]: https://github.com/Hollahard/project-ned/releases/tag/v1.0.0
[Unreleased]: https://github.com/Hollahard/project-ned/compare/v1.0.0...HEAD
