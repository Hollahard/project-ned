# Milestone 1 Explorer 2 Handoff Report: Memory Churn & Concurrent Scheduler Soak Fix Strategy

## 1. Observation

### 1.1 Direct Test Run Observations (`tests/soak/test_soak_endurance.py`)
Execution of the test suite via `cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -v -m soak"` revealed exact failures in both targeted tests:

1. **`test_memory_churn_and_fts5_integrity` Failure**:
   ```
   tests\soak\test_soak_endurance.py:207: in test_memory_churn_and_fts5_integrity
       mem_id = await coordinator.semantic.save(entry)
   services\core\src\friday\memory\semantic.py:51: in save
       await conn.execute(sql, entry.model_dump())
   .venv\Lib\site-packages\aiosqlite\core.py:63: in _connection_worker_thread
       result = function()
   E   sqlite3.IntegrityError: FOREIGN KEY constraint failed
   ```
   - Exact observation in `tests/soak/test_soak_endurance.py:194-207`:
     `session_id = "soak-mem-session"` was passed to `SemanticMemoryEntry(source_session_id=session_id)`.
   - Exact observation in `services/core/src/friday/storage/db.py:12, 83`:
     Line 12: `PRAGMA foreign_keys=ON;`
     Line 83: `source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL`
     No session record with `id = "soak-mem-session"` existed in the `sessions` table, causing SQLite to reject the insert.

2. **`test_concurrent_scheduler_soak_and_frozen_snapshot` Failure**:
   ```
   tests\soak\test_soak_endurance.py:295: in test_concurrent_scheduler_soak_and_frozen_snapshot
       final_state=RunState.COMPLETED,
   E   AttributeError: type object 'RunState' has no attribute 'COMPLETED'
   ```
   - Exact observation in `services/core/src/friday/scheduler/models.py:37-47`:
     The `RunState` enum defines:
     `RUNNING = "running"`, `STOPPING = "stopping"`, `SUCCESS = "success"`, `FAILED = "failed"`, `DENIED = "denied"`, `CANCELLED = "cancelled"`, `TIMEOUT = "timeout"`, `INTERRUPTED = "interrupted"`, `SKIPPED = "skipped"`.
     There is no `COMPLETED` member in `RunState` (`ScheduleState` has `COMPLETED`, but `complete_run()` requires `final_state: RunState`).

3. **Scheduler Concurrency Bottleneck**:
   - Exact observation in `services/core/src/friday/scheduler/db.py:371-372, 500-510`:
     `claim_next_due_job()` defaults to `max_workspace_runs: int = 1` and `max_installation_runs: int = 2`.
     Lines 503-510:
     ```python
     SELECT COUNT(*) FROM job_runs jr
     JOIN scheduled_jobs sj ON jr.job_id = sj.id
     WHERE sj.workspace_root = ? AND jr.state IN ('running', 'stopping')
     ```
     If `COUNT(*) >= max_workspace_runs`, candidate jobs for that workspace are skipped.
     In `test_soak_endurance.py:277-286`, all 10 jobs share `workspace_root = str(tmp_path)` and the loop sequentially attempts to claim without completing runs or overriding `max_workspace_runs`. Consequently, only 1 job could ever be claimed.

4. **Missing Coverage Against Requirement R1**:
   - In `test_memory_churn_and_fts5_integrity`:
     - Working memory (`WorkingMemory`: scratchpad notes, summary formatting, clear) was completely omitted.
     - Episodic memory (`EpisodicMemory`: sessions, messages, `messages_fts` synchronization via triggers `messages_ai` / `messages_ad`) was completely omitted.
     - Procedural memory (`ProceduralMemory`: `procedural_memory_fts`, unapproved passive summary vs approved steps) was completely omitted.
     - Output fencing assertion (`MEMORY_OUTPUT_FENCE_PREFIX`) was omitted.
   - In `test_concurrent_scheduler_soak_and_frozen_snapshot`:
     - Multi-worker concurrent claims via `asyncio.gather` were missing (it was a sequential loop on a single worker).
     - Lease heartbeats (`refresh_lease`) and stale owner rejection were missing.
     - Expired lease timeout recovery (`recover_expired_leases`) was missing.
     - Duplicate suppression verification via `idempotency_key` was missing.

