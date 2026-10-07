# Forensic Audit Report: Milestone 1 Fast Mocked Soak Test Suite

## Forensic Audit Summary
- **Work Product**: `tests/soak/test_soak_endurance.py`
- **Profile**: General Project (Integrity Forensics)
- **Integrity Mode**: Development Mode (as specified in `ORIGINAL_REQUEST.md`)
- **Verdict**: **CLEAN**

---

### Phase Results
1. **Hardcoded Test Result Detection**: PASS — No hardcoded test outputs, canned results, or trivial boolean shortcuts found.
2. **Facade & Dummy Implementation Detection**: PASS — `SoakMockInference` complies with `InferenceBackend` protocol; test tool `HighRiskTool` implements full `Tool` contract with valid `parameters_schema`; core classes under test (`AgentLoop`, `MemoryCoordinator`, `SchedulerDatabaseManager`, `validate_capability_containment`, `PolicyEngine`) are authentic production code from `services/core/src/friday`.
3. **Pre-Populated Artifact Detection**: PASS — All test cases strictly use `tmp_path` fixture for ephemeral database paths and trace directories; no dependency on pre-existing artifacts.
4. **Behavioral Test Execution (Soak Suite)**: PASS — `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"` passed 5/5 tests in 4.10 seconds (well under the 180s threshold) with zero warnings and no leaked processes.
5. **Behavioral Test Execution (Regression Suite)**: PASS — `cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q"` passed 216/216 tests in 20.82 seconds with zero regressions.
6. **50-Turn Execution Integrity**: PASS — Genuine execution of 50 turns through `AgentLoop.run_turn()`; 43 completed turns, 7 mid-flight cancelled turns (`i % 7 == 0`), zero active cancellation leaks (`len(agent_loop._active_cancels) == 0`), zero orphaned background tasks (`len(asyncio.all_tasks()) == 1`), and bounded tracemalloc drift (< 25 MB).
7. **4-Tier Memory Churn & SQLite/FTS5 Integrity**: PASS — All 4 tiers (Working, Episodic, Semantic, Procedural) exercised with real CRUD; FTS5 triggers verified on insert, update, and delete; `MEMORY_OUTPUT_FENCE_PREFIX` validated; PRAGMA `integrity_check`, `quick_check`, `foreign_key_check` (0 violations), and `wal_checkpoint(TRUNCATE)` validated.
8. **Concurrent Scheduler & Frozen Snapshot Integrity**: PASS — 10 jobs created with `idempotency_key`; duplicate suppression validated; 10 concurrent worker claims across 4 worker IDs in `asyncio.gather` validated without duplicate claims; lease heartbeats and rogue rejection verified; expired lease recovery verified; `RunState.SUCCESS` completion verified; `ScheduledExecutionGuard` policy enforcement verified.
9. **Subagent Depth-1 Containment & Grandchild Refusal Integrity**: PASS — `SubagentSpec(depth=1)` monotonic containment and strict reduction validated; anti-recursion grandchild refusal validated at spec creation (depth=2 ValueError), containment check (`caller depth is 1; only depth 0 may delegate`), and dispatch guard (`subagent.delegate` anti-recursion denial); monotonic tool/budget escalation denials verified; dynamic parent revocation verified; `BudgetExceededError` ceiling verified.
10. **Headless Auto-Denial & Capability Token Integrity**: PASS — High-risk tool invocation without token auto-denied (`allowed=False`, `requires_approval=True`); valid HMAC-SHA256 test token approved; consumed token replay rejected; tampered arguments rejected; mismatched tool-name spoofing rejected.

---

## 1. Observation

Direct observations from forensic static analysis and terminal executions:

### 1.1 Test Suite Execution Output
Executed command per GEMINI.md:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_audit.txt 2>&1"
```
Verbatim stdout from `soak_audit.txt`:
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

============================== 5 passed in 4.10s ==============================
```

### 1.2 Regression Suite Execution Output
Executed command per GEMINI.md:
```cmd
cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_audit.txt 2>&1"
```
Verbatim stdout from `reg_audit.txt`:
```
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 20.82s
```

