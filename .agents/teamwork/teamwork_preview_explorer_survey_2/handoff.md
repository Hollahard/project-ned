# Phase 16 Python Core Codebase Survey Handoff Report

## 1. Observation

### 1.1 Inference Backend & Mock Implementations
- **Protocol Definition (`services/core/src/friday/inference/protocol.py:81-104`)**:
  - `InferenceBackend` protocol requires:
    ```python
    async def health(self) -> HealthStatus: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def load_model(self, profile: ModelProfile) -> None: ...
    async def unload_model(self) -> None: ...
    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]: ...
    ```
  - Crucial observation: The generation method name is `generate(self, request: ChatRequest)`, NOT `chat()`.
  - Event types (`protocol.py:63-70`): `InferenceEventType.TOKEN_DELTA`, `REASONING_DELTA`, `TOOL_CALL`, `USAGE`, `FINISH`, `ERROR`.
  - Event structure (`protocol.py:72-79`): `InferenceEvent(type, content="", tool_call=None, finish_reason=None, prompt_tokens=0, completion_tokens=0)`.
- **Existing Mock Backend (`services/core/src/friday/inference/mock.py:17-95`)**:
  - `MockInferenceBackend(InferenceBackend)` already exists.
  - Initializes in `ModelState.UNLOADED`; transitions to `ModelState.READY` upon `load_model(profile)` or manual setting.
  - Generates token deltas and finishes with `finish_reason="stop"`.
- **Production Backend (`services/core/src/friday/inference/tabby.py:22-190`)**:
  - `TabbyBackend(InferenceBackend)` communicates with TabbyAPI on `http://127.0.0.1:5000` via `httpx.AsyncClient`.
  - Endpoints: GET `/health` (returns `vram_used`, `vram_total`), GET `/v1/models`, POST `/v1/model/load`, POST `/v1/model/unload`, POST `/v1/chat/completions` (SSE streaming).
- **Gaming Mode (`services/core/src/friday/inference/gaming_mode.py:29-105`)**:
  - `GamingModeController.activate(backend, agent_loop)` cancels active in-flight turns, calls `backend.unload_model()`, measures evacuation time (target <2.0s), and verifies VRAM freed.

### 1.2 Memory Modules (4-Tier Memory Churn)
- **Coordinator (`services/core/src/friday/memory/coordinator.py:22-94`)**:
  - `MemoryCoordinator(db_manager: DatabaseManager)` exposes:
    - `self.working = WorkingMemory()` (`services/core/src/friday/memory/working.py`)
    - `self.episodic = EpisodicMemory(db_manager)` (`services/core/src/friday/memory/episodic.py`)
    - `self.semantic = SemanticMemory(db_manager)` (`services/core/src/friday/memory/semantic.py`)
    - `self.procedural = ProceduralMemory(db_manager)` (`services/core/src/friday/memory/procedural.py`)
    - `async def search(self, query: str, workspace_root: str, tiers: Optional[List[str]] = None, limit_per_tier: int = 3, total_max_chars: int = 3000) -> str`
  - All outputs wrapped in `MEMORY_OUTPUT_FENCE_PREFIX` (`coordinator.py:14-19`) to prevent memory prompt injection.
  - Crucial observation: `MemoryCoordinator` does NOT have `save_episodic_memory()` or `save_semantic_fact()`. Sub-tiers must be invoked directly or via standard storage.
- **Tier 1 - Working Memory (`services/core/src/friday/memory/working.py:6-30`)**:
  - In-memory scratchpad: `add_note(note)`, `get_notes()`, `clear()`, `format_summary(max_chars=1000)`.
- **Tier 2 - Episodic Memory (`services/core/src/friday/memory/episodic.py:10-83`)**:
  - Queries `messages` table joined to `sessions` table (`s.working_directory = :workspace_root`) and FTS5 virtual table `messages_fts` (`services/core/src/friday/storage/db.py:60-74`).
  - Synced automatically by SQLite triggers `messages_ai` and `messages_ad`.
  - Message insertion is done via `SessionManager.add_message(session_id, role, content)` (`services/core/src/friday/sessions/manager.py:97-118`).
