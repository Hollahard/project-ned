# Milestone 1: Fast Mocked Soak Test Suite Handoff Report

## 1. Observation

### 1.1 Initial Failures in `tests/soak/test_soak_endurance.py`
Running the original test draft revealed 4 critical failures and 1 superficial pass:
1. `test_50_turn_agent_loop_with_cancellations`:
   ```
   AttributeError: type object 'InferenceEventType' has no attribute 'ASSISTANT_DELTA'
   ```
   In `friday.inference.protocol`, event types are `TOKEN_DELTA`, `REASONING_DELTA`, `TOOL_CALL`, `USAGE`, `FINISH`, `ERROR`. Streaming delta chunks use attribute `content`, not `delta`. Furthermore, orphaned background tasks from unawaited `cancel_later()` were leaking on the event loop.
2. `test_memory_churn_and_fts5_integrity`:
   ```
   sqlite3.IntegrityError: FOREIGN KEY constraint failed
   ```
   In `friday.storage.db`, `semantic_memory.source_session_id` references `sessions(id)` with `PRAGMA foreign_keys=ON;`. No session with `id="soak-mem-session"` had been inserted. Additionally, Tier 1 Working Memory, Tier 2 Episodic Memory (`messages_fts`), Tier 4 Procedural Memory (`procedural_memory_fts`), and `MEMORY_OUTPUT_FENCE_PREFIX` were missing.
3. `test_concurrent_scheduler_soak_and_frozen_snapshot`:
   ```
   AttributeError: type object 'RunState' has no attribute 'COMPLETED'
   ```
   In `friday.scheduler.models`, `RunState` has `SUCCESS = "success"`, not `COMPLETED`. Concurrency was constrained because claims sequentially hit `max_workspace_runs=1`. Duplicate suppression (`idempotency_key`), lease heartbeats (`refresh_lease`), and expired lease recovery (`recover_expired_leases`) were not exercised.
4. `test_subagent_depth1_delegation_and_grandchild_rejection`:
   The draft passed superficially by only checking `SubagentSpec(depth=1)` but omitted `ParentCapabilities`, `validate_capability_containment` (caller depth=1 grandchild refusal, monotonic tool/budget/reduction escalation checks), dynamic parent revocation, and `BudgetExceededError`.
5. `test_high_risk_auto_denial_in_soak_mode`:
   ```
   AttributeError: 'CapabilityTokenManager' object has no attribute 'compute_canonical_args_hash'
   ```
   `CapabilityTokenManager` defines `compute_args_hash(arguments)` and `mint_token(tool_name, arguments)`. Replay defense, argument tampering defense, and tool-spoofing defense were not verified.

### 1.2 Implemented Fixes in `tests/soak/test_soak_endurance.py`
- Implemented `SoakMockInference.generate()` yielding `InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content=...)` with 1ms cooperative delays and ending with `FINISH` (`finish_reason="stop"`).
- Executed 50 turns with mid-turn cancellations triggered on `assistant.delta` via `cancel_event.set()` (odd multiples of 7) and `agent_loop.cancel_turn(session_id)` (multiples of 14).
- Verified zero leaked active cancels (`len(agent_loop._active_cancels) == 0`), zero leaked background tasks (`len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()]) == 0`), and bounded tracemalloc drift (< 25 MB).
- Implemented full 4-tier memory churn in `test_memory_churn_and_fts5_integrity`:
  - Tier 1 Working: `add_note`, `get_notes`, `format_summary`, `clear`.
  - Tier 2 Episodic: `sessions` + `messages` insert, `coordinator.episodic.search`, delete triggering trigger `messages_ad`.
  - Tier 3 Semantic: `coordinator.semantic.save`, update triggering `semantic_memory_au`, delete triggering `semantic_memory_ad`.
  - Tier 4 Procedural: `procedural_memory` unapproved vs approved (`coordinator.procedural.approve`), delete triggering `procedural_memory_ad`.
  - Search: verified `MEMORY_OUTPUT_FENCE_PREFIX`, historical unapproved notice with steps omitted, and approved procedure steps.
  - Integrity: `PRAGMA integrity_check`, `PRAGMA quick_check`, `PRAGMA foreign_key_check` (0 violations), and `PRAGMA wal_checkpoint(TRUNCATE)`.
- Implemented concurrent scheduler soak:
  - 10 jobs with `idempotency_key`. Verified duplicate job re-creation returns original job instance.
  - Concurrent claims via `asyncio.gather` across 4 worker instances with `max_workspace_runs=10` and `max_installation_runs=10`.
  - Lease heartbeats (`refresh_lease`) succeed for owner and fail for rogue workers.
  - Expired lease detection and recovery (`recover_expired_leases` and `confirm_run_quiescence`).
  - Completed runs using `RunState.SUCCESS`.
  - Verified WAL file size < 64 MB.
  - Verified `ScheduledExecutionGuard` against forbidden anti-recursion tools, unallowed tools, and Risk >= 2 tools.
- Implemented subagent containment verification:
  - `SubagentSpec` depth=1 validation and anti-recursion tool bans.
  - Caller depth=1 rejection via `validate_capability_containment` (grandchild refusal).
  - Monotonic containment escalation checks (tool escalation, token budget escalation, strict reduction invariant).
  - Dynamic parent revocation and token budget reconciliation (`BudgetExceededError`).
