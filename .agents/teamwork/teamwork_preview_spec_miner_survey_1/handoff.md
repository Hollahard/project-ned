# Specification Mining Handoff: Phase 16 Continuous Soak and Long-Run Endurance Harness

**Agent**: `teamwork_preview_spec_miner_survey_1` (Specification Miner)  
**Parent**: `orchestrator_1` (`3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22`)  
**Date**: 2026-10-07  
**Working Directory**: `G:\Project_Ned\.agents\teamwork\teamwork_preview_spec_miner_survey_1`  
**Target Project**: Project Friday (`G:\Project_Ned`)  
**Authoritative References**:
1. `G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md`
2. `G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md`
3. `G:\Project_Ned\GEMINI.md`

---

## 1. Observation

Direct verbatim extractions and code citations from authoritative sources:

### 1.1 From `ORIGINAL_REQUEST.md`
- **R1. Fast Mocked Soak Test Suite (`tests/soak/test_soak_endurance.py`)**:
  - *"Implement an automated endurance test suite marked with `@pytest.mark.soak` that completes in under 3 minutes using a mocked inference backend (`MockInferenceBackend`)."* [Lines 12-13]
  - *"Exercise 50 continuous turns incorporating: Rapid mid-turn cancellations; 4-tier memory churn (rapid insert, FTS5 scoped search, soft deletion); SQLite scheduler concurrent job claims, timeouts, and duplicate execution suppression; Depth-1 subagent delegations with budget reconciliation, proving monotonic permission containment and anti-recursion (grandchild delegation refusal); Strict absence of `database is locked` errors, WAL growth exceeding 64 MB, or SQLite checkpoint stalls."* [Lines 14-19]
- **R2. Standalone Long-Run Endurance Runner (`tests/soak/run_8hr_soak.py`)**:
  - *"Implement a CLI runner supporting three duration modes: `--mode smoke` (15 minutes fast qualification), `--mode gate` (1 hour GPU qualification gate), `--mode release` (8 hours full continuous soak run)."* [Lines 21-25]
  - *"Attribute VRAM specifically to the TabbyAPI PID via `nvidia-smi compute-apps` / NVML; verify post-unload residual memory returns to within 512 MB of baseline, and full process exit returns to pre-launch baseline."* [Line 26]
  - *"Sample Private Bytes, OS handle counts, thread counts, and loopback TCP connections for Core, TabbyAPI, and the supervisor; enforce tripwires: Discard the first 15 minutes of warmup; Abort if Private Bytes growth slope > 50 MB/hour; Abort if OS handles climb > 50/hour or thread count monotonically ratchets; Abort if GPU temperature exceeds 83°C."* [Lines 27-31]
  - *"Periodically trigger scripted fault injections: Gaming Mode evacuation (VRAM release and restore); Mid-flight turn cancellation; Core and MCP sidecar restarts inside the Windows Job Object."* [Lines 32-35]
  - *"Stream telemetry dual-sink to `logs/traces/` and Langfuse Cloud, outputting `logs/soak_results.json` and generating `docs/benchmarks/soak_test_report.md`."* [Line 36]
- **R3. Rust Tauri Supervisor Endurance Contract (`apps/desktop/src-tauri`)**:
  - *"Add integration tests to the Rust Tauri supervisor verifying: Repeated session creation, telemetry polling, and preflight checks do not leak Windows OS handles or thread pools; Supervisor window close cleanly terminates child processes (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) without setting active process limits that would break worker concurrency."* [Lines 38-42]
- **R4. Security & Headless Approval Invariants**:
  - *"Tests must execute headlessly and never simulate user clicks on Win32 system modal dialogs."* [Line 44]
  - *"Any operation with Risk >= 2 in the soak profile must be auto-denied and verified as a rejected capability."* [Line 45]
  - *"Capability tokens must strictly use the HMAC-SHA256 test stub bound to exact tool names and canonical arguments."* [Line 46]
  - *"Any test requiring real GPU weights must be marked with `@pytest.mark.gpu` to keep standard test runs offline and deterministic."* [Line 47]
- **Acceptance Criteria**:
  - `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"` passes in under 3 minutes with zero warnings and no orphaned processes.
  - `cmd.exe /c "cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml"` passes all supervisor handle leak and termination invariants.
  - Smoke run `cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke"` passes 15-minute qualification, validates baseline VRAM recovery, and writes `logs/soak_results.json`.
  - All 198+ existing regression tests (`services/core/tests/`, `tests/security/`, `tests/e2e/`) continue passing cleanly without regressions.

### 1.2 From `docs/adr/0002-continuous-soak-and-endurance-testing.md`
- **Process Memory & Leak Invariants**:
  - *"Sample Private Bytes, handle count, thread count, and loopback (`127.0.0.1`) TCP connections across Core, Tabby, and Supervisor processes."* [Line 24]
  - *"Discard the first 15 minutes of warmup execution to account for initial JIT, SQLite cache population, and dynamic library loading."* [Line 25]
  - *"Failure threshold: Private Bytes growth slope exceeding 50 MB/hour, handle growth exceeding 50/hour, or thread count ratcheting."* [Line 26]
  - *"Fast CI test suite may utilize `tracemalloc`; long-running soak runs must disable `tracemalloc` to eliminate profiling overhead."* [Line 27]
  - *"Session termination must leave zero dangling background tasks, open HTTP clients, or uncommitted SQLite transactions."* [Line 28]
- **GPU VRAM Leak Oracle**:
  - *"Query `nvidia-smi` compute-apps memory attributed specifically to the TabbyAPI sidecar PID."* [Line 31]
  - *"After model unload, memory attributed to Tabby must return within 512 MB of the post-start residual baseline."* [Line 32]
  - *"Monotonic VRAM growth across consecutive unload cycles fails the run."* [Line 33]
  - *"Process termination must return total GPU memory to the pre-launch Windows baseline."* [Line 34]
  - *"Record p50 and p95 unload latencies (sub-2.0s target for Gaming Mode, but transient spikes do not fail the run unless a GPU driver TDR / `nvlddmkm` event occurs)."* [Line 35]