### 1.3 Code Inspection & Invariant Verifications in `tests/soak/test_soak_endurance.py`
- **Lines 143-235 (`test_50_turn_agent_loop_with_cancellations`)**:
  - Genuine loop: `for i in range(1, 51)` calling `agent_loop.run_turn()`.
  - Cancellations tested: On odd multiples of 7 (`cancel_event.set()`) and multiples of 14 (`agent_loop.cancel_turn(session_id)`).
  - Explicit count assertion: `assert completed_turns + cancelled_turns == 50`, `assert cancelled_turns == 7`, `assert completed_turns == 43`.
  - Zero leak assertions: `assert len(agent_loop._active_cancels) == 0`, `assert len(pending_tasks) == 0`.
  - Memory drift bounded: `tracemalloc` comparison asserts `total_diff_kb < 25600.0`.
- **Lines 239-400 (`test_memory_churn_and_fts5_integrity`)**:
  - Real SQLite session seeded: `INSERT INTO sessions ...` to satisfy `PRAGMA foreign_keys=ON;`.
  - 4 tiers churned: Tier 1 Working (50 notes, formatting, truncation check, clear), Tier 2 Episodic (50 messages inserted, FTS5 search for "Blackwell", 25 deleted triggering `messages_ad`), Tier 3 Semantic (50 entries saved, 10 updated triggering `semantic_memory_au`, 25 deleted triggering `semantic_memory_ad`), Tier 4 Procedural (20 entries saved, 3 approved, 5 deleted).
  - Output fence assertion: `assert search_results.startswith(MEMORY_OUTPUT_FENCE_PREFIX)`.
  - Executable steps omission for unapproved procedures: `assert "[Unapproved procedure - executable steps omitted to prevent unauthorized replay]" in search_results`.
  - Physical integrity: PRAGMA `integrity_check` ("ok"), PRAGMA `quick_check` ("ok"), PRAGMA `foreign_key_check` (0 violations), PRAGMA `wal_checkpoint(TRUNCATE)`.
- **Lines 404-582 (`test_concurrent_scheduler_soak_and_frozen_snapshot`)**:
  - Idempotency duplicate suppression: re-creating job with `idempotency_key="idem-soak-1"` returns original job (`assert existing_job.id == "job-soak-1"`).
  - Concurrency: 10 worker claims executed via `asyncio.gather(*claim_tasks)` across 4 worker IDs; uniqueness asserted (`assert len(claimed_job_ids) == len(set(claimed_job_ids))` and `assert len(claimed_run_ids) == len(set(claimed_run_ids))`).
  - Leases: owner heartbeat succeeds (`refreshed is True`), rogue heartbeat rejected (`stale_refreshed is False`).
  - Stale lease recovery: job with expired lease recovered via `recover_expired_leases(now_utc=now_utc)` and quiesced.
  - Final state transition: all claimed runs completed using `RunState.SUCCESS`.
  - Security guard: `ScheduledExecutionGuard` blocks anti-recursion tools, unallowed tools, and Risk >= 2 tools.
- **Lines 585-742 (`test_subagent_depth1_delegation_and_grandchild_rejection`)**:
  - Valid spec passes `validate_capability_containment` with monotonic reduction.
  - Anti-recursion A: `SubagentSpec(depth=2)` raises `ValueError("depth must be exactly 1")`.
  - Anti-recursion B: Subagent caller (`depth=1`) spawning grandchild raises `SubagentPolicyDeniedError("caller depth is 1; only depth 0 may delegate")`.
  - Anti-recursion C: Spec requesting forbidden tools raises `ValueError("forbidden for subagents")`.
  - Monotonic escalation: tool escalation and token budget escalation raise `SubagentPolicyDeniedError`.
  - Strict reduction: identical privileges raise `SubagentPolicyDeniedError("must be strictly narrower than parent authority")`.
  - Dynamic guard: `SubagentExecutionGuard` blocks `subagent.delegate`, ungranted tools, dynamically revoked parent tools, and token budget ceiling (`BudgetExceededError`).
