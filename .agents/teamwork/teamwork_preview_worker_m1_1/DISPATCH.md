## 2026-10-07T15:36:46Z
You are the Worker for Milestone 1: Fast Mocked Soak Test Suite.
Your working directory is G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m1_1.
Your parent is orchestrator_1 (conversation ID: 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context and inputs to read FIRST:
1. G:\Project_Ned\.agents\teamwork\ORIGINAL_REQUEST.md (MANDATORY: read this first!)
2. G:\Project_Ned\.agents\teamwork\orchestrator_1\PROJECT.md
3. G:\Project_Ned\GEMINI.md (Strict workspace rules: cmd.exe /c test piping, async db teardown, isolated stat mocking)
4. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m1_1\handoff.md (Turns & cancellation blueprint)
5. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m1_2\handoff.md (4-tier memory & concurrent scheduler blueprint)
6. G:\Project_Ned\.agents\teamwork\teamwork_preview_explorer_m1_3\handoff.md (Subagent containment & security auto-denial blueprint)
7. G:\Project_Ned\tests\soak\test_soak_endurance.py

Write Ownership:
You have EXCLUSIVE write ownership of:
- G:\Project_Ned\tests\soak\test_soak_endurance.py
DO NOT modify production source code in services/core/ — all 5 test cases in test_soak_endurance.py must be implemented correctly against existing production contracts.

Objective:
Implement all fixes and complete coverage for the 5 tests in `tests/soak/test_soak_endurance.py`:
1. `SoakMockInference` & `test_50_turn_agent_loop_with_cancellations`:
   - Use `generate(request) -> AsyncIterator[InferenceEvent]` with `InferenceEventType.TOKEN_DELTA` (content) and `FINISH` (finish_reason="stop").
   - Exercise 50 turns with mid-turn cancellations via `cancel_event.set()` and `agent_loop.cancel_turn(session_id)`.
   - Bounded tracemalloc drift (< 25 MB), zero leaked tasks, zero leaked cancel events.
2. `test_memory_churn_and_fts5_integrity`:
   - Satisfy foreign key constraints by pre-populating session in `sessions` table.
   - Exercise all 4 tiers: Working memory notes/summary/clear, Episodic messages insert/search/delete (testing `messages_ad`), Semantic save/update/delete (`semantic_memory_ad`), Procedural unapproved vs approved (`procedural_memory_fts`).
   - Assert `MEMORY_OUTPUT_FENCE_PREFIX` on coordinator search.
   - Assert `PRAGMA integrity_check`, `quick_check`, `foreign_key_check` return 'ok' / zero violations.
   - Follow async db fixture teardown with `await db.close()`.
3. `test_concurrent_scheduler_soak_and_frozen_snapshot`:
   - Create 10 scheduled jobs with `idempotency_key`.
   - Verify duplicate job suppression via `idempotency_key`.
   - Execute concurrent atomic claims across simulated workers via `asyncio.gather` with `max_workspace_runs=10` and `max_installation_runs=10`.
   - Verify lease heartbeats (`refresh_lease`) and rejection of rogue workers.
   - Verify expired lease recovery (`recover_expired_leases`).
   - Complete runs using `RunState.SUCCESS`.
   - Verify WAL size < 64 MB.
   - Verify `ScheduledExecutionGuard` policy enforcement.
4. `test_subagent_depth1_delegation_and_grandchild_rejection`:
   - Verify `SubagentSpec` depth=1 validation and anti-recursion tool bans.
   - Verify `validate_capability_containment` rejects caller depth=1 (grandchild refusal).
   - Verify monotonic containment escalation checks (tools, budget, strict reduction invariant).
   - Verify `SubagentExecutionGuard` dynamic parent revocation and token budget reconciliation (`BudgetExceededError`).
5. `test_high_risk_auto_denial_in_soak_mode`:
   - Headless auto-denial for Risk >= 2 without token.
   - Minting HMAC-SHA256 test token (`token_mgr.mint_token(tool.name, args)`).
   - Approval via token; single-use replay rejection; tampered arguments rejection; tool-spoofing rejection.

Verification Step:
Run tests following GEMINI.md:
`cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak > soak_run.txt 2>&1"`
Inspect `soak_run.txt` with view_file, confirm all 5 tests pass in < 3 minutes (should finish in < 15 seconds) with 0 warnings. Then delete `soak_run.txt`.
Also verify regression suite:
`cmd.exe /c ".\.venv\Scripts\pytest.exe services/core/tests/ tests/security/ tests/e2e/ -q > reg_run.txt 2>&1"`
Inspect `reg_run.txt` and delete it.

Deliver your results in G:\Project_Ned\.agents\teamwork\teamwork_preview_worker_m1_1\handoff.md.
Send a completion message back to parent using send_message with recipient 3e3ebb48-c2d9-47f5-ab92-cbc0f9a97e22 when done.