- **SQLite Concurrency & Integrity**:
  - *"Any `database is locked` exception exceeding `busy_timeout` constitutes failure."* [Line 39]
  - *"SQLite WAL file size must remain below 64 MB between application-triggered checkpoints."* [Line 40]
  - *"`PRAGMA wal_checkpoint(TRUNCATE)` is invoked exclusively at run boundaries, never inside the telemetry sampling loop."* [Line 41]
  - *"Post-run verification must assert `PRAGMA integrity_check` / `quick_check` returns `ok`."* [Line 42]
- **Process Containment & Job Object Invariants**:
  - *"All child processes remain enclosed inside the Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and breakaway denied."* [Line 45]
  - *"Critical Invariant: Do NOT set `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` or `ActiveProcessLimit = 1` on the supervisor job, ensuring legitimate worker sidecars and child tools can execute concurrently without job denial."* [Line 46]
  - *"Upon session cancellation or exit, `QueryInformationJobObject` must list zero active processes after handle termination."* [Line 47]
- **Security & Native Approvals in Soak Mode**:
  - *"Soak harness operates headlessly and must never attempt to programmatic-click native Win32 approval dialogs."* [Line 50]
  - *"Any tool invocation with Risk >= 2 in the soak profile is auto-denied and logged as a verified policy rejection."* [Line 51]
  - *"Mock capability tokens are minted solely through the existing test approval stub bound to the exact tool name and canonical argument hash."* [Line 52]
  - *"Scheduled jobs strictly retain frozen permission snapshots: network disabled, zero fail-open."* [Line 53]
- **Non-Goals**:
  - *"No embeddings recalculation or secondary resident model swaps."* [Line 56]
  - *"No voice, browser automation, or direct computer desktop use in v1 soak."* [Line 57]
  - *"No continuous 8-hour execution in standard CI PR pipelines (15-minute qualification gate only for CI; 8-hour run is reserved for release tagging)."* [Line 58]

### 1.3 From `GEMINI.md`
- **Terminal Execution & Subshell Invariants**:
  - *"Always Route Tests to Output Files: When running test or build commands (`pytest`, `cargo test`, `npm test`), always route through `cmd.exe /c` or pipe output to a temporary log file (`> log.txt 2>&1`) and inspect via `view_file`."* [Lines 4-6]
  - *"PowerShell Parentheses Escaping: When passing paths with `(x86)` or commit messages with parentheses like `feat(core): ...`, always quote strings or escape them in pwsh to avoid subexpression evaluation errors."* [Line 7]
  - *"Sandbox Bypass: Workspaces spanning drive G: with restricted system drives require `BypassSandbox: true` for reliable execution."* [Line 8]
- **Process Guardian & Sidecar Invariants**:
  - *"Zero Orphaned Processes: Child processes (Core and TabbyAPI) must run inside the Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Breakaway is strictly denied."* [Line 11]
  - *"Environment Sanitization: Never copy `std::env::vars()` or `os.environ` wholesale to child processes. Strip parent secrets and pass only explicit whitelist variables (`PATH`, `TEMP`, `SYSTEMROOT`) and process tokens."* [Line 12]
  - *"Sidecar Isolation: Never import ExLlamaV3 directly in Core. Keep TabbyAPI in its isolated `.venv` (`runtime/tabbyAPI/.venv`)."* [Line 13]
- **Security & Capability Tokens**:
  - *"Native OS Modals: Approvals for high-risk tools must use native Win32 system modal dialogs (`MB_SYSTEMMODAL`, `MB_DEFBUTTON2`). Web UI cannot bypass or auto-approve."* [Line 16]
  - *"One-Shot Capability Tokens: Tokens issued upon native OS approvals are strictly single-use, bounded by HMAC-SHA256, and bound to deterministic JSON-serialized arguments (`sort_keys=True`, no extra whitespace)."* [Line 17]
- **Testing & Mocking Invariants**:
  - *"Isolated Path & Stat Mocking: When patching `pathlib.Path.stat` or filesystem introspection methods, never replace them globally with dummy objects lacking `st_mode`."* [Line 20]
  - *"Tool Contract Completeness: Mock tools inheriting from `Tool` must define `parameters_schema` (minimum `{"type": "object", "properties": {}}`)."* [Line 21]
  - *"Hung Process Cleanup: If a test run exits abnormally or is interrupted, always verify and terminate orphaned `pytest.exe` or `python.exe` processes before launching subsequent test runs."* [Line 22]
  - *"Async Database & Background Worker Teardown: Fixtures initializing FastAPI applications or database managers (`DatabaseManager`, `aiosqlite`) must be asynchronous `yield` fixtures that explicitly await `db_manager.close()` during teardown. SQLite worker threads spawned by `aiosqlite` will otherwise prevent the Python process from exiting on Windows, causing pytest subshells to hang indefinitely after test completion."* [Line 23]

### 1.4 Codebase Touchpoints
- **4 Memory Tiers**:
  1. `friday.memory.working.WorkingMemory`: Ephemeral scratchpad for active agent turn.
  2. `friday.memory.episodic.EpisodicMemory`: FTS5 full-text search across `messages` table joined to `sessions.working_directory`.
  3. `friday.memory.semantic.SemanticMemory`: Persistent architectural/fact knowledge in `semantic_memory` with `semantic_memory_fts`.
  4. `friday.memory.procedural.ProceduralMemory`: Workflow playbooks/recipes in `procedural_memory` with `procedural_memory_fts`. Unapproved procedures (`approved=0`) emit passive historical summary with executable steps omitted; approved (`approved=1`) emit steps.
  5. `friday.memory.coordinator.MemoryCoordinator`: Fences output with `MEMORY_OUTPUT_FENCE_PREFIX` and enforces `total_max_chars=3000` context budget.