- Implemented security auto-denial invariants:
  - Headless auto-denial for Risk >= 2 without token (`requires_approval=True`, `allowed=False`).
  - Minting valid HMAC-SHA256 test tokens (`token_mgr.mint_token(tool.name, args)`).
  - Approval with token (`allowed=True`).
  - Single-use replay rejection (`allowed=False`).
  - Argument tampering rejection (`allowed=False`).
  - Tool-spoofing rejection (`allowed=False`).
- Teardown: Wrapped in `soak_memory_db` and `soak_scheduler_db` async fixtures that explicitly `await close()`, preventing hung SQLite threads on Windows.

### 1.3 Execution Results
1. **Soak Test Suite**:
   ```
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"
   5 passed in 4.08s (0 warnings)
   ```
2. **Core Regression Suite**:
   ```
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q"
   216 passed in 20.91s
   ```

---

## 2. Logic Chain

1. **Protocol Adherence**:
   - `AgentLoop.run_turn` processes generator events from `inference.generate(request)`.
   - By yielding `InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content=...)` and finishing with `InferenceEvent(type=InferenceEventType.FINISH, finish_reason="stop", ...)`, the agent loop streams tokens and records metrics without schema mismatches.
2. **Deterministic Interruption Without Task Leaks**:
   - Waiting for the first `assistant.delta` event before signaling `cancel_event.set()` or `agent_loop.cancel_turn(session_id)` ensures the cancellation occurs deterministically while generation is active.
   - This eliminates background coroutine delays (`asyncio.sleep`) and avoids race conditions, guaranteeing zero orphaned tasks and zero leaked entries in `agent_loop._active_cancels`.
3. **Database Integrity & Teardown**:
   - Enforcing `PRAGMA foreign_keys=ON;` requires valid foreign keys; creating the session in `sessions` satisfies the foreign key for `semantic_memory.source_session_id` and `messages.session_id`.
   - Asynchronous `yield` fixtures awaiting `db.close()` ensure all connection worker threads terminate cleanly upon test completion, preventing subshell deadlocks on Windows.
4. **Idempotency, Concurrency, and Leases**:
   - `create_job` matches on `idempotency_key` and returns the existing job if already present, satisfying duplicate suppression.
   - Setting `max_workspace_runs=10` and `max_installation_runs=10` allows `claim_next_due_job` to atomically admit multiple runs concurrently across distinct worker IDs in `asyncio.gather`.
   - `recover_expired_leases` inspects `lease_expires_at_utc < now_utc`, transitions abandoned runs to `stopping`, and pauses the parent schedule.
5. **Monotonic Containment & Anti-Recursion**:
   - `SubagentSpec` validates `depth == 1` and rejects anti-recursion tool prefixes at instantiation.
   - `validate_capability_containment` validates `parent.depth == 0`, refusing grandchild delegations when caller depth is 1.
   - `validate_capability_containment` checks tool subsets, risk ceilings, token budgets, and the strict reduction invariant.
   - `SubagentExecutionGuard` intercepts calls at runtime, verifying parent live tools and enforcing token budget ceilings (`BudgetExceededError`).
6. **Security R4 Headless Invariants**:
   - High-risk operations evaluated without capability tokens in headless mode are auto-denied (`allowed=False, requires_approval=True`).
   - Mints test HMAC-SHA256 tokens bound to tool name and canonical argument hash (`compute_args_hash`).
   - First call consumes the token; replay, tampered arguments, or mismatched tool names are rejected.

---

## 3. Caveats

- **No Production Code Alterations**: Write ownership was strictly constrained to `tests/soak/test_soak_endurance.py`. No code in `services/core/` was modified.
- **Mock Inference vs Physical GPU**: The soak endurance suite uses `SoakMockInference` designed for offline, deterministic execution without physical RTX 5090 hardware dependencies. Tests requiring real GPU weights must use `@pytest.mark.gpu`.

---

## 4. Conclusion

All 5 endurance test cases in `tests/soak/test_soak_endurance.py` are fully implemented with genuine, complete logic adhering to ADR-0002 and Milestone 1 specifications.
- `test_50_turn_agent_loop_with_cancellations`: PASS (43 completed, 7 cancelled, zero leaked tasks, zero leaked cancel events, tracemalloc drift < 25 MB).
- `test_memory_churn_and_fts5_integrity`: PASS (Working, Episodic, Semantic, Procedural tiers exercised, output fence verified, PRAGMA checks verified, zero FK violations, WAL truncate).
- `test_concurrent_scheduler_soak_and_frozen_snapshot`: PASS (idempotency duplicate suppression, concurrent worker claims, lease heartbeats & rogue rejection, expired lease recovery, RunState.SUCCESS, WAL < 64 MB, ScheduledExecutionGuard).
- `test_subagent_depth1_delegation_and_grandchild_rejection`: PASS (depth=1 enforcement, grandchild refusal, monotonic escalation checks, parent revocation, BudgetExceededError).
- `test_high_risk_auto_denial_in_soak_mode`: PASS (Risk >= 2 auto-denial, HMAC-SHA256 token minting/consumption, replay rejection, tamper rejection, spoof rejection).
- Full suite execution time: **4.08 seconds** (threshold < 180 seconds).
- Full regression suite: **216 passed** in 20.91 seconds (zero regressions).

---

## 5. Verification Method

To independently verify the implementation:

1. **Run Soak Endurance Test Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_run.txt 2>&1"
   ```
   Inspect `soak_run.txt` to confirm `5 passed in ~4s` with zero warnings, then delete `soak_run.txt`.

2. **Run Full Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_run.txt 2>&1"
   ```
   Inspect `reg_run.txt` to confirm `216 passed` with zero failures, then delete `reg_run.txt`.
