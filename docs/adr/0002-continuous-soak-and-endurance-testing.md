# ADR 0002: Continuous Soak and Long-Run Endurance Testing

## Status
Accepted (Phase 16 Specification on 2026-10-07)

## Context
Project Friday integrates a Tauri 2 / Rust supervisor, a Python FastAPI core, an app-owned TabbyAPI (ExLlamaV3) sidecar, and an SQLite database (WAL + FTS5) on Windows 11 with an NVIDIA GeForce RTX 5090 (32 GB GDDR7).
While unit, integration, and security regression suites (Phases 0–15) prove functional and defensive correctness under isolated conditions, continuous multi-hour desktop execution introduces risks of:
- Process memory accumulation (Python garbage collection fragmentation, asyncio task leaks, unclosed client sessions, Rust handle retention).
- GPU VRAM leaks across model loads, unloads, and Gaming Mode evacuations.
- SQLite deadlocks under concurrent turns, episodic memory ingestion, and scheduler job claims.
- Zombie child process accumulation or Job Object leaks.
- Context budget compaction degradation over long-horizon sessions.

## Decision Drivers
- **Zero Unauthorized Side-Effects**: Soak testing must strictly observe existing security boundaries and must not weaken policy or Job Object controls to facilitate test completion.
- **Accurate Resource Telemetry**: Standard RSS is susceptible to OS working set trimmings and shared DLL caching; metrics must isolate true Private Bytes and process handles.
- **Attributable GPU Memory**: GPU VRAM must isolate TabbyAPI process allocations via NVIDIA system telemetry rather than global card VRAM.
- **Transactional Database Stability**: SQLite must withstand sustained concurrent access without `database is locked` errors or unconstrained WAL accumulation.

## Decision

### 1. Process Memory & Leak Invariants
- Sample Private Bytes, handle count, thread count, and loopback (`127.0.0.1`) TCP connections across Core, Tabby, and Supervisor processes.
- Discard the first 15 minutes of warmup execution to account for initial JIT, SQLite cache population, and dynamic library loading.
- Failure threshold: Private Bytes growth slope exceeding 50 MB/hour, handle growth exceeding 50/hour, or thread count ratcheting.
- Fast CI test suite may utilize `tracemalloc`; long-running soak runs must disable `tracemalloc` to eliminate profiling overhead.
- Session termination must leave zero dangling background tasks, open HTTP clients, or uncommitted SQLite transactions.

### 2. GPU VRAM Leak Oracle
- Query `nvidia-smi` compute-apps memory attributed specifically to the TabbyAPI sidecar PID.
- After model unload, memory attributed to Tabby must return within 512 MB of the post-start residual baseline.
- Monotonic VRAM growth across consecutive unload cycles fails the run.
- Process termination must return total GPU memory to the pre-launch Windows baseline.
- Record p50 and p95 unload latencies (sub-2.0s target for Gaming Mode, but transient spikes do not fail the run unless a GPU driver TDR / `nvlddmkm` event occurs).

### 3. SQLite Concurrency & Integrity
- Concurrent execution spans turn streaming, scheduler job claims, memory search/ingestion, and structured audit logging.
- Any `database is locked` exception exceeding `busy_timeout` constitutes failure.
- SQLite WAL file size must remain below 64 MB between application-triggered checkpoints.
- `PRAGMA wal_checkpoint(TRUNCATE)` is invoked exclusively at run boundaries, never inside the telemetry sampling loop.
- Post-run verification must assert `PRAGMA integrity_check` / `quick_check` returns `ok`.

### 4. Process Containment & Job Object Invariants
- All child processes remain enclosed inside the Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and breakaway denied.
- **Critical Invariant**: Do NOT set `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` or `ActiveProcessLimit = 1` on the supervisor job, ensuring legitimate worker sidecars and child tools can execute concurrently without job denial.
- Upon session cancellation or exit, `QueryInformationJobObject` must list zero active processes after handle termination.

### 5. Security & Native Approvals in Soak Mode
- Soak harness operates headlessly and must never attempt to programmatic-click native Win32 approval dialogs.
- Any tool invocation with Risk >= 2 in the soak profile is auto-denied and logged as a verified policy rejection.
- Mock capability tokens are minted solely through the existing test approval stub bound to the exact tool name and canonical argument hash.
- Scheduled jobs strictly retain frozen permission snapshots: network disabled, zero fail-open.

## Non-Goals
- No embeddings recalculation or secondary resident model swaps.
- No voice, browser automation, or direct computer desktop use in v1 soak.
- No continuous 8-hour execution in standard CI PR pipelines (15-minute qualification gate only for CI; 8-hour run is reserved for release tagging).
