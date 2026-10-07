# Milestone 1: Fast Mocked Soak Test Suite Review & Adversarial Challenge Report

## 1. Observation

### 1.1 Scope and Test Suite Execution
Target File: `tests/soak/test_soak_endurance.py` (816 lines).
Execution Command:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > rev1_soak.txt 2>&1"
```
Observed Output in `rev1_soak.txt`:
```
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- G:\Project_Ned\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: G:\Project_Ned
configfile: pytest.ini
plugins: anyio-4.15.1, asyncio-1.4.0, mock-3.16.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests/soak/test_soak_endurance.py::test_50_turn_agent_loop_with_cancellations PASSED [ 20%]
tests/soak/test_soak_endurance.py::test_memory_churn_and_fts5_integrity PASSED [ 40%]
tests/soak/test_soak_endurance.py::test_concurrent_scheduler_soak_and_frozen_snapshot PASSED [ 60%]
tests/soak/test_soak_endurance.py::test_subagent_depth1_delegation_and_grandchild_rejection PASSED [ 80%]
tests/soak/test_soak_endurance.py::test_high_risk_auto_denial_in_soak_mode PASSED [100%]

============================== 5 passed in 4.01s ==============================
```
Timing: **4.01 seconds** (threshold is < 180 seconds). Warnings: **0 warnings**.

### 1.2 Regression Suite Execution
Execution Command:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > rev1_reg.txt 2>&1"
```
Observed Output in `rev1_reg.txt`:
```
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 20.79s
```
Zero regressions across all existing suites.

### 1.3 Detailed Code Observations in `tests/soak/test_soak_endurance.py`
1. **Mock Protocol Alignment**:
   - Lines 69-95: `SoakMockInference` implements `async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]`.
   - Lines 82-88: Yields `InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content=token + " ")` with cooperative `await asyncio.sleep(0.001)`.
   - Lines 89-95: Finishes with `InferenceEvent(type=InferenceEventType.FINISH, finish_reason="stop", prompt_tokens=..., completion_tokens=...)`.
2. **Turn Cancellation Interleaving & Invariant Verification**:
   - Lines 175-194: Alternates cancellation triggers between `cancel_event.set()` (odd multiples of 7) and `agent_loop.cancel_turn(session_id)` (multiples of 14). Trigger occurs deterministically upon the first `assistant.delta` event.
   - Lines 195-199: Asserts `turn.started` and `turn.canceled` in emitted event types, and `turn.completed` strictly absent.
   - Lines 219-232: Asserts `len(agent_loop._active_cancels) == 0`, `len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()]) == 0`, and tracemalloc memory drift `< 25600.0 KB`.
3. **4-Tier Memory Churn & FTS5 Synchronization**:
   - Lines 246-255: Inserts valid root session into `sessions` to strictly satisfy `PRAGMA foreign_keys=ON;` on `semantic_memory.source_session_id`.
   - Lines 258-268: Exercises Working Memory (`add_note`, `get_notes`, `format_summary`, `clear`).
   - Lines 270-295: Exercises Episodic Memory (50 messages, `coordinator.episodic.search`, delete triggering `messages_ad`).
   - Lines 298-329: Exercises Semantic Memory (50 inserts, 10 updates triggering `semantic_memory_au`, 25 deletes triggering `semantic_memory_ad`).
   - Lines 331-359: Exercises Procedural Memory (20 inserts with `approved=0`, 3 approvals triggering `procedural_memory_au`, 5 deletes triggering `procedural_memory_ad`).
   - Lines 363-376: Unified FTS5 search validates `MEMORY_OUTPUT_FENCE_PREFIX`, redaction of unapproved steps (`[HISTORICAL RECORD]`), and inclusion of approved steps (`[APPROVED PROCEDURE]`).
   - Lines 380-399: Validates `PRAGMA integrity_check` == "ok", `PRAGMA quick_check` == "ok", `PRAGMA foreign_key_check` (0 violations), `PRAGMA wal_checkpoint(TRUNCATE)`, and WAL size < 64 MB.