- **Tier 3 - Semantic Memory (`services/core/src/friday/memory/semantic.py:26-141`)**:
  - Backed by table `semantic_memory` and FTS5 virtual table `semantic_memory_fts(title, content)` (`storage/db.py:76-107`).
  - Methods:
    - `save(entry: SemanticMemoryEntry) -> str`
    - `get(memory_id: str, workspace_root: str) -> Optional[SemanticMemoryEntry]`
    - `search(query: str, workspace_root: str, category: Optional[str] = None, limit: int = 5) -> List[SemanticMemoryEntry]`
    - `delete(memory_id: str, workspace_root: str) -> bool`
- **Tier 4 - Procedural Memory (`services/core/src/friday/memory/procedural.py:27-147`)**:
  - Backed by table `procedural_memory` and FTS5 virtual table `procedural_memory_fts(title, steps, source)` (`storage/db.py:109-142`).
  - Methods:
    - `save(entry: ProceduralMemoryEntry, is_system_authorized: bool = False) -> str`: forces `approved = 0` unless `is_system_authorized=True`.
    - `approve(memory_id: str, workspace_root: str) -> bool`: promotes to `approved = 1`.
    - `search(query: str, workspace_root: str, limit: int = 5) -> List[ProceduralMemoryEntry]`
    - `delete(memory_id: str, workspace_root: str) -> bool`

### 1.3 SQLite Scheduler
- **Scheduler Storage (`services/core/src/friday/scheduler/db.py:364-710`)**:
  - `claim_next_due_job`:
    ```python
    async def claim_next_due_job(
        self,
        now_utc: int,
        owner_instance: str,
        ownership_generation: int = 1,
        lease_duration_seconds: int = 60,
        grace_seconds: int = 60,
        max_workspace_runs: int = 1,
        max_installation_runs: int = 2,
        max_daily_workspace_tokens: int = 50000,
        max_daily_installation_tokens: int = 100000,
    ) -> Optional[tuple["ScheduledJob", "JobRun"]]:
    ```
    - Worker identifier argument is named `owner_instance` (NOT `worker_id`).
    - Returns a tuple of `(job, run)` or `None`.
  - `complete_run`:
    ```python
    async def complete_run(
        self,
        run_id: str,
        owner_instance: str,
        ownership_generation: int,
        final_state: "RunState",
        consumed_tokens: int,
        output_summary: Optional[str] = None,
        error_summary: Optional[str] = None,
        outcome_certain: bool = True,
        next_run_at_utc: Optional[int] = None,
    ) -> bool:
    ```
  - `RunState` enum (`services/core/src/friday/scheduler/models.py:37-47`): `RUNNING`, `STOPPING`, `SUCCESS`, `FAILED`, `DENIED`, `CANCELLED`, `TIMEOUT`, `INTERRUPTED`, `SKIPPED`. Note: The success state is `RunState.SUCCESS`, NOT `RunState.COMPLETED`.
  - Deduplication: `scheduled_jobs.idempotency_key UNIQUE`. Duplicate `create_job` calls return the existing job.
  - Frozen Permission Snapshot (`models.py:84-135`): `JobPermissionSnapshot` enforces `extra='forbid'`, `max_risk_level <= 1`, and strictly rejects forbidden tool prefixes: `schedule.`, `subagent.`, `policy.`, `system.shutdown`.

### 1.4 Subagent Delegation
- **Specification Model (`services/core/src/friday/subagents/models.py:130-170`)**:
  - `SubagentSpec` required fields:
    - `role: str`
    - `task_prompt: str`
    - `parent_session_id: str`
    - `parent_turn_id: str`
    - `workspace_root: str`
  - Optional / bounded defaults:
    - `depth: int = 1` (must be exactly 1)
    - `allowed_tool_ids: List[str] = []`
    - `max_risk_level: int = 0` (0..2)
    - `token_budget: int = 4000` (100..32000)
    - `iteration_budget: int = 10` (1..10)
    - `duration_seconds_budget: int = 120` (5..120)
  - `extra="forbid"`: Reject any unknown fields.