- **Lines 745-816 (`test_high_risk_auto_denial_in_soak_mode`)**:
  - Headless auto-denial: Risk >= 2 call without token rejected (`allowed=False`, `requires_approval=True`).
  - Token minting: Valid HMAC-SHA256 test token authorized (`allowed=True`).
  - Replay defense: Replaying consumed token rejected (`allowed=False`).
  - Argument tampering: Mismatched argument hash rejected (`allowed=False`).
  - Tool-spoofing defense: Mismatched tool name rejected (`allowed=False`).

---

## 2. Logic Chain

1. **Premise**: Under the General Project Forensic Audit Profile and Development Mode integrity constraints (from `ORIGINAL_REQUEST.md`), a work product is rejected if it contains hardcoded test outputs, facade/dummy logic circumventing genuine behavior, or fabricated verification results.
2. **Evaluation of Test Authenticity**:
   - The test methods instantiate real classes (`AgentLoop`, `MemoryCoordinator`, `SchedulerDatabaseManager`, `PolicyEngine`, `CapabilityTokenManager`, `SubagentExecutionGuard`, `ScheduledExecutionGuard`).
   - Mocking is strictly limited to `SoakMockInference` (which inherits from `MockInferenceBackend`), as explicitly mandated by Requirement R1 for offline, fast soak execution.
   - Assertions inspect dynamic state changes (event stream deltas, database record existence, FTS5 query results, PRAGMA checks, cryptographic HMAC hash validation, exception triggers).
   - Therefore, the tests are genuine, rigorous, and assert authentic conditions rather than trivial no-ops.
3. **Evaluation of Concurrency and Database Cleanup**:
   - `soak_memory_db` and `soak_scheduler_db` fixtures are async generators that explicitly `await close()`, ensuring all `aiosqlite` worker threads terminate cleanly upon test completion.
   - Execution exited in 4.10 seconds without deadlocks or hung processes on Windows.
4. **Evaluation of Regression Impact**:
   - Running the full existing regression test suite (`services/core/tests/`, `tests/security/`, `tests/e2e/`) yielded 216 passed tests in 20.82 seconds with zero failures.
   - Therefore, the soak test suite introduces no regressions.
5. **Conclusion of Logic Chain**: Every check defined in the forensic verification procedure passed with direct empirical evidence. No integrity violations exist.

---

## 3. Caveats

- **Offline Mock vs. Physical RTX 5090 Execution**: As designed by Requirement R1 and ADR-0002, `tests/soak/test_soak_endurance.py` uses `SoakMockInference` to achieve fast (<3 min) deterministic qualification without physical GPU weights. Physical RTX 5090 hardware and NVML attribution are covered under Milestone 3 (`run_8hr_soak.py`), marked with `@pytest.mark.gpu`.
- **No Production Code Alterations**: The scope of Milestone 1 is confined to `tests/soak/test_soak_endurance.py`. No production files in `services/core/` were altered.

---

## 4. Conclusion

The work product `tests/soak/test_soak_endurance.py` demonstrates impeccable integrity, authentic logic, and comprehensive adherence to ADR-0002 and Milestone 1 requirements.

**Final Forensic Verdict**: **CLEAN**

---

## 5. Verification Method

To independently reproduce the forensic verification:

1. **Verify Soak Suite Execution**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_audit.txt 2>&1"
   ```
   Inspect `soak_audit.txt` to confirm 5 passed in < 5s with zero warnings, then delete `soak_audit.txt`.

2. **Verify Regression Suite**:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_audit.txt 2>&1"
   ```
   Inspect `reg_audit.txt` to confirm 216 passed, then delete `reg_audit.txt`.

3. **Verify Integrity of Source**:
   Inspect `tests/soak/test_soak_endurance.py` lines 143-816 to verify absence of hardcoded outputs, dummy mocks, or bypassed assertions.
