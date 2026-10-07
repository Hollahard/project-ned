# Project: Project Friday Phase 16 — Continuous Soak and Long-Run Endurance Harness

## Architecture
Project Friday integrates a Tauri 2 / Rust supervisor, a Python FastAPI core service, an app-owned TabbyAPI (ExLlamaV3) sidecar, and an SQLite database (WAL + FTS5) running on Windows 11 with an NVIDIA GeForce RTX 5090 (32 GB GDDR7).
The Phase 16 Continuous Soak and Long-Run Endurance Harness establishes both fast deterministic CI soak qualification (<3 minutes offline mock) and multi-hour hardware endurance qualification (15m smoke, 1h gate, 8h release), verifying zero memory leaks (Private Bytes slope <= 50 MB/hr), zero handle leaks (slope <= 50/hr), zero thread ratchets, GPU thermal ceiling (<= 83°C), TabbyAPI VRAM recovery (<= 512 MB residual over baseline), and Windows Job Object process containment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` without active process limit).

```
+---------------------------------------------------------------------------------------------------+
|                                      Windows 11 (NTFS Workspace)                                  |
|                                                                                                   |
|  +------------------------------+             +------------------------------------------------+  |
|  | Rust Tauri Supervisor        |             | Long-Run Endurance Runner                      |  |
|  | (apps/desktop/src-tauri)     |             | (tests/soak/run_8hr_soak.py)                   |  |
|  | - Windows Job Object         |             | - CLI modes: smoke (15m), gate (1h), release(8h)| |
|  |   (KILL_ON_JOB_CLOSE)        |             | - Telemetry: Private Bytes, Handles, Threads,  |  |
|  | - No ActiveProcessLimit      |             |   Loopback TCP, NVML Tabby PID VRAM            |  |
|  | - Handle/Thread Leak Tests   |             | - Tripwires: 50MB/hr, 50 handles/hr, ratchet,  |  |
|  +--------------+---------------+             |   83°C GPU thermal ceiling                     |  |
|                 | (spawns & supervises)       | - Scripted Fault Injections: Gaming Mode,      |  |
|                 v                             |   turn cancel, Job Object sidecar restarts     |  |
|  +------------------------------+             | - Dual-sink: logs/traces/, Langfuse Cloud      |  |
|  | Windows Job Object Boundary  |             | - Artifacts: logs/soak_results.json, report.md |  |
|  |  +------------------------+  |             +------------------------------------------------+  |
|  |  | Python FastAPI Core    |  |                                                                 |
|  |  | (services/core)        |  |             +------------------------------------------------+  |
|  |  | - 4-tier memory churn  |  |             | Fast Mocked Soak Test Suite                    |  |
|  |  | - SQLite scheduler     |  |             | (tests/soak/test_soak_endurance.py)            |  |
|  |  | - Depth-1 subagents    |  |             | - @pytest.mark.soak (< 3 minutes)              |  |
|  |  | - PolicyEngine (Risk>=2|  |             | - 50 turns with MockInferenceBackend           |  |
|  |  |   auto-denied headless)|  |             | - 4-tier memory churn, FTS5, SQLite scheduler  |  |
|  |  +------------------------+  |             | - Depth-1 subagent monotonic containment       |  |
|  |  | TabbyAPI Sidecar       |  |             | - Zero locked errors, WAL < 64 MB              |  |
|  |  | (runtime/tabbyAPI)     |  |             +------------------------------------------------+  |
|  +--+------------------------+--+                                                                 |
+---------------------------------------------------------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Fast Mocked Soak Suite | Automated soak test suite marked `@pytest.mark.soak` completing in < 3 minutes | M1 | ORIGINAL_REQUEST §R1 |
| 2 | 50-Turn Continuous Execution | 50 turns with rapid mid-turn cancellations using `MockInferenceBackend` | M1 | ORIGINAL_REQUEST §R1 |
| 3 | 4-Tier Memory Churn | Rapid insert, FTS5 scoped search, and soft delete across Working, Episodic, Semantic, Procedural tiers | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Concurrent SQLite Scheduler | Concurrent claims (`owner_instance`), leases, timeouts, duplicate suppression via `idempotency_key` | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Subagent Monotonic Containment | Depth-1 delegation validation, budget containment, anti-recursion (grandchild rejection) | M1 | ORIGINAL_REQUEST §R1 |
| 6 | SQLite Concurrency & WAL Limits | Absence of `database is locked`, WAL growth <= 64 MB, clean checkpoints | M1 | ORIGINAL_REQUEST §R1, ADR-0002 §3 |
| 7 | Security Headless Invariants | Auto-denial of Risk >= 2 operations in soak profile; HMAC-SHA256 capability token test stub | M1 | ORIGINAL_REQUEST §R4 |
| 8 | Rust Supervisor Handle/Thread Leak Tests | Integration test verifying 50+ iterations of session, telemetry, preflight leak zero handles (`<= 5`) / threads (`<= 1`) | M2 | ORIGINAL_REQUEST §R3 |
| 9 | Rust Job Object Concurrency & Termination | Verification that `ActiveProcessLimit = 1` is NOT set, multi-worker concurrency allowed, and drop terminates all children | M2 | ORIGINAL_REQUEST §R3, ADR-0002 §4 |
| 10 | Standalone Soak CLI Modes | CLI runner supporting `--mode smoke` (15m), `--mode gate` (1h), and `--mode release` (8h) | M3 | ORIGINAL_REQUEST §R2 |
| 11 | Process Metrics & Telemetry Sampler | Query Private Bytes (`PROCESS_MEMORY_COUNTERS_EX`), handles, threads, loopback TCP connections across Core, Tabby, Supervisor | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §1 |
| 12 | Tripwire: 15-Minute Warmup Discard | Discard initial warmup samples before evaluating slopes or ratchets | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §1 |
| 13 | Tripwire: Private Bytes Slope | Linear regression slope abort if growth > 50 MB/hour | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §1 |
| 14 | Tripwire: Handle Count Slope | Linear regression slope abort if growth > 50 handles/hour | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §1 |
| 15 | Tripwire: Thread Count Ratchet | Monotonic ratchet detection across sliding windows aborts runner | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §1 |
| 16 | Tripwire: GPU Temperature Ceiling | NVML temperature monitor aborts runner if temperature > 83°C | M3 | ORIGINAL_REQUEST §R2 |
| 17 | NVML Tabby PID VRAM Attribution | Query TabbyAPI compute process VRAM specifically via NVML / `nvidia-smi compute-apps` | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §2 |
| 18 | Post-Unload VRAM Recovery Oracle | Verify post-unload residual memory returns to within 512 MB of post-start baseline, and full exit returns to pre-launch baseline | M3 | ORIGINAL_REQUEST §R2, ADR-0002 §2 |
| 19 | Scripted Fault Injections | Gaming Mode evacuation (<2.0s), mid-turn cancel, Core/MCP sidecar restarts inside Job Object | M3 | ORIGINAL_REQUEST §R2 |
| 20 | Dual-Sink Telemetry Streaming | Stream to local `logs/traces/*.jsonl` and mirror to Langfuse Cloud | M3 | ORIGINAL_REQUEST §R2 |
| 21 | Soak Results & Benchmark Report | Generate `logs/soak_results.json` and `docs/benchmarks/soak_test_report.md` | M3 | ORIGINAL_REQUEST §R2 |
| 22 | GPU Marker Isolation | `@pytest.mark.gpu` for hardware-dependent tests, keeping standard soak deterministic and offline | M1, M3 | ORIGINAL_REQUEST §R4 |
| 23 | E2E Acceptance Verification | Execute full acceptance criteria (pytest soak, cargo test, smoke runner 15m, 198+ regression pass) | M4 | ORIGINAL_REQUEST Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Fast Mocked Soak Suite | `tests/soak/test_soak_endurance.py` fixing all 5 API mismatches and verifying 50 turns, 4-tier memory churn, concurrent scheduler, subagent containment, WAL <= 64 MB | none | PLANNED |
| 2 | M2: Rust Tauri Supervisor Contract | `apps/desktop/src-tauri/tests/test_endurance_invariants.rs` asserting handle/thread stability and multi-worker Job Object concurrency | none | PLANNED |
| 3 | M3: Standalone Long-Run Runner | `tests/soak/run_8hr_soak.py` implementing CLI modes, Win32/NVML metrics, tripwires, fault injection, dual-sink telemetry, and reporting | M1 | PLANNED |
| 4 | M4: Final Acceptance & Dual Track | End-to-end verification of all acceptance criteria (pytest soak < 3m, cargo test, smoke run qualification, 198+ regression suite) + Forensic Audit | M1, M2, M3 | PLANNED |