- **Monotonic Capability Containment & Anti-Recursion (`models.py:172-235`)**:
  - `validate_capability_containment(parent: ParentCapabilities, child: SubagentSpec) -> None`:
    - Enforces `parent.depth == 0` and `child.depth == 1`.
    - If caller depth is not 0 (e.g., depth 1 subagent trying to delegate to grandchild), raises `PolicyDeniedError("Delegation rejected: caller depth is 1; only depth 0 may delegate.")`.
    - Enforces `child_tools.issubset(parent_tools)`.
    - Enforces `child.max_risk_level <= parent.max_risk_level`.
    - Enforces `child.token_budget <= parent.token_budget`.
    - Enforces `is_path_within_root(child.workspace_root, parent.workspace_root)`.
    - Strict reduction invariant: At least one capability dimension must be strictly narrower than parent.
  - Anti-recursion tools forbidden at construction: `FORBIDDEN_SUBAGENT_TOOL_PREFIXES = ("subagent.", "schedule.", "policy.", "system.shutdown")`.

### 1.5 Telemetry, Tracing, and Process Spawning
- **Telemetry (`services/core/src/friday/telemetry/`)**:
  - Dual-sink: `LocalJsonlSink` logs to `logs/traces/trace_<date>.jsonl`, while `LangfuseSink` mirrors to Langfuse if configured.
  - GPU Telemetry: `TelemetryProvider` (`services/core/src/friday/inference/telemetry.py:26-102`) queries NVML on RTX 5090 (VRAM total/used/free, temperature, watts, GPU/mem utilization).
- **Windows Process Metrics (ADR-0002 R2 Requirements)**:
  - Private Bytes: In Windows, standard RSS fluctuates due to working set trimming. Private Bytes is queried via Win32 `psapi.GetProcessMemoryInfo` -> `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`.
  - Handle Count: Win32 `kernel32.GetProcessHandleCount`.
  - Thread Count: `kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)` iterating threads.
  - TCP Loopback: Filter connections on `127.0.0.1` for target PID (via `netstat -ano -p tcp` or `GetExtendedTcpTable`).
  - TabbyAPI VRAM Attribution: Query `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits` or NVML `nvmlDeviceGetComputeRunningProcesses` for TabbyAPI PID.
- **Windows Job Object Containment (`apps/desktop/src-tauri/src/processes.rs:50-80` & ADR-0002 §4)**:
  - Rust supervisor wraps children in Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
  - **CRITICAL INVARIANT**: Do NOT set `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` or `ActiveProcessLimit = 1` on the supervisor job object, ensuring Core, TabbyAPI, and child tools run concurrently without job denial.

### 1.6 PolicyEngine & Capability Tokens
- **Policy Engine (`services/core/src/friday/tools/policy.py:27-100`)**:
  - `policy.evaluate(tool: Tool, arguments: Dict[str, Any], capability_token: str | None = None) -> PolicyDecision`:
    - Synchronous method (not async `evaluate_call`).
    - Takes `tool: Tool` instance (not tool string name).
    - If `tool.risk_level >= 2` or `tool.requires_approval` and no valid token is provided, returns `PolicyDecision(allowed=False, requires_approval=True)`.
  - One-shot capability token generation (`services/core/src/friday/security/tokens.py:35-51`):
    - `token, args_hash = token_mgr.mint_token(tool.name, arguments)`.
    - Single-use, HMAC-SHA256 bound to canonical argument hash (`json.dumps(arguments, sort_keys=True, separators=(",", ":"))`).

### 1.7 Current Failure Analysis of `tests/soak/test_soak_endurance.py`
`pytest_soak_test.txt` revealed 5 out of 5 failures in the draft test suite:
1. `test_50_turn_agent_loop_with_cancellations`: `TypeError: 'async for' requires an object with __aiter__ method, got coroutine`.
   - Root cause: `SoakMockInference` implemented `chat(request)` instead of `generate(request)`. `AgentLoop` calls `self.inference.generate(request)`.
2. `test_memory_churn_and_fts5_integrity`: `AttributeError: 'MemoryCoordinator' object has no attribute 'save_episodic_memory'`.
   - Root cause: `MemoryCoordinator` only coordinates searches. Episodic messages belong to sessions/messages; semantic facts belong to `coordinator.semantic.save(entry)`.