4. **Concurrent Scheduler & Snapshot Guard**:
   - Lines 409-436: Creates 10 scheduled jobs with `JobPermissionSnapshot` and unique `idempotency_key`.
   - Lines 438-454: Re-creating a job with an existing `idempotency_key` returns the original job (duplicate suppression).
   - Lines 457-479: Concurrent claims across 4 worker IDs using `asyncio.gather` with `max_workspace_runs=10` and `max_installation_runs=10`. Validates all admitted job IDs and run IDs are distinct sets (zero double claims).
   - Lines 480-498: Validates `refresh_lease` succeeds for genuine owner and returns `False` for rogue workers.
   - Lines 500-540: Simulates abandoned job past lease deadline; `recover_expired_leases` detects and transitions it; confirms quiescence.
   - Lines 542-553: Completes all runs via `RunState.SUCCESS`.
   - Lines 564-581: `ScheduledExecutionGuard` verifies permitted invocation passes, while anti-recursion tools (`schedule.create`, `subagent.invoke`, `policy.update`, `system.shutdown`), unauthorized tools, and Risk >= 2 tools raise `SchedPolicyDeniedError`.
5. **Subagent Monotonic Containment & Anti-Recursion**:
   - Lines 589-616: Validates depth-1 delegation with strict parameter containment against `ParentCapabilities` (depth 0).
   - Lines 618-629: Instantiating `SubagentSpec(depth=2)` raises `ValueError("depth must be exactly 1")`.
   - Lines 632-652: `validate_capability_containment` with caller depth=1 raises `SubagentPolicyDeniedError("caller depth is 1; only depth 0 may delegate")` (grandchild refusal).
   - Lines 653-665: `SubagentSpec` rejects forbidden prefixes at construction (`subagent.invoke`, etc.).
   - Lines 666-708: Escalation tests assert failures for unheld tools, exceeding token budget, or failing the strict reduction invariant.
   - Lines 709-741: `SubagentExecutionGuard` blocks `subagent.delegate`, ungranted tools, parent-revoked tools, and enforces token budget ceiling with `BudgetExceededError`.
6. **Security Headless Auto-Denial & One-Shot Capability Tokens**:
   - Lines 753-763: Headless invocation of Risk >= 2 tool without token results in auto-denial (`allowed=False`, `requires_approval=True`).
   - Lines 764-780: Approved invocation with HMAC-SHA256 test token minted via `mint_token` succeeds (`allowed=True`).
   - Lines 781-789: Replaying consumed token is denied (`allowed=False`).
   - Lines 790-803: Tampered argument payload is denied (`allowed=False`).
   - Lines 804-816: Mismatched tool name is denied (`allowed=False`).
7. **Process & Resource Teardown**:
   - Lines 119-139: Asynchronous fixtures `soak_memory_db` and `soak_scheduler_db` explicitly await `close()` on teardown, preventing background worker thread hangs on Windows.

---

## 2. Logic Chain

1. **Integrity Validation**:
   - All tests execute actual core runtime code: `AgentLoop`, `MemoryCoordinator`, `SchedulerDatabaseManager`, `PolicyEngine`, `validate_capability_containment`, and `CapabilityTokenManager`.
   - No hardcoded results, mock facades without logic, or dummy bypassing were found.
   - Independent test execution reproduced the exact results reported by Worker M1.
2. **Fulfillment of Requirement R1**:
   - The test suite is decorated with `@pytest.mark.soak`.
   - The suite completed in 4.01 seconds, well below the 3-minute requirement.
   - 50 continuous turns were executed with mid-turn cancellations, with zero leaked active cancels, zero orphaned background tasks, and bounded memory drift (< 25 MB).
   - 4 memory tiers were churned, including FTS5 table sync and trigger firings, verified by clean SQLite integrity checks, zero foreign key violations, and WAL truncation.
   - Scheduler concurrency was exercised with 4 worker instances claiming simultaneously without collisions, duplicate suppression was verified via idempotency keys, and expired lease recovery was verified.
   - Depth-1 subagent monotonic containment, grandchild refusal, and budget reconciliation were strictly enforced.
   - Zero `database is locked` errors occurred.
3. **Fulfillment of Requirement R4**:
   - Headless execution is maintained throughout; no Win32 GUI modals are spawned or simulated.
   - Risk >= 2 operations are auto-denied in the absence of valid one-shot capability tokens.
   - HMAC-SHA256 test stub tokens bound to canonical arguments and tool names were verified for minting, consumption, single-use invalidation, tamper resistance, and tool binding.
4. **Workspace Conformance (GEMINI.md)**:
   - Output piped to temporary log file and deleted immediately after inspection.
   - Asynchronous database teardown handles worker threads cleanly.
   - Tool parameters schema completely defined for `HighRiskTool`.

---

## 3. Caveats