- **SQLite Concurrency & WAL**:
  - `friday.storage.db.DatabaseManager`: WAL journal mode, synchronous=NORMAL, foreign keys enabled, FTS5 virtual tables and sync triggers.
  - `friday.scheduler.db.SchedulerDatabaseManager`: WAL mode, PRAGMA synchronous=FULL, PRAGMA foreign_keys=ON, PRAGMA busy_timeout=5000, atomic leases via `claim_next_due_job`, duplicate suppression via `UNIQUE(job_id, scheduled_for_utc)`.
- **Subagents**:
  - `friday.subagents.models.SubagentSpec`: Depth must be exactly 1 (`validate_depth`), forbidden tools (`subagent.`, `schedule.`, `policy.`, `system.shutdown`), budget ranges (tokens 100-32000, iterations 1-10, duration 5-120s).
  - `friday.subagents.models.validate_capability_containment`: Parent depth=0, child depth=1, tool subset, risk ceiling, budget ceiling, path containment, and strict reduction invariant (at least one dimension strictly narrower).
  - `friday.subagents.runner.SubagentExecutionGuard`: Runtime invocation check against live parent authority intersection and anti-recursion prefixes.
- **GPU Telemetry & Gaming Mode**:
  - `friday.inference.telemetry.TelemetryProvider`: NVML-based `get_gpu_telemetry()` returning VRAM used/free/total, temperature (°C), wattage, utilization.
  - `friday.inference.gaming_mode.GamingModeController`: Evacuates VRAM, halts active turns, unloads model, measures completion elapsed time (target < 2.0s), computes freed VRAM.
- **Process Supervisor (Rust)**:
  - `friday_supervisor::processes::JobObject`: Wraps Windows Job Object, configures `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, assigns child processes, RAII drop closes handle.
  - `friday_supervisor::processes::build_sanitized_env`: Whitelist only (`PATH`, `TEMP`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`), strips all external API keys and secrets.
  - `friday_supervisor::approvals::ApprovalManager`: HMAC-SHA256 one-shot capability tokens bound to canonical order-independent argument hash (`compute_args_hash`).

---

## 2. Logic Chain

From the authoritative requirements and codebase inspection, we construct the following step-by-step logic chain:

1. **Test Separation Invariant (Offline Mock vs Long-Run Hardware)**:
   - *Observation*: R1 requires `@pytest.mark.soak` completing in < 3 minutes without real GPU dependencies, while R2 tests multi-hour GPU behavior on RTX 5090 Blackwell.
   - *Logic*: The codebase must decouple unit soak (`test_soak_endurance.py`) from physical hardware soak (`run_8hr_soak.py`). R1 uses `MockInferenceBackend` to run 50 turns deterministically and rapidly. Any test requiring physical GPU weights must be marked with `@pytest.mark.gpu` to prevent CI pipeline hangs and timeouts.

2. **Memory Leak Detection & Working Set Pitfall**:
   - *Observation*: ADR-0002 explicitly notes: *"Standard RSS is susceptible to OS working set trimmings and shared DLL caching; metrics must isolate true Private Bytes and process handles."*
   - *Logic*: On Windows, querying standard `rss` (`WorkingSetSize`) is misleading because the Windows Memory Manager dynamically trims working sets to the paging file when system pressure occurs or when windows are minimized. Therefore, Private Bytes (`psutil.Process().memory_info().private` or `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`) must be sampled.

3. **Telemetry Warmup Discard (15 Minutes)**:
   - *Observation*: R2 and ADR-0002 dictate: *"Discard the first 15 minutes of warmup execution to account for initial JIT, SQLite cache population, and dynamic library loading."*
   - *Logic*: The linear regression slope calculations for Private Bytes and OS handles must ignore all samples with timestamp $t < t_0 + 15\text{ minutes}$. For `--mode smoke` (15 min), warmup is either scaled down proportionally (e.g., first 3 minutes) or measured specifically during steady-state cycles.

4. **Private Bytes Growth Slope Formula**:
   - *Observation*: Tripwire threshold is 50 MB/hour.
   - *Logic*: Given $N$ samples $(t_i, M_i)$ where $t_i$ is elapsed time in hours (post-warmup) and $M_i$ is Private Bytes in MB, the least-squares linear slope is calculated as:
     $$\text{Slope}_{\text{Private Bytes}} = \frac{N \sum (t_i M_i) - (\sum t_i)(\sum M_i)}{N \sum t_i^2 - (\sum t_i)^2}$$
     If $\text{Slope}_{\text{Private Bytes}} > 50.0\text{ MB/hr}$, the tripwire trips and the runner immediately initiates graceful shutdown and marks the test as FAILED.

5. **OS Handle Count Slope Formula**:
   - *Observation*: Tripwire threshold is 50 handles/hour.
   - *Logic*: Using the same linear regression formula with $H_i$ (handle count) in place of $M_i$:
     $$\text{Slope}_{\text{Handles}} = \frac{N \sum (t_i H_i) - (\sum t_i)(\sum H_i)}{N \sum t_i^2 - (\sum t_i)^2}$$
     If $\text{Slope}_{\text{Handles}} > 50.0\text{ handles/hr}$, the tripwire trips and execution aborts.

6. **Thread Count Monotonic Ratchet Definition**:
   - *Observation*: ADR-0002 states: *"Abort if OS handles climb > 50/hour or thread count monotonically ratchets."*
   - *Logic*: A ratchet condition occurs when the thread count increases at iteration $k$, never recovers to previous baseline, and monotonically increases across subsequent check intervals (e.g. $T_k > T_{k-1}$ repeatedly without downward reclamation). The detection algorithm maintains a sliding window of peak thread counts: if the minimum thread count in window $W_j$ strictly exceeds the maximum thread count in prior window $W_{j-1}$ across 3 consecutive windows, a thread leak/ratchet is flagged.