3. `test_concurrent_scheduler_soak_and_frozen_snapshot`: `TypeError: SchedulerDatabaseManager.claim_next_due_job() got an unexpected keyword argument 'worker_id'`.
   - Root cause: Keyword argument is `owner_instance`. Also return value is a `(job, run)` tuple, and `complete_run` requires `(run_id, owner_instance, ownership_generation, RunState.SUCCESS, consumed_tokens)`.
4. `test_subagent_depth1_delegation_and_grandchild_rejection`: `ValidationError: 10 validation errors for SubagentSpec`.
   - Root cause: `SubagentSpec` was initialized with obsolete/invalid fields (`subagent_id`, `max_iterations`, `max_tokens`, etc.) and missed required fields (`role`, `task_prompt`, `parent_turn_id`). Also called non-existent static methods on `SubagentExecutionGuard`.
5. `test_high_risk_auto_denial_in_soak_mode`: `AttributeError: 'PolicyEngine' object has no attribute 'evaluate_call'`.
   - Root cause: `PolicyEngine` method is synchronous `policy.evaluate(tool, arguments, capability_token)`.

---

## 2. Logic Chain

1. **Inference Backend Contract**:
   - `services/core/src/friday/agent/loop.py:172` calls `async for event in self.inference.generate(request):`.
   - `services/core/src/friday/inference/protocol.py:101` defines `generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]`.
   - Therefore, any mock inference backend used in fast soak tests MUST implement `async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]` yielding `InferenceEvent` with valid `InferenceEventType` (`TOKEN_DELTA`, `FINISH`).
2. **Memory Architecture & FTS5 Concurrency**:
   - `MemoryCoordinator` delegates to `WorkingMemory`, `EpisodicMemory`, `SemanticMemory`, and `ProceduralMemory`.
   - SQLite triggers `messages_ai`/`messages_ad`, `semantic_memory_ai`/`semantic_memory_ad`/`semantic_memory_au`, and `procedural_memory_ai`/`procedural_memory_ad`/`procedural_memory_au` keep FTS5 indexes in sync.
   - Therefore, a memory churn test must insert via `session_manager.add_message()` (or `messages` SQL table), `coordinator.semantic.save()`, and `coordinator.procedural.save()`, query via `coordinator.search()`, delete via `coordinator.semantic.delete()` and `coordinator.procedural.delete()`, and assert `PRAGMA integrity_check` is `ok`.
3. **Scheduler Concurrency & Claim Contracts**:
   - `SchedulerDatabaseManager.claim_next_due_job(now_utc=..., owner_instance=...)` uses `BEGIN IMMEDIATE;` to atomically lease candidate jobs.
   - Jobs are created with `JobPermissionSnapshot` enforcing `max_risk_level <= 1` and anti-recursion tool bans.
   - Deduplication is guaranteed via `idempotency_key UNIQUE`.
   - Therefore, concurrent scheduler testing must pass `owner_instance`, unpack `(job, run)`, and complete via `complete_run(run.id, owner_instance, 1, RunState.SUCCESS, tokens)`.
4. **Subagent Delegation & Anti-Recursion**:
   - `SubagentSpec` requires `role`, `task_prompt`, `parent_session_id`, `parent_turn_id`, `workspace_root`, with `depth=1` strictly enforced.
   - `validate_capability_containment(parent, child)` rejects any caller with `parent.depth != 0`, preventing subagents from spawning grandchildren.
   - `SubagentExecutionGuard` intercepts tool execution dynamically against child grant and parent live permissions.
   - Therefore, testing depth-1 delegation and anti-recursion must instantiate `ParentCapabilities` and `SubagentSpec` with exact required fields and verify `validate_capability_containment` raises `PolicyDeniedError` for depth > 0 callers or escalating grants.
5. **Security Invariants & Capability Tokens**:
   - In soak mode, headless operation forbids Win32 UI click simulation.
   - Tools with `risk_level >= 2` evaluated by `PolicyEngine.evaluate(tool, args)` return `allowed=False, requires_approval=True` when no token is present.
   - Minting test tokens via `token_mgr.mint_token(tool.name, args)` enables execution with `allowed=True`.