5. **Async Database Teardown Violation (GEMINI.md Rule 4)**:
   - Both tests created `DatabaseManager` / `SchedulerDatabaseManager` instances directly and called `await db.close()` at the end of the test function without `try...finally` or async pytest fixtures. When an exception or assertion failure occurred, `await db.close()` was bypassed, leaving `aiosqlite` worker threads running and causing potential subshell process hangs on Windows.

---

## 2. Logic Chain

1. **Memory Foreign Key Integrity**:
   - Observation: SQLite runs with `PRAGMA foreign_keys=ON;`. `semantic_memory.source_session_id` references `sessions(id)`.
   - Deduction: To insert entries into `semantic_memory` with a non-null `source_session_id`, or to test episodic messages, a valid row in `sessions` (`id`, `title`, `created_at`, `updated_at`, `working_directory`, `model_profile`) must exist.
   - Action: Pre-populate the session row in the test setup before memory insertion.

2. **Full 4-Tier Memory Churn**:
   - Observation: Requirement R1 mandates "4-tier memory churn (rapid insert, FTS5 scoped search, soft deletion)".
   - Deduction:
     - Tier 1 (Working): In-memory scratchpad (`coordinator.working.add_note()`, `get_notes()`, `format_summary()`, `clear()`).
     - Tier 2 (Episodic): `sessions` + `messages` with `messages_fts` virtual table synced via `messages_ai`/`messages_ad`. Deleting messages exercises trigger `messages_ad`.
     - Tier 3 (Semantic): `semantic_memory` with `semantic_memory_fts`. Insertion, updates (`semantic_memory_au`), and deletion (`semantic_memory_ad`) via `coordinator.semantic.delete()`.
     - Tier 4 (Procedural): `procedural_memory` with `procedural_memory_fts`. Default unapproved (`approved=0`), promotion via `coordinator.procedural.approve()`, and deletion via `coordinator.procedural.delete()`.
     - Output Fencing: `coordinator.search()` returns text prefixed with `MEMORY_OUTPUT_FENCE_PREFIX` and passive summaries for unapproved procedures.
     - Integrity Check: `PRAGMA integrity_check;`, `PRAGMA quick_check;`, and `PRAGMA foreign_key_check;`.

3. **Scheduler Claim Concurrency & Enums**:
   - Observation: `RunState` has `SUCCESS = "success"`, not `COMPLETED`. `complete_run` asserts valid `RunState`.
   - Deduction: All run completions must pass `final_state=RunState.SUCCESS`.
   - Observation: `claim_next_due_job` throttles claims if `total_running >= max_workspace_runs` (default 1) or `max_installation_runs` (default 2).
   - Deduction: To test concurrent claims across workers for 10 jobs, the test must specify `max_workspace_runs=10` and `max_installation_runs=10` and use `asyncio.gather` across multiple worker identifiers (`worker-soak-alpha`, `worker-soak-beta`, etc.).
   - Deduction: Verify no double claims occur (all returned `job.id` and `run.id` values are pairwise unique).

4. **Idempotency & Leases**:
   - Observation: `scheduled_jobs.idempotency_key` is UNIQUE and checked in `create_job()`.
   - Deduction: Re-submitting a job with an identical `idempotency_key` must return the existing job instance without duplicating records.
   - Observation: `SchedulerDatabaseManager` provides `refresh_lease()`, `recover_expired_leases()`, and `confirm_run_quiescence()`.
   - Deduction:
     - Verify active worker heartbeat extends lease (`refresh_lease` returns `True`).
     - Verify rogue/stale worker heartbeat fails (`refresh_lease` returns `False`).
     - Verify abandoned lease past `lease_expires_at_utc` is detected by `recover_expired_leases()`, marked `stopping`, and the job paused.

5. **Async Teardown Safety**:
   - Observation: GEMINI.md Rule 4 mandates async yield fixtures for database managers to avoid hung `aiosqlite` threads on Windows.
   - Deduction: Refactor both tests to accept async fixtures (`soak_memory_db`, `soak_scheduler_db`) that yield the manager and await `close()` in teardown.

---

## 3. Caveats

- **No Schema Changes Permitted**: The underlying database schemas (`services/core/src/friday/storage/db.py` and `services/core/src/friday/scheduler/db.py`) are fully validated and stable across the 198+ regression test suite. All changes must be strictly within `tests/soak/test_soak_endurance.py`.
- **Soft Deletion Semantics**:
  - In `scheduled_jobs`, deletion is soft via tombstoning (`deleted_at_utc` set, state transitioned to `cancelled`).
  - In memory stores (`semantic_memory`, `procedural_memory`, `messages`), deletion removes rows from the base table and fires SQLite triggers (`semantic_memory_ad`, etc.) to delete tokens from FTS5 index tables, preserving database integrity without orphan virtual rows.
