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

#### Phase 7: Persistent Workspace Memory & FTS5 (`7567f8f`)
- 4-tier memory architecture (Episodic, Semantic, Working, Procedural).
- SQLite WAL mode storage with FTS5 virtual tables and automatic trigger synchronization.
- Hybrid BM25 full-text keyword search and relevance scoring strictly scoped to workspace roots.

#### Phase 8: External Skills Runtime & Sandbox Isolation (`b88acf6`)
- Dynamic agent skill loading and discovery from `.agents/skills/`.
- Isolated skill process execution within a dedicated Win32 Job Object sandbox cage.
- Scrubbed child process environment stripping parent secrets and API tokens.

#### Phase 9: Model Context Protocol (MCP) Host Integration (`b924d0e`)
- Native JSON-RPC 2.0 stdio MCP client and server host.
- Per-server namespace prefixing (`mcp.<server>.<tool>`) and automatic health checks.
- Dynamic tool discovery and schema adapter for seamless agent loop integration.

#### Phase 10: Model Context Management & Compaction (`8a76c16`)
- Sliding window conversation management with strict token budget enforcement.
- Dynamic compaction summarizing older conversation history when context exceeds budget.
- Inert data tagging ensuring compacted historical context cannot override active policy or developer prompts.

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