6. **Endurance Runner (R2) Telemetry Architecture**:
   - To fulfill ADR-0002 R2, `tests/soak/run_8hr_soak.py` must track Private Bytes (`GetProcessMemoryInfo`), handle counts (`GetProcessHandleCount`), thread counts (`CreateToolhelp32Snapshot`), and loopback connections (`netstat`) for Core, TabbyAPI, and Supervisor.
   - TabbyAPI VRAM must be attributed specifically via `nvidia-smi` compute-apps query or NVML `nvmlDeviceGetComputeRunningProcesses`.
   - Must implement 15-minute warmup discard, 50 MB/hr slope tripwire, 50 handles/hr tripwire, and 83°C GPU tripwire.
   - Must output `logs/soak_results.json` and generate `docs/benchmarks/soak_test_report.md`.

---

## 3. Caveats

- **tracemalloc usage**: As specified in ADR-0002 §1, `tracemalloc` is suitable for the fast 3-minute mocked soak test suite (`tests/soak/test_soak_endurance.py`), but MUST be disabled during multi-hour long-run endurance runs (`tests/soak/run_8hr_soak.py`) to prevent profiling overhead and false memory accumulation.
- **Physical GPU Weights in CI**: CI pipelines run headlessly without guarantee of real GPU weights loaded; hence R1 mocked soak suite and mock approval stubs must never require real GPU execution. Only tests marked with `@pytest.mark.gpu` touch the physical RTX 5090 TabbyAPI sidecar.
- **Async Teardown**: Per GEMINI.md rules, any test creating `DatabaseManager` or `SchedulerDatabaseManager` must explicitly await `close()` in an async fixture teardown to prevent hanging `aiosqlite` threads on Windows.

---

## 4. Conclusion

1. **R1 Fast Mocked Soak Suite (`tests/soak/test_soak_endurance.py`)**:
   - The current draft file contains 5 API mismatches causing test failures.
   - Fixing these requires aligning `SoakMockInference` with `InferenceBackend.generate()`, updating memory calls to match `MemoryCoordinator` + `SemanticMemory` + `SessionManager`, fixing `claim_next_due_job(owner_instance=...)` and `complete_run()`, updating `SubagentSpec` and `validate_capability_containment()`, and calling synchronous `PolicyEngine.evaluate()`.
   - Once updated, R1 will pass in under 30 seconds with 50 turns, 4-tier memory churn, concurrent scheduler claims, depth-1 delegation guard, and high-risk token rejection.
2. **R2 Standalone Long-Run Endurance Runner (`tests/soak/run_8hr_soak.py`)**:
   - Does not yet exist and needs to be implemented.
   - Must implement CLI flags (`--mode smoke|gate|release`), Win32 process metrics sampling (Private Bytes, handles, threads, TCP connections), Tabby PID compute-apps VRAM attribution via NVML / `nvidia-smi`, tripwires (15m warmup discard, 50MB/hr Private Bytes slope, 50 handles/hr, 83°C temp), periodic fault injections (Gaming Mode evacuation, mid-turn cancellation), dual-sink telemetry, `logs/soak_results.json`, and markdown report generation.
3. **R3 Supervisor Contract (`apps/desktop/src-tauri`)**:
   - Rust supervisor process manager `JobObject` is configured properly with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
   - Tests in `apps/desktop/src-tauri/tests/` verify handle cleanup and kill-on-drop. Additional test verifying absence of `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` will satisfy R3.

---

## 5. Verification Method

To verify these survey observations independently:
1. **Inspect Inference Contract**:
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\inference\protocol.py" StartLine=81 EndLine=104`
2. **Inspect Memory Coordinator**:
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\memory\coordinator.py" StartLine=22 EndLine=94`
3. **Inspect Scheduler Claim & Complete**:
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\scheduler\db.py" StartLine=364 EndLine=400`
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\scheduler\db.py" StartLine=642 EndLine=670`
4. **Inspect Subagent Delegation Contracts**:
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\subagents\models.py" StartLine=130 EndLine=210`
5. **Inspect Policy Engine Evaluation**:
   `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\tools\policy.py" StartLine=40 EndLine=95`
6. **Verify Current Regression Suite Baseline**:
   `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > test_baseline.txt 2>&1"`