- **Other File Failures**: `test_50_turn_agent_loop_with_cancellations` (`InferenceEventType.ASSISTANT_DELTA` mismatch) and `test_high_risk_auto_denial_in_soak_mode` (`compute_canonical_args_hash` mismatch) were identified and noted for Explorer 1 / implementer, but are outside this report's primary focus.

---

## 4. Conclusion & Proposed Implementation

### 4.1 Required Changes in `tests/soak/test_soak_endurance.py`

#### Change 1: Add Imports and Async DB Fixtures
```python
from friday.memory.coordinator import MEMORY_OUTPUT_FENCE_PREFIX
from friday.memory.procedural import ProceduralMemoryEntry

@pytest.fixture
async def soak_memory_db(tmp_path: Path):
    db_path = str(tmp_path / "soak_memory.db")
    db_mgr = DatabaseManager(db_path)
    await db_mgr.initialize()
    yield db_mgr, db_path
    await db_mgr.close()

@pytest.fixture
async def soak_scheduler_db(tmp_path: Path):
    db_path = tmp_path / "soak_scheduler.db"
    sched_db = SchedulerDatabaseManager(db_path)
    await sched_db.initialize()
    yield sched_db, db_path
    await sched_db.close()
```

#### Change 2: Concrete Replacement for `test_memory_churn_and_fts5_integrity`
```python
@pytest.mark.soak
@pytest.mark.asyncio
async def test_memory_churn_and_fts5_integrity(soak_memory_db, tmp_path: Path):
    """Requirement R1: 4-tier memory churn (Working, Episodic, Semantic, Procedural) with FTS5 search, soft deletion, and PRAGMA integrity."""
    db_mgr, db_path = soak_memory_db
    coordinator = MemoryCoordinator(db_mgr)
    workspace = str(tmp_path)

    # 0. Setup valid session in DB to satisfy foreign key constraints
    conn = await db_mgr.get_connection()
    session_id = "soak-mem-session"
    await conn.execute(
        """
        INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile)
        VALUES (?, 'Soak Memory Test Session', unixepoch(), unixepoch(), ?, 'default')
        """,
        (session_id, workspace),
    )
    await conn.commit()

    # ---------------------------------------------------------
    # Tier 1: Working Memory Churn (In-Memory Ephemeral Scratchpad)
    # ---------------------------------------------------------
    for i in range(1, 51):
        coordinator.working.add_note(f"Ephemeral scratchpad note {i} for active turn.")
    notes = coordinator.working.get_notes()
    assert len(notes) == 50
    summary = coordinator.working.format_summary(max_chars=200)
    assert "[Working notes truncated]" in summary
    coordinator.working.clear()
    assert len(coordinator.working.get_notes()) == 0

    # ---------------------------------------------------------
    # Tier 2: Episodic Memory Churn (Sessions + Messages + FTS5 messages_fts)
    # ---------------------------------------------------------
    msg_ids = []
    for i in range(1, 51):
        msg_id = f"msg-soak-{i}"
        msg_ids.append(msg_id)
        role = "user" if i % 2 == 1 else "assistant"
        content = f"Episodic turn {i}: Reviewing RTX 5090 Blackwell sm_120 deployment invariants and endurance specs."
        await conn.execute(
            """
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, unixepoch() + ?)
            """,
            (msg_id, session_id, role, content, i),
        )
    await conn.commit()

    # Query Episodic via Coordinator & direct EpisodicMemory
    ep_results = await coordinator.episodic.search("Blackwell", workspace_root=workspace, limit=10)
    assert len(ep_results) > 0
    assert any("Blackwell" in r["content"] for r in ep_results)

    # Deletion churn in Episodic: delete 25 messages, triggers messages_ad
    for mid in msg_ids[:25]:
        await conn.execute("DELETE FROM messages WHERE id = ?", (mid,))
    await conn.commit()

    # ---------------------------------------------------------
    # Tier 3: Semantic Memory Churn (Persistent Facts + FTS5 semantic_memory_fts)
    # ---------------------------------------------------------
    saved_sem_ids = []
    for i in range(1, 51):
        entry = SemanticMemoryEntry(
            workspace_root=workspace,
            category="architecture" if i % 2 == 0 else "convention",
            title=f"Rule_{i}",
            content=f"Critical project invariant {i}: Always enforce canonical path verification on drive G.",
            source_session_id=session_id,  # Valid FK reference
        )
        mem_id = await coordinator.semantic.save(entry)
        saved_sem_ids.append(mem_id)

    # Update churn: update 10 entries to trigger semantic_memory_au
    for mid in saved_sem_ids[:10]:
        updated_entry = SemanticMemoryEntry(
            id=mid,
            workspace_root=workspace,
            category="architecture",
            title=f"Rule_Updated_{mid[:8]}",
            content=f"Updated invariant {mid}: Canonical NTFS path validation is strictly mandatory.",
            source_session_id=session_id,
        )
        await coordinator.semantic.save(updated_entry)

    # Delete churn in Semantic: delete 25 entries via coordinator.semantic.delete (triggers semantic_memory_ad)
    for mid in saved_sem_ids[25:]:
        del_ok = await coordinator.semantic.delete(mid, workspace_root=workspace)
        assert del_ok is True
        assert await coordinator.semantic.get(mid, workspace_root=workspace) is None

    # ---------------------------------------------------------
    # Tier 4: Procedural Memory Churn (Playbooks + FTS5 procedural_memory_fts)
    # ---------------------------------------------------------
    saved_proc_ids = []
    for i in range(1, 21):
        proc_entry = ProceduralMemoryEntry(
            workspace_root=workspace,
            title=f"Procedure_{i}",
            steps=f"Step 1: Inspect process. Step 2: Run verification cycle {i}.",
            source="soak_harness",
            approved=0,
            source_session_id=session_id,
        )
        pid = await coordinator.procedural.save(proc_entry, is_system_authorized=False)
        saved_proc_ids.append(pid)

    # Verify unapproved status default
    proc_sample = await coordinator.procedural.get(saved_proc_ids[0], workspace_root=workspace)
    assert proc_sample is not None and proc_sample.approved == 0

    # Promote 10 procedures to approved
    for pid in saved_proc_ids[:10]:
        app_ok = await coordinator.procedural.approve(pid, workspace_root=workspace)
        assert app_ok is True

    # Delete churn in Procedural: delete 5 procedures
    for pid in saved_proc_ids[15:]:
        del_proc_ok = await coordinator.procedural.delete(pid, workspace_root=workspace)
        assert del_proc_ok is True

    # ---------------------------------------------------------
    # Multi-Tier Unified FTS5 Search & Output Fencing
    # ---------------------------------------------------------
    search_results = await coordinator.search(
        query="verification",
        workspace_root=workspace,
        tiers=["episodic", "semantic", "procedural"],
        limit_per_tier=5,
    )
    # Must enforce MEMORY_OUTPUT_FENCE_PREFIX
    assert search_results.startswith(MEMORY_OUTPUT_FENCE_PREFIX), "Memory search results must start with security fence prefix"
    # Unapproved procedures must omit executable steps
    assert "[HISTORICAL RECORD]" in search_results
    assert "[Unapproved procedure - executable steps omitted to prevent unauthorized replay]" in search_results
    # Approved procedures must include steps
    assert "[APPROVED PROCEDURE]" in search_results

    # ---------------------------------------------------------
    # Database Integrity & Foreign Key Checks
    # ---------------------------------------------------------
    async with aiosqlite.connect(db_path) as verify_conn:
        cursor = await verify_conn.execute("PRAGMA integrity_check;")
        row = await cursor.fetchone()
        assert row is not None and row[0] == "ok", f"Integrity check failed: {row}"

        cursor = await verify_conn.execute("PRAGMA quick_check;")
        row = await cursor.fetchone()
        assert row is not None and row[0] == "ok", f"Quick check failed: {row}"

        cursor = await verify_conn.execute("PRAGMA foreign_key_check;")
        fk_violations = await cursor.fetchall()
        assert len(fk_violations) == 0, f"Foreign key violations found: {fk_violations}"
```