## Interface Contracts
### `SoakMockInference` ↔ `AgentLoop`
- `async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]`
- Emits `InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="...")` and `InferenceEvent(type=InferenceEventType.FINISH, finish_reason="stop")`.

### `MemoryCoordinator` ↔ Test Churn
- Search: `coordinator.search(query, workspace_root, tiers=["working", "episodic", "semantic", "procedural"]) -> str` (fenced with `MEMORY_OUTPUT_FENCE_PREFIX`).
- Episodic: `session_manager.add_message(session_id, role, content)`.
- Semantic: `coordinator.semantic.save(entry: SemanticMemoryEntry)` / `delete(entry.id, workspace_root)`.
- Procedural: `coordinator.procedural.save(entry: ProceduralMemoryEntry, is_system_authorized=True)` / `approve(id, root)`.

### `SchedulerDatabaseManager` ↔ Concurrent Worker
- `claim_next_due_job(now_utc: int, owner_instance: str, ...) -> Optional[tuple[ScheduledJob, JobRun]]`
- `complete_run(run_id: str, owner_instance: str, ownership_generation: int, final_state: RunState, consumed_tokens: int) -> bool`

### `SubagentSpec` ↔ `validate_capability_containment`
- `SubagentSpec(role: str, task_prompt: str, parent_session_id: str, parent_turn_id: str, workspace_root: str, depth=1, allowed_tool_ids=[...], token_budget=4000)`
- `validate_capability_containment(parent: ParentCapabilities, child: SubagentSpec)` raises `PolicyDeniedError` if `parent.depth != 0` or grants escalate.