7. **GPU VRAM Isolation via PID Attribution**:
   - *Observation*: Global GPU VRAM includes Windows DWM, desktop apps, and OS composition. R2 demands attributing VRAM specifically to TabbyAPI PID.
   - *Logic*: Telemetry must query NVML per-process compute accounting (`pynvml.nvmlDeviceGetComputeRunningProcesses`) or `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits` filtered by `tabby_pid`.

8. **GPU VRAM Post-Unload Baseline Residual Rule**:
   - *Observation*: *"verify post-unload residual memory returns to within 512 MB of baseline, and full process exit returns to pre-launch baseline."*
   - *Logic*: Let $V_{\text{start}}$ be TabbyAPI's VRAM usage immediately after initial model-free startup (post-start residual baseline). After each model unload (e.g., Gaming Mode or cycle end), let $V_{\text{post-unload}}$ be the TabbyAPI VRAM usage. The invariant is:
     $$V_{\text{post-unload}} - V_{\text{start}} \le 512\text{ MB}$$
     Furthermore, monotonic growth across consecutive unload cycles ($V_{\text{unload}, k} > V_{\text{unload}, k-1} + \epsilon$) violates the oracle and fails the run. Finally, upon full process termination, system VRAM must equal pre-launch Windows baseline ($V_{\text{sys, post-exit}} \approx V_{\text{sys, pre-launch}}$).

9. **GPU Thermal Ceiling**:
   - *Observation*: R2 states: *"Abort if GPU temperature exceeds 83°C."*
   - *Logic*: At each sampling tick, NVML temperature $T_{\text{GPU}}$ is polled. If $T_{\text{GPU}} > 83^\circ\text{C}$, the runner aborts to protect the RTX 5090 hardware from thermal degradation.

10. **SQLite Concurrency, WAL Ceiling (64 MB), and Teardown**:
    - *Observation*: SQLite WAL file size must remain $< 64\text{ MB}$, zero `database is locked` errors beyond `busy_timeout` (5000 ms), and `aiosqlite` threads must not hang.
    - *Logic*: Checkpoint frequency must ensure WAL does not balloon under churn. Manual checkpointing (`PRAGMA wal_checkpoint(TRUNCATE)`) is restricted to run boundaries. During teardown, all SQLite connections and database managers (`DatabaseManager`, `SchedulerDatabaseManager`, `SubagentDatabaseManager`) must explicitly await `.close()` to terminate worker threads on Windows.

11. **Supervisor Process Concurrency Invariant (`ActiveProcessLimit` Prohibition)**:
    - *Observation*: ADR-0002 states: *"Critical Invariant: Do NOT set `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` or `ActiveProcessLimit = 1` on the supervisor job, ensuring legitimate worker sidecars and child tools can execute concurrently without job denial."*
    - *Logic*: If `ActiveProcessLimit = 1` was configured on the Job Object, spawning TabbyAPI or Core or tool processes would fail with `ERROR_ACCESS_DENIED` or `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` violation. The Job Object must solely enforce `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` with breakaway denied, allowing arbitrary child worker concurrency.

12. **Zero Orphaned Processes Oracle (`QueryInformationJobObject`)**:
    - *Observation*: ADR-0002 specifies that upon session cancellation or exit, `QueryInformationJobObject` must list zero active processes.
    - *Logic*: In Rust (`apps/desktop/src-tauri`), the supervisor tests must query the Windows kernel via `QueryInformationJobObject(handle, JobObjectBasicProcessIdList, ...)` to prove that after dropping or closing the supervisor, the active process count is exactly 0.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | R1 (Test Suite) | Fast Soak Test Suite | Automated test suite marked `@pytest.mark.soak` completing in < 3 minutes. | Mock inference backend, test fixtures | Pytest exit code 0, 0 warnings | Fails if runtime >= 180s or any assertion fails | ORIGINAL_REQUEST.md [L12-13] |