#### Change 3: Concrete Replacement for `test_concurrent_scheduler_soak_and_frozen_snapshot`
```python
@pytest.mark.soak
@pytest.mark.asyncio
async def test_concurrent_scheduler_soak_and_frozen_snapshot(soak_scheduler_db, tmp_path: Path):
    """Requirement R1: Concurrent scheduler claims, leases, timeouts, duplicate suppression, and frozen snapshots."""
    sched_db, db_path = soak_scheduler_db
    now_utc = int(time.time())

    # 1. Create 10 scheduled jobs with frozen permission snapshots
    job_ids = []
    for i in range(1, 11):
        snap = JobPermissionSnapshot(
            source_session_id=f"soak-source-sess-{i}",
            workspace_root=str(tmp_path),
            allowed_tool_ids=["filesystem.read", "git.status"],
            max_risk_level=0,
            tokens_per_run=1000,
            tool_calls_per_run=5,
            duration_seconds_per_run=60,
        )
        job = ScheduledJob(
            id=f"job-soak-{i}",
            session_id=f"sess-soak-{i}",
            workspace_root=str(tmp_path),
            title=f"Recurring Soak Job {i}",
            prompt=f"Execute system inspection {i}",
            schedule_type=ScheduleType.CRON,
            cron_expression="* * * * *",
            next_run_at_utc=now_utc - 10,
            permission_snapshot=snap,
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            idempotency_key=f"idem-soak-{i}",
        )
        created = await sched_db.create_job(job)
        job_ids.append(created.id)

    # 2. Duplicate suppression verification: re-creating job with identical idempotency_key returns existing job
    dup_job = ScheduledJob(
        id="job-soak-duplicate-attempt",
        session_id="sess-soak-dup",
        workspace_root=str(tmp_path),
        title="Duplicate Job Attempt",
        prompt="Duplicate prompt",
        schedule_type=ScheduleType.CRON,
        cron_expression="* * * * *",
        next_run_at_utc=now_utc - 10,
        permission_snapshot=snap,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
        idempotency_key="idem-soak-1",  # Same idempotency key as job-soak-1
    )
    existing_job = await sched_db.create_job(dup_job)
    assert existing_job.id == "job-soak-1", "Duplicate idempotency key must return original job"

    # 3. Concurrent claims across multiple simulated worker instances
    workers = ["worker-soak-alpha", "worker-soak-beta", "worker-soak-gamma", "worker-soak-delta"]
    async def worker_claim(worker_id: str):
        return await sched_db.claim_next_due_job(
            now_utc=now_utc,
            owner_instance=worker_id,
            ownership_generation=1,
            lease_duration_seconds=30,
            max_workspace_runs=10,       # Allow up to 10 concurrent runs in test workspace
            max_installation_runs=10,    # Allow up to 10 concurrent runs across installation
        )

    # Launch concurrent claim attempts
    claim_tasks = [worker_claim(workers[i % len(workers)]) for i in range(10)]
    claim_results = await asyncio.gather(*claim_tasks)
    admitted_claims = [c for c in claim_results if c is not None]
    assert len(admitted_claims) > 0, "At least one job must be atomically claimed"

    # Verify no double claims: all admitted run IDs and job IDs must be unique
    claimed_job_ids = [c[0].id for c in admitted_claims]
    claimed_run_ids = [c[1].id for c in admitted_claims]
    assert len(claimed_job_ids) == len(set(claimed_job_ids)), "Concurrent claims must not double-claim the same job"
    assert len(claimed_run_ids) == len(set(claimed_run_ids)), "Every claim must generate a unique run ID"

    # 4. Lease heartbeat & stale owner rejection
    first_job, first_run = admitted_claims[0]
    # Legitimate owner heartbeat succeeds
    refreshed = await sched_db.refresh_lease(
        run_id=first_run.id,
        owner_instance=first_run.owner_instance,
        ownership_generation=1,
        extend_seconds=60,
    )
    assert refreshed is True, "Heartbeat extension by owner must succeed"

    # Rogue / stale owner heartbeat fails
    stale_refreshed = await sched_db.refresh_lease(
        run_id=first_run.id,
        owner_instance="rogue-worker",
        ownership_generation=1,
        extend_seconds=60,
    )
    assert stale_refreshed is False, "Heartbeat extension by non-owner must fail"

    # 5. Expired lease timeout & recovery
    # Simulate an abandoned job by claiming with a past timestamp and short lease
    abandoned_claim = await sched_db.claim_next_due_job(
        now_utc=now_utc - 100,
        owner_instance="worker-abandoned",
        ownership_generation=1,
        lease_duration_seconds=5,
        max_workspace_runs=10,
        max_installation_runs=10,
    )
    if abandoned_claim:
        abandoned_job, abandoned_run = abandoned_claim
        # Recover expired leases at current time now_utc
        recovered_ids = await sched_db.recover_expired_leases(now_utc=now_utc)
        assert abandoned_run.id in recovered_ids, "Expired lease must be detected and recovered"
        await sched_db.confirm_run_quiescence(abandoned_run.id)

    # 6. Complete claimed runs using RunState.SUCCESS
    for job_record, run_record in admitted_claims:
        ok = await sched_db.complete_run(
            run_id=run_record.id,
            owner_instance=run_record.owner_instance,
            ownership_generation=1,
            final_state=RunState.SUCCESS,  # Correct RunState enum!
            consumed_tokens=25,
            output_summary="Completed successfully with network disabled.",
            next_run_at_utc=now_utc + 60,
        )
        assert ok is True, f"Run {run_record.id} completion should succeed"

    # 7. WAL file size check: strictly under 64 MB
    wal_file = Path(f"{db_path}-wal")
    if wal_file.exists():
        wal_size_mb = wal_file.stat().st_size / (1024 * 1024)
        assert wal_size_mb < 64.0, f"WAL size {wal_size_mb:.2f} MB exceeds 64 MB threshold"

    # 8. Verify frozen snapshot guard prohibits forbidden tools & privilege escalations
    guard = ScheduledExecutionGuard(admitted_claims[0][0].permission_snapshot)
    # Permitted tool passes
    guard.check_tool_invocation("filesystem.read", {"path": str(tmp_path / "safe.txt")})

    # Forbidden anti-recursion prefixes raise SchedPolicyDeniedError
    for forbidden in ["schedule.create", "subagent.invoke", "policy.update", "system.shutdown"]:
        with pytest.raises(SchedPolicyDeniedError):
            guard.check_tool_invocation(forbidden, {})

    # Tool not in allowed_tool_ids raises SchedPolicyDeniedError
    with pytest.raises(SchedPolicyDeniedError):
        guard.check_tool_invocation("terminal.exec", {})

    # Tool with Risk >= 2 raises SchedPolicyDeniedError
    with pytest.raises(SchedPolicyDeniedError):
        guard.check_tool_invocation("filesystem.read", {}, tool_risk_level=2)
```