### Rust `JobObject` ↔ Supervisor Integration Tests
- `apps/desktop/src-tauri/src/processes.rs`: `JobObject` exposes `pub fn raw_handle(&self) -> HANDLE` or implements `std::os::windows::io::AsRawHandle`.
- `QueryInformationJobObject` asserts `LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0`, `LimitFlags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS == 0`, and `ActiveProcessLimit == 0`.

### Standalone Soak Runner CLI ↔ Windows OS & NVML
- CLI: `python tests/soak/run_8hr_soak.py --mode smoke|gate|release`
- Telemetry outputs: `logs/soak_results.json`, `docs/benchmarks/soak_test_report.md`, `logs/traces/*.jsonl`.
- Tripwires: slope > 50 MB/hr, slope > 50 handles/hr, thread ratchet, temp > 83°C.

## Code Layout
- `tests/soak/test_soak_endurance.py`: Fast mocked soak test suite (R1, R4).
- `tests/soak/run_8hr_soak.py`: Standalone long-run endurance runner CLI (R2, R4).
- `apps/desktop/src-tauri/tests/test_endurance_invariants.rs`: Rust supervisor endurance integration test (R3).
- `apps/desktop/src-tauri/src/processes.rs`: JobObject handle accessor (R3).
- `logs/soak_results.json`: Soak test results summary.
- `docs/benchmarks/soak_test_report.md`: Soak benchmark markdown report.