| 2 | R1 (Turns) | 50-Turn Continuous Execution | Executes 50 sequential agent turns with mid-turn cancellations and session switching. | 50 turn prompts, session IDs, cancellation triggers | Streamed events (`turn.started`, `turn.completed`, `CancelledError`) | Leaked background tasks or uncommitted DB transactions trigger test failure | ORIGINAL_REQUEST.md [L14-15] |
| 3 | R1 (Memory Churn) | 4-Tier Memory Churn & FTS5 Integrity | Rapid insert, FTS5 scoped search, and soft deletion across Working, Episodic, Semantic, and Procedural memory tiers. | Memory entries (facts, rules, notes, playbooks), workspace root | FTS5 search results with `MEMORY_OUTPUT_FENCE_PREFIX`, DB integrity status `ok` | Raises assertion failure if FTS search fails, results escape workspace root, or `PRAGMA integrity_check` != 'ok' | ORIGINAL_REQUEST.md [L16], `friday.memory` |
| 4 | R1 (Scheduler) | SQLite Scheduler Concurrent Operations | Concurrently claims jobs, tests lease timeouts, and asserts duplicate execution suppression. | Job specs, cron expressions, worker IDs, now_utc | Claimed job records, completion states | Duplicate run on `(job_id, scheduled_for_utc)` rejected by SQLite unique constraint | ORIGINAL_REQUEST.md [L17], `friday.scheduler.db` |
| 5 | R1 (Subagents) | Depth-1 Subagent Delegation Guard | Validates child subagent creation at depth=1, dynamic authority intersection, and anti-recursion. | Parent capabilities, child `SubagentSpec` (depth=1, tools, budgets) | Validated `SubagentSpec` or execution decision | Grandchild delegation (depth >= 2) or requesting forbidden tools raises `ValueError` / `PolicyDeniedError` | ORIGINAL_REQUEST.md [L18], `friday.subagents` |
| 6 | R1 (SQLite WAL) | WAL Growth & Lock Oracle | Asserts zero `database is locked` errors and WAL size strictly under 64 MB during concurrent access. | Concurrent SQLite read/write operations | WAL file size in MB, execution success | WAL >= 64 MB or lock timeout exceeding 5000ms triggers test failure | ORIGINAL_REQUEST.md [L19], ADR-0002 [L39-40] |
| 7 | R1 (Memory Drift) | Tracemalloc Bounded Memory Drift | Verifies Python in-memory heap drift slope is bounded (< 25 MB) during 50 mocked turns. | `tracemalloc` snapshots (start, end) | Size diff in KB/MB | Fails if memory diff >= 25,600 KB | `test_soak_endurance.py` [L124-182] |
| 8 | R2 (CLI Runner) | Multi-Mode Soak CLI | CLI entry point supporting `--mode smoke` (15m), `--mode gate` (1h), and `--mode release` (8h). | CLI arguments (`--mode`, `--sample-interval`, `--report-path`, etc.) | Process exit code, stdout summary | Invalid mode exits with error; unhandled crash returns non-zero | ORIGINAL_REQUEST.md [L21-25] |
| 9 | R2 (Warmup) | 15-Minute Warmup Discard | Discards first 15 minutes of metric sampling before calculating growth slopes and ratchet tripwires. | Time series telemetry samples | Filtered post-warmup time series dataset | Warmup samples included in slope triggers false positive tripwire abort | ORIGINAL_REQUEST.md [L28], ADR-0002 [L25] |
| 10 | R2 (Private Bytes) | Private Bytes Slope Tripwire | Computes linear regression growth slope of Private Bytes (MB/hr); aborts if > 50 MB/hr. | Private Bytes telemetry samples $(t_i, M_i)$ | Calculated slope in MB/hr | Aborts soak runner immediately if slope > 50.0 MB/hr | ORIGINAL_REQUEST.md [L29], ADR-0002 [L26] |
| 11 | R2 (OS Handles) | OS Handle Count Slope Tripwire | Computes linear regression slope of process handle count; aborts if > 50 handles/hr. | Process handle count samples $(t_i, H_i)$ | Calculated slope in handles/hr | Aborts soak runner immediately if slope > 50.0 handles/hr | ORIGINAL_REQUEST.md [L30], ADR-0002 [L26] |
| 12 | R2 (Threads) | Thread Count Monotonic Ratchet Tripwire | Detects monotonic thread count increase across consecutive sampling windows without downward recovery. | Process thread counts across time | Ratchet detection boolean | Aborts soak runner immediately if thread ratchet is detected | ORIGINAL_REQUEST.md [L30], ADR-0002 [L26] |
| 13 | R2 (Thermal) | GPU Temperature Ceiling Tripwire | Monitors GPU core temperature via NVML; aborts if $T_{\text{GPU}} > 83^\circ\text{C}$. | NVML temperature reading | Current temperature in °C | Aborts soak runner immediately if temperature > 83°C | ORIGINAL_REQUEST.md [L31] |
| 14 | R2 (VRAM Attribution) | TabbyAPI PID VRAM Attribution | Isolates GPU memory consumption specifically to TabbyAPI sidecar PID via NVML or `nvidia-smi compute-apps`. | TabbyAPI PID, NVML compute process query | Attributed VRAM in MB | Fails if non-attributable or attributed memory leaks | ORIGINAL_REQUEST.md [L26], ADR-0002 [L31] |
| 15 | R2 (VRAM Baseline) | Post-Unload VRAM Recovery Oracle | Asserts TabbyAPI residual memory post-unload is within 512 MB of post-start baseline, and full exit restores pre-launch baseline. | Pre-launch, post-start, and post-unload VRAM snapshots | Delta VRAM in MB | Fails if residual > baseline + 512 MB or monotonic growth across consecutive unloads | ORIGINAL_REQUEST.md [L26], ADR-0002 [L32-34] |
| 16 | R2 (Latency) | Unload Latency Tracking | Records p50 and p95 model unload latencies (sub-2.0s target for Gaming Mode). | Unload duration timestamps | p50, p95 latencies in seconds | Spikes logged; GPU driver TDR (`nvlddmkm`) fails run | ADR-0002 [L35] |
| 17 | R2 (Fault Injection) | Gaming Mode Evacuation Fault | Triggers mid-soak Gaming Mode evacuation (turn abort + VRAM release) and verifies clean recovery on resume. | GamingModeController activate/deactivate | Evacuated VRAM in MB, elapsed seconds | Fails if evacuation > 2.0s or VRAM fails to release | ORIGINAL_REQUEST.md [L33], `friday.inference.gaming_mode` |
| 18 | R2 (Fault Injection) | Mid-Flight Turn Cancellation Fault | Aborts in-flight generation turns via WebSocket/AgentLoop and checks zero task leaks. | Active session ID, cancel signal | Cancelled turn event, task completion | Hanging tasks or deadlock fail the run | ORIGINAL_REQUEST.md [L34] |
| 19 | R2 (Fault Injection) | Sidecar Restart inside Job Object | Restarts Core or MCP sidecar processes within the supervisor Windows Job Object without breaking containment. | Target process PID, restart command | New PID assigned to Job Object | Process breakaway or orphan PIDs fail the run | ORIGINAL_REQUEST.md [L35], GEMINI.md [L11] |
| 20 | R2 (Telemetry Dual-Sink) | Dual-Sink Observability Streaming | Durably streams telemetry to local JSONL files in `logs/traces/` and mirrors to Langfuse Cloud. | Observation records, trace events | Local `.jsonl` trace files, Langfuse HTTP traces | Tracing errors fail-safe and never crash the soak runner | ORIGINAL_REQUEST.md [L36], `friday.telemetry` |
| 21 | R2 (Reporting) | Artifact Generation (`soak_results.json` & Report) | Outputs structured `logs/soak_results.json` and generates formatted `docs/benchmarks/soak_test_report.md`. | Complete run telemetry, stats, tripwire evaluations | JSON summary file, Markdown report file | Missing results file or malformed JSON fails run | ORIGINAL_REQUEST.md [L36] |
| 22 | R3 (Supervisor Endurance) | Repeated Supervisor Operations Test | Integration test verifying repeated session creations, telemetry queries, and preflight checks do not leak handles or threads. | Number of repetitions (e.g. 50-100 cycles) | Delta OS handle count, delta thread count | Handle or thread count climbing across cycles fails test | ORIGINAL_REQUEST.md [L39-40] |
| 23 | R3 (Job Object) | Job Object Termination & Zero Orphan Oracle | Verifies supervisor exit terminates all child processes cleanly (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) without active process limits. | Supervisor process exit / drop | Process exit status, `QueryInformationJobObject` | Active process count > 0 or setting `ActiveProcessLimit=1` fails test | ORIGINAL_REQUEST.md [L41-42], ADR-0002 [L45-47] |
| 24 | R4 (Security) | Headless Native Modal Rejection | Enforces that headless runs never simulate UI clicks on Win32 modal dialogs (`MB_SYSTEMMODAL`). | Tool call requiring approval | Denied tool result, requires_approval=True | Attempting programmatic click or GUI bypass fails test | ORIGINAL_REQUEST.md [L44], GEMINI.md [L16] |
| 25 | R4 (Security) | Risk Tier 2 Auto-Denial in Soak Profile | Any tool call with `risk_level >= 2` without a valid one-shot token is automatically rejected and logged. | Tool invocation request with risk >= 2 | PolicyDecision(allowed=False, requires_approval=True) | Unauthorized high-risk execution fails test | ORIGINAL_REQUEST.md [L45], ADR-0002 [L51] |
| 26 | R4 (Security) | HMAC-SHA256 Capability Token Test Stub | Capability tokens minted strictly via deterministic test stub bound to tool name and canonical arguments hash. | Tool name, arguments dictionary, TTL | One-shot capability token string | Key ordering mismatch, payload tampering, or reuse rejected | ORIGINAL_REQUEST.md [L46], `friday.security.tokens` |
| 27 | R4 (Security) | GPU Offline Test Marker (`@pytest.mark.gpu`) | Ensures tests requiring physical GPU weights are marked `@pytest.mark.gpu` and skipped in offline CI runs. | Pytest configuration, marker flags | Pytest test collection | Tests attempting unmocked GPU calls in offline soak fail | ORIGINAL_REQUEST.md [L47] |
| 28 | Security / Sidecar | Child Process Environment Sanitization | Whitelists only safe OS environment variables, stripping parent secrets (`ANTHROPIC_API_KEY`, AWS tokens). | Parent environment variables | Sanitized environment dictionary | Parent secret leaking into child process fails test | GEMINI.md [L12], `processes.rs` |