---

## 5. Verification Method

To independently verify these strategies:

1. **Verify Database Models & Enums**:
   - Inspect `RunState` definition:
     `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\scheduler\models.py" StartLine=37 EndLine=50`
   - Inspect `ScheduledJob` and `idempotency_key` handling:
     `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\scheduler\db.py" StartLine=205 EndLine=220`
   - Inspect `claim_next_due_job` and concurrency bounds:
     `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\scheduler\db.py" StartLine=500 EndLine=520`

2. **Verify Memory Models & Triggers**:
   - Inspect foreign key and table definitions in `db.py`:
     `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\storage\db.py" StartLine=75 EndLine=142`
   - Inspect `MEMORY_OUTPUT_FENCE_PREFIX`:
     `view_file AbsolutePath="G:\Project_Ned\services\core\src\friday\memory\coordinator.py" StartLine=14 EndLine=21`

3. **Targeted Pytest Execution**:
   After applying the fix to `tests/soak/test_soak_endurance.py`, run:
   ```cmd
   cmd.exe /c ".\.venv\Scripts\pytest.exe tests/soak/test_soak_endurance.py -k "test_memory_churn or test_concurrent_scheduler" -v > soak_verify.txt 2>&1"
   ```
   Inspect `soak_verify.txt` to confirm both tests pass in < 2 seconds with zero errors and no unclosed database warnings, then delete `soak_verify.txt`.

4. **Invalidation Conditions**:
   - If `test_memory_churn_and_fts5_integrity` fails with `FOREIGN KEY constraint failed`, verify that `INSERT INTO sessions` executed prior to any message or semantic memory save.
   - If `test_concurrent_scheduler_soak_and_frozen_snapshot` fails with `AttributeError`, verify that `RunState.SUCCESS` (not `.COMPLETED`) is used.
   - If any `pytest` worker process hangs, verify that `soak_memory_db` and `soak_scheduler_db` fixtures properly execute `await db.close()`.
