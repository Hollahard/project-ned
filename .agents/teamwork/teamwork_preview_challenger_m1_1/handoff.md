# Milestone 1 Challenger Handoff Report: Adversarial Verification of `tests/soak/test_soak_endurance.py`

## 1. Observation

### 1.1 Baseline Verification of Worker Deliverable
Executed baseline validation for `tests/soak/test_soak_endurance.py`:
- Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"`
- Log output:
  ```
  tests/soak/test_soak_endurance.py::test_50_turn_agent_loop_with_cancellations PASSED [ 20%]
  tests/soak/test_soak_endurance.py::test_memory_churn_and_fts5_integrity PASSED [ 40%]
  tests/soak/test_soak_endurance.py::test_concurrent_scheduler_soak_and_frozen_snapshot PASSED [ 60%]
  tests/soak/test_soak_endurance.py::test_subagent_depth1_delegation_and_grandchild_rejection PASSED [ 80%]
  tests/soak/test_soak_endurance.py::test_high_risk_auto_denial_in_soak_mode PASSED [100%]
  5 passed in 4.12s
  ```
- 3-run sequential loop stability check:
  - Command: `cmd.exe /c "for /l %i in (1,1,3) do .\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -q -m soak"`
  - Results: Run 1: 5 passed in 4.01s; Run 2: 5 passed in 3.99s; Run 3: 5 passed in 3.99s. Zero flakiness or orphaned processes.

### 1.2 Full System Regression Suite
- Command: `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q"`
- Result: `216 passed in 21.01s`. Zero regressions introduced across core, security, and e2e suites.

### 1.3 Empirical Adversarial Stress Results
An adversarial test suite was authored and executed to test failure modes and bypass attempts:

1. **Mid-tool cancellation**:
   - Tested cancellation while a tool is actively running (`SlowTool` sleeping cooperatively).
   - Result: Agent loop detected cancellation, aborted further execution, yielded `turn.canceled` (not `turn.completed`), and evicted the session from `_active_cancels`. No hung tasks.
2. **Abandoned generator session registry leak**:
   - Tested consumer breaking out of `async for event in agent_loop.run_turn()` on the first delta chunk.
   - Result: Explicitly awaiting `gen.aclose()` executes the generator's `finally:` block, completely clearing `_active_cancels[session_id]`.
3. **Multi-session concurrent turns**:
   - 10 concurrent sessions running turns in `asyncio.gather` with interleaved cancellations on odd-numbered sessions.
   - Result: Odd sessions yielded `turn.canceled`, even sessions yielded `turn.completed`. `len(agent_loop._active_cancels) == 0` upon completion.
4. **Broadcast global cancellation**:
   - 5 active streaming sessions cancelled simultaneously via `agent_loop.cancel_current_turn()`.
   - Result: All 5 received `turn.canceled`, registry completely cleared.
5. **Subagent depth-1 bypass via `model_construct`**:
   - Instantiated child spec bypassing Pydantic field validators with `depth=2` and `depth=0` using `SubagentSpec.model_construct(...)`.
   - Result: `validate_capability_containment` independently caught the illegal depth and raised `SubagentPolicyDeniedError: Delegation rejected: requested child depth is ...; must be exactly 1`.
6. **Tool ban bypass tricks (case variations and whitespace)**:
   - Evaluated `allowed_tool_ids=["SUBAGENT.RUN"]` and `allowed_tool_ids=[" subagent.run"]`.
   - Result: `validate_capability_containment` enforced `child_tools.issubset(parent_tools)`. Because parent only holds lowercase tools, unauthorized variations were rejected with `SubagentPolicyDeniedError: Escalation denied: child requested tools not held by parent`.
7. **Subagent path traversal attack**:
   - Invocation of `filesystem.read` with `path="safe_sandbox/../outside.txt"`.
   - Result: `SubagentExecutionGuard.check_tool_invocation` canonicalized the path and rejected it with `PolicyDeniedError: Path '...' is outside subagent workspace root '...'`.
8. **Scheduler high-contention worker race**:
   - 20 worker instances competing for 5 due jobs simultaneously via `asyncio.gather`.
   - Result: Exactly 5 jobs were admitted, 0 duplicate jobs claimed, 0 duplicate run IDs created. `PRAGMA integrity_check` returned `ok`.
9. **Memory FTS5 adversarial syntax stress**:
   - Tested special queries: `""`, `"`, `AND OR NOT`, `NEAR()`, `***`, `()()()`, `SELECT * FROM sessions`, `<script>`, `wal*`, `wal OR`, `a"b"c`.
   - Result: Handled cleanly without `sqlite3.OperationalError`. When results matched, output fence `MEMORY_OUTPUT_FENCE_PREFIX` was strictly enforced.

---

## 2. Logic Chain