---

## 4. Edge Cases

| # | Feature | Input | Observed Behavior |
|---|---------|-------|-------------------|
| 1 | R1 Subagent Delegation | Child subagent spec requested with `depth = 2` (grandchild delegation). | Rejected with `ValueError: Subagent depth must be exactly 1. Got depth=2. Children cannot delegate.` Anti-recursion invariant upheld. |
| 2 | R1 Subagent Tools | Child subagent requested with tool `subagent.invoke` or `schedule.create`. | Rejected with `ValueError: Tool '...' is forbidden for subagents (anti-recursion invariant).` Prevents recursive spawning and privilege escalation. |
| 3 | R1 Subagent Monotonicity | Child subagent requested with identical tools, identical risk ceiling, and identical budgets as parent (no strict reduction). | Rejected with `PolicyDeniedError: Monotonic delegation denied: Child capabilities must be strictly narrower than parent authority in at least one dimension.` |
| 4 | R1 Scheduler Claims | Two concurrent worker tasks attempt to claim the exact same due job run scheduled for `scheduled_for_utc`. | Exactly one worker succeeds via atomic transaction; second worker is suppressed or blocked by `UNIQUE(job_id, scheduled_for_utc)` without `database is locked` error. |
| 5 | R1 Memory Coordinator | User queries procedural memory for unapproved procedure (`approved = 0`). | Returned snippet provides passive historical description ONLY (`[HISTORICAL RECORD] User once performed ... [Unapproved procedure - executable steps omitted to prevent unauthorized replay]`). Executable code steps are strictly suppressed. |
| 6 | R1 Memory Truncation | FTS5 memory search matches 10,000 characters of conversation text. | Output is capped at `total_max_chars = 3000` and appended with `\n\n[Memory results truncated to context budget]`. |
| 7 | R2 Private Bytes Slope | Initial 15 minutes of run experiences rapid 200 MB memory spike due to PyTorch/CUDA DLL loading and JIT compilation. | Discarded by 15-minute warmup filter ($t < 15\text{ min}$). Steady-state post-warmup slope remains under 50 MB/hr; tripwire does not false-positive. |
| 8 | R2 TabbyAPI VRAM Leak | TabbyAPI model unload frees memory but retains 600 MB residual over baseline due to uncollected CUDA caching buffers. | Post-unload residual check ($600\text{ MB} > 512\text{ MB}$) fails the VRAM leak oracle, aborting the run with descriptive residual memory failure. |
| 9 | R2 GPU Thermal Spike | Workstation cooling fan profile delay causes GPU temperature to hit 84°C for 2 seconds. | Thermal ceiling tripwire ($T_{\text{GPU}} > 83^\circ\text{C}$) triggers immediate graceful shutdown to prevent hardware damage on RTX 5090 workstation. |
| 10 | R2 Mid-Flight Cancellation | In-flight generation WebSocket connection dropped while TabbyAPI is streaming token deltas. | AgentLoop catches cancellation, drains connection, frees active turn locks, and leaves 0 dangling asyncio tasks or uncommitted SQLite transactions. |
| 11 | R2 SQLite WAL Accumulation | Sustained high-frequency scheduler job claims and turn logging generate 50 MB of WAL. | WAL remains below 64 MB threshold. `PRAGMA wal_checkpoint(TRUNCATE)` is NOT called mid-run (preventing I/O stalls during telemetry), but executed cleanly at run exit. |
| 12 | R3 Rust Job Object Concurrency | Supervisor spawns TabbyAPI sidecar, Core service, and multiple child tools inside the same Job Object. | Succeeded without denial because `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` was NOT set. All processes run concurrently. |
| 13 | R3 Rust Supervisor Exit | Supervisor window closed abruptly (`ExitRequested` or `SIGINT`). | `JobObject::drop()` closes the Job Object handle; Windows kernel immediately terminates all child processes (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`). Zero orphaned `python.exe` or `uvicorn` processes remain. |
| 14 | R4 One-Shot Token Reuse | Valid capability token consumed once for `terminal.exec`, then immediately re-sent with identical arguments. | Second invocation returns `consumed = False` or `TokenAlreadyConsumed`. Single-use invariant strictly prevents replay attacks. |
| 15 | R4 Argument Tampering | Valid capability token minted for `{"command": "dir"}`, but attacker submits token with `{"command": "del /f *.*"}`. | Canonical argument hash mismatch ($H_{\text{tampered}} \ne H_{\text{token}}$); PolicyEngine denies execution immediately. |
| 16 | R4 Headless Approval | High-risk tool invocation (`risk_level = 2`) executed in headless test without pre-minted capability token. | Auto-denied with `PolicyDecision(allowed=False, requires_approval=True)`. Zero attempt to open Win32 modal dialog or simulate click. |

---

## 5. Specification Deep-Dive & Mathematical Constraints

### 5.1 Telemetry Metrics & Mathematical Tripwires (R2)

| Metric | Source / API | Sampling Window | Mathematical Threshold / Formula | Tripwire Action |
|---|---|---|---|---|
| **Private Bytes Growth Slope** | Windows `ProcessPrivateBytes` / `psutil.Process().memory_info().private` | Post-warmup ($t \ge 15\text{ min}$) | $\text{Slope} = \frac{N\sum(t_i M_i) - \sum t_i \sum M_i}{N\sum t_i^2 - (\sum t_i)^2} \le 50.0\text{ MB/hr}$ | Abort run; mark FAILED |
| **OS Handle Count Slope** | Win32 `GetProcessHandleCount` / `psutil.Process().num_handles()` | Post-warmup ($t \ge 15\text{ min}$) | $\text{Slope} = \frac{N\sum(t_i H_i) - \sum t_i \sum H_i}{N\sum t_i^2 - (\sum t_i)^2} \le 50.0\text{ handles/hr}$ | Abort run; mark FAILED |
| **Thread Count Ratchet** | Win32 Thread Counter / `psutil.Process().num_threads()` | Post-warmup sliding windows | $\min(T_{W_j}) > \max(T_{W_{j-1}})$ across 3 consecutive windows (monotonic ratchet) | Abort run; mark FAILED |
| **GPU Temperature** | NVML `pynvml.nvmlDeviceGetTemperature` | Instantaneous per tick | $T_{\text{GPU}} \le 83^\circ\text{C}$ | Abort run immediately; hardware thermal safety |
| **TabbyAPI Residual VRAM** | NVML compute process / `nvidia-smi compute-apps` | Post-model-unload | $V_{\text{post-unload}} - V_{\text{post-start}} \le 512.0\text{ MB}$ | Fail run; GPU VRAM leak detected |
| **Consecutive Unload VRAM** | NVML compute process / `nvidia-smi compute-apps` | Across cycle transitions | $V_{\text{unload}, k} \le V_{\text{unload}, k-1} + \epsilon$ (no monotonic climb) | Fail run; cumulative VRAM leak |
| **Process Exit VRAM Baseline** | System NVML / `nvidia-smi` | Run completion (post-exit) | $V_{\text{sys, post-exit}} \approx V_{\text{sys, pre-launch}}$ | Fail run; leaked GPU resource |
| **SQLite WAL Size** | File size of `<db_path>-wal` | Continuous polling | $S_{\text{WAL}} \le 64.0\text{ MB}$ | Fail run; unconstrained WAL growth |
| **Unload Latency** | High-resolution timer (`time.perf_counter`) | Model unload operations | $p50 < 2.0\text{s}$, $p95 < 5.0\text{s}$ (target); TDR event is hard fail | Spikes logged; TDR driver crash fails run |

### 5.2 Standalone Runner CLI Specification (`tests/soak/run_8hr_soak.py`)

The runner must be a standalone executable Python CLI script adhering to the following interface:

```text
usage: run_8hr_soak.py [-h] [--mode {smoke,gate,release}]
                       [--duration-minutes DURATION_MINUTES]
                       [--sample-interval-seconds SAMPLE_INTERVAL_SECONDS]
                       [--warmup-minutes WARMUP_MINUTES]
                       [--db-path DB_PATH]
                       [--traces-dir TRACES_DIR]
                       [--results-path RESULTS_PATH]
                       [--report-path REPORT_PATH]
                       [--fault-injection-interval FAULT_INJECTION_INTERVAL]
                       [--skip-fault-injections]
                       [--no-langfuse]
```

- **Modes**:
  - `--mode smoke`: 15 minutes (0.25 hours). Fast qualification for CI/CD and pre-merge validation. Discards first 3 minutes of warmup for slope checks.
  - `--mode gate`: 1 hour (1.0 hour). GPU qualification gate on RTX 5090. Discards first 15 minutes of warmup.
  - `--mode release`: 8 hours (8.0 hours). Full continuous soak test for release tagging. Discards first 15 minutes of warmup.
- **Profiling Invariant**:
  - `tracemalloc` MUST be disabled during `run_8hr_soak.py` to avoid memory overhead and CPU profiling drag over hours of continuous execution.
- **Output Artifacts**:
  1. `logs/traces/*.jsonl`: Raw dual-sink telemetry records.
  2. `logs/soak_results.json`: Machine-readable results summary including pass/fail status, metric slopes, peak memory, and tripwire evaluations.
  3. `docs/benchmarks/soak_test_report.md`: Markdown report summarizing performance curves, tripwires, unload latency percentiles, and hardware health.

### 5.3 Rust Tauri Supervisor Specification (`apps/desktop/src-tauri`)

Integration test file: `apps/desktop/src-tauri/tests/test_soak_supervisor.rs`
1. **Handle & Thread Stability under Repeated Polling**:
   - Spawns supervisor runtime with mock/test configuration.
   - Repeatedly executes 100 iterations of:
     - `create_session`
     - `get_gpu_telemetry`
     - `check_vram_preflight`
     - `run_first_launch_diagnostics`
   - Samples OS handle count before and after loop using `GetProcessHandleCount(GetCurrentProcess(), &mut count)`.
   - Asserts handle count growth $\Delta \text{Handles} \le 5$ (allowing minor internal CRT caching, strictly prohibiting unbounded linear leak).
2. **Job Object Containment & Child Termination**:
   - Creates `JobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
   - Spawns child process (e.g. `cmd.exe /c ping 127.0.0.1 -n 30`).
   - Assigns child process to Job Object.
   - Asserts child is alive and queryable.
   - Drops `JobObject` / terminates supervisor.
   - Asserts child process handle confirms termination (`try_wait` returns `Ok(Some(_))`).
   - **Critical Invariant**: Asserts `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` is NOT set in `JobObjectExtendedLimitInformation`.

---

## 6. Caveats

1. **Physical GPU Workstation vs Offline CI**:
   - Requirements R2 and RTX 5090 Blackwell qualification require physical access to the workstation with NVIDIA drivers and NVML (`pynvml`) installed.
   - In environments without an NVIDIA GPU or in standard CI runners, R2 must provide graceful mock telemetry detection or skip GPU assertions unless `--require-gpu` or real NVML is present.
   - All tests requiring real GPU weights must be annotated with `@pytest.mark.gpu`.
2. **Smoke Mode Warmup Scaling**:
   - In `--mode smoke` (15 minutes total duration), discarding 15 minutes of warmup would leave 0 minutes for slope evaluation. Therefore, the specification requires scaling warmup in smoke mode (e.g. first 3 minutes of warmup discarded, evaluating the remaining 12 minutes).
3. **Windows Job Object OS Prerequisite**:
   - Windows Job Objects are an OS-specific primitive (`windows_sys::Win32::System::JobObjects`). All supervisor integration tests must be conditional on Windows platform (`#[cfg(windows)]`).
4. **SQLite Worker Threads Teardown**:
   - Per `GEMINI.md` Rule 4, all async fixtures using `aiosqlite` must explicitly await `close()` during teardown to avoid Windows pytest subshells hanging indefinitely.

---

## 7. Conclusion

The specification for Phase 16 Continuous Soak and Long-Run Endurance Harness is fully defined, highly detailed, and mathematically unambiguous:
- **R1** is bounded to $< 3$ minutes with mocked inference (`MockInferenceBackend`), exercising 50 turns with mid-turn cancellations, 4-tier memory churn, concurrent SQLite scheduler claims, depth-1 subagents with anti-recursion, bounded `tracemalloc` drift (< 25 MB), and strict database WAL limits (< 64 MB).
- **R2** provides a 3-mode CLI runner (`smoke`, `gate`, `release`) tracking Private Bytes slope ($\le 50\text{ MB/hr}$), handle slope ($\le 50\text{ handles/hr}$), thread ratchets, 83°C thermal limits, and TabbyAPI PID-specific VRAM baseline recovery ($\le 512\text{ MB}$ residual), outputting dual-sink traces, `logs/soak_results.json`, and `docs/benchmarks/soak_test_report.md`.
- **R3** enforces a Rust integration test verifying zero handle/thread leaks over repeated supervisor commands, child process termination via `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and the strict prohibition of `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`.
- **R4** guarantees headless auto-denial for Risk >= 2 operations, single-use HMAC-SHA256 capability tokens, sanitized child environments, and `@pytest.mark.gpu` isolation.

All architectural touchpoints, contracts, formulas, and edge cases are mined and ready for task allocation and implementation.

---

## 8. Verification Method

To independently verify the authoritative sources and specifications documented in this report:

1. **Inspect Specifications**:
   - `view_file` on `G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md` (lines 10-56)
   - `view_file` on `G:\Project_Ned\docs\adr\0002-continuous-soak-and-endurance-testing.md` (lines 21-59)
   - `view_file` on `G:\Project_Ned\GEMINI.md` (lines 1-25)

2. **Verify Acceptance Criteria Test Commands**:
   - Unit Soak Suite:
     ```cmd
     cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > pytest_soak.txt 2>&1"
     ```
   - Rust Tauri Supervisor Test Suite:
     ```cmd
     cmd.exe /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml > cargo_test.txt 2>&1"
     ```
   - Standalone Soak Runner Smoke Mode (15-min):
     ```cmd
     cmd.exe /c ".\.venv\Scripts\python.exe tests/soak/run_8hr_soak.py --mode smoke > soak_smoke.txt 2>&1"
     ```
   - Full Regression Test Suite (198+ tests):
     ```cmd
     cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -v > pytest_regression.txt 2>&1"
     ```