- **Mocked Inference vs Real GPU**: As specified in R1 and R4, this suite tests the orchestration and system harness using `SoakMockInference` offline. Hardware GPU execution (e.g. TabbyAPI NVML VRAM recovery, thermal tripwires) is scoped to Milestones 3 & 4 under `@pytest.mark.gpu`.
- **Duration**: The 4-second runtime satisfies the CI soak qualification constraint (< 3 minutes); extended multi-hour endurance (15m, 1h, 8h) is handled by the standalone runner in Milestone 3.

---

## 4. Conclusion

**Verdict: APPROVE**

The implementation of `tests/soak/test_soak_endurance.py` is exemplary, robust, and completely adheres to R1, R4, and ADR-0002. All 5 test cases pass cleanly in 4.01 seconds, introduce zero regressions, and exhibit zero integrity violations.

---

## 5. Verification Method

To independently verify the implementation:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > rev_check.txt 2>&1"
```
Inspect `rev_check.txt` with `view_file` to confirm 5 passed in < 180s, then delete `rev_check.txt`:
```cmd
cmd.exe /c "del rev_check.txt"
```

---

## 6. Formal Review Report

```markdown
## Review Summary

**Verdict**: APPROVE

## Findings
None. All R1 and R4 requirements are comprehensively satisfied.

## Verified Claims
- Fast soak completion < 3 minutes → verified via pytest (4.01s) → pass
- 50 turns with mid-turn cancellations → verified via pytest (43 completed, 7 cancelled, 0 leaks) → pass
- 4-tier memory churn + FTS5 integrity → verified via PRAGMA checks and FTS5 search fence → pass
- Concurrent scheduler claims & idempotency → verified via asyncio.gather across 4 workers → pass
- Depth-1 subagent monotonic containment → verified via spec validation & grandchild denial → pass
- Risk >= 2 headless auto-denial & HMAC tokens → verified via PolicyEngine evaluation → pass
- Full regression suite integrity → verified via 216 tests passing → pass

## Coverage Gaps
None for Milestone 1 scope. Real GPU weight qualification is segregated to @pytest.mark.gpu per R4.

## Unverified Items
None.
```

---

## 7. Adversarial Challenge Report

```markdown
## Challenge Summary

**Overall risk assessment**: LOW

## Challenges

### [Low] Challenge 1: Cancellation Timing Interleaving
- Assumption challenged: Cooperative sleep (1ms) in mock generator guarantees cancellation interleaving without race conditions.
- Attack scenario: If token generation finished before cancellation could be signaled, the turn would register as completed rather than canceled.
- Mitigation verified: In the test, cancellation is signaled inside the consumer loop upon receiving the very first `assistant.delta` event. Because the consumer processes the first delta synchronously before subsequent tokens are yielded, cancellation is guaranteed to take effect before completion.

### [Low] Challenge 2: Session Re-use After Cancellation
- Assumption challenged: Subsequent turns on a session that previously experienced cancellation might inherit a cancelled state.
- Attack scenario: If `_active_cancels` is not cleared upon turn exit, subsequent turns would immediately abort.
- Mitigation verified: 50 turns are distributed across 5 reusable session IDs (`i % 5`). Sessions 2, 4, 1, 3, 0 experience mid-turn cancellations on turns 7, 14, 21, 28, 35, 42, 49. Subsequent turns on these exact sessions complete cleanly because `_active_cancels.pop(session_id, None)` is guaranteed in the `finally` block of `AgentLoop.run_turn`.

### [Low] Challenge 3: SQLite Concurrency Contention
- Assumption challenged: Multiple concurrent claims could encounter SQLite locking errors under load.
- Mitigation verified: `SchedulerDatabaseManager` utilizes an internal `asyncio.Lock` coupled with `BEGIN IMMEDIATE;` to serialize admission queries within the event loop, ensuring zero `database is locked` errors.

## Stress Test Results
- Session re-use post-cancellation → expected: clean turn completion → actual: 43 successful turns → pass
- Concurrent worker claim collision → expected: unique job & run allocations → actual: all IDs distinct → pass
- Rogue worker lease refresh → expected: rejected (False) → actual: False → pass
- Stale worker abandoned lease → expected: recovered and paused → actual: detected in recovered_ids → pass
- Subagent privilege escalation → expected: PolicyDeniedError → actual: raised and caught → pass
- Token replay / tamper / spoof → expected: rejected → actual: rejected → pass

## Unchallenged Areas
- TabbyAPI NVML VRAM allocation and physical GPU temperature monitoring (scoped to Milestone 3 / hardware execution).
```