1. **Protocol and Loop Correctness**:
   - In `tests/soak/test_soak_endurance.py`, `SoakMockInference.generate()` yields `InferenceEvent` instances with `type=InferenceEventType.TOKEN_DELTA` and ends with `InferenceEventType.FINISH`.
   - The 50 continuous turns execute in ~4.0s (well below the 3-minute requirement).
   - Cancellations during turn execution (turns 7, 14, 21, 28, 35, 42, 49) trigger proper handling: `turn.started` and `turn.canceled` are emitted, `turn.completed` is omitted.
   - Post-test assertions verify `len(agent_loop._active_cancels) == 0`, `len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()]) == 0`, and tracemalloc memory drift is bounded (< 25 MB).
2. **Subagent Containment Defense-in-Depth**:
   - Pydantic models validate `depth == 1` and ban forbidden tool prefixes (`subagent.`, `schedule.`, `policy.`, `system.shutdown`) at instantiation.
   - `validate_capability_containment` provides a second independent validation layer, rejecting `parent.depth != 0`, `child.depth != 1`, tool set escalation, risk level escalation, budget escalation, and identical capability allocations (strict reduction invariant).
   - Even if attacker code attempts to circumvent Pydantic validators using `model_construct`, `validate_capability_containment` catches and denies the delegation.
   - At runtime, `SubagentExecutionGuard` intercepts tool calls, verifies live parent tool authorization, checks path boundary containment against workspace root, and tracks token consumption against budget (`BudgetExceededError`).
3. **Database Concurrency and Integrity**:
   - Memory churn properly sets up valid foreign key relationships (`sessions.id` -> `semantic_memory.source_session_id`), preventing `IntegrityError`.
   - All 4 tiers (Working, Episodic, Semantic, Procedural) are churned with inserts, updates, and deletes triggering FTS5 triggers (`messages_ad`, `semantic_memory_au`, `semantic_memory_ad`, `procedural_memory_ad`).
   - SQLite PRAGMA checks (`integrity_check`, `quick_check`, `foreign_key_check`) pass with 0 errors.
   - Checkpoint truncation ensures WAL size remains well under 64 MB (< 1 MB observed).
   - Scheduler idempotency prevents duplicate job creation, and concurrent atomic claims prevent double-allocation under race conditions.
4. **Security Headless Auto-Denial**:
   - Headless invocations of Risk >= 2 tools without tokens are auto-denied (`requires_approval=True, allowed=False`).
   - Valid HMAC-SHA256 capability tokens minted for specific tools and argument hashes are accepted once, then successfully rejected upon replay, argument tampering, or tool-spoofing.

---

## 3. Caveats

- **Mocked Inference vs Real Model Weights**: In accordance with Requirement R1, this test suite uses `SoakMockInference` to achieve deterministic, offline execution under 3 minutes. Tests requiring physical GPU weights are marked with `@pytest.mark.gpu` and belong to subsequent long-run runner stages (Milestones 2-3).
- **Generator Early Exit Consumer Duty**: When consumers abandon an async generator early (e.g. `break` during `run_turn`), Python requires either explicit `await gen.aclose()` or garbage collection to run the generator's `finally:` block. In standard Friday usage, caller loops either run to completion or handle `aclose()`.
- **Review-Only Role**: No changes were made to production source code in `services/core/`. Temporary adversarial test scripts and logs were cleaned up immediately following empirical execution.

---

## 4. Conclusion

**Verdict: APPROVE**

`tests/soak/test_soak_endurance.py` satisfies all requirements of Milestone 1 and ADR-0002:
1. Fast soak suite executes 5 tests in **4.12 seconds** (threshold: < 180 seconds).
2. 50 turns with mid-turn cancellations complete with zero leaked tasks, zero leaked cancel events, and bounded memory drift (< 25 MB).
3. 4-tier memory churn and FTS5 search run without SQLite corruption, zero FK violations, and WAL < 64 MB.
4. Concurrent scheduler soak verifies idempotency, atomic claims across workers, lease recovery, and frozen permission snapshots.
5. Subagent depth-1 containment and anti-recursion invariants hold firmly against bypass attempts, subclassing, parameter tricks, and path traversals.
6. Headless auto-denial and one-shot HMAC-SHA256 capability token invariants are thoroughly validated.
7. Full regression suite continues to pass cleanly (216/216 passed).

---

## 5. Verification Method

To independently verify this assessment:

1. **Run Soak Test Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_run.txt 2>&1"
   ```
   Inspect `soak_run.txt` to verify `5 passed in ~4s (0 warnings)`. Delete `soak_run.txt` after inspection.

2. **Run Full Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_run.txt 2>&1"
   ```
   Inspect `reg_run.txt` to verify `216 passed`. Delete `reg_run.txt` after inspection.
