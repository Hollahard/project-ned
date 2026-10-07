"""Tests for ScheduledExecutionGuard and SchedulerWorker (Phase 11 Milestone 4).

Verifies:
1. Frozen permission enforcement at dispatch (tool allowlist, risk caps, path containment, recursion denial).
2. Zero background approval prompts: attempt to invoke Risk 2 or unpermitted tools halts turn.
3. Resource caps: tool call and token budget limits.
4. Watchdog hard timeout triggers safe termination.
5. Autonomous claim, execution, heartbeat, and finalization.
6. Automatic job pausing upon failure or policy denial.
7. Overdue jobs skipped past admission grace window without execution.
"""

import asyncio
from pathlib import Path
import time
import pytest
import pytest_asyncio

from friday.scheduler.db import SchedulerDatabaseManager
from friday.scheduler.models import (
    JobPermissionSnapshot,
    PolicyDeniedError,
    RunState,
    ScheduleState,
    ScheduleType,
    ScheduledJob,
)
from friday.scheduler.worker import (
    ScheduledExecutionGuard,
    ScheduledTurnResult,
    SchedulerWorker,
)


@pytest.fixture
def sample_snapshot(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return JobPermissionSnapshot(
        source_session_id="sess-test",
        workspace_root=str(ws),
        allowed_tool_ids=["filesystem.read", "filesystem.write"],
        max_risk_level=1,
        tokens_per_run=1000,
        tool_calls_per_run=5,
        duration_seconds_per_run=2,
    )


def test_execution_guard_anti_recursion(sample_snapshot):
    """Anti-recursion: forbidden prefixes (schedule.*, subagent.*, policy.*, system.shutdown) are denied."""
    guard = ScheduledExecutionGuard(sample_snapshot)
    for forbidden in ["schedule.create", "schedule.list", "subagent.invoke", "policy.update", "system.shutdown"]:
        with pytest.raises(PolicyDeniedError, match="anti-recursion rule"):
            guard.check_tool_invocation(forbidden, {})


def test_execution_guard_allowlist(sample_snapshot):
    """Tools not in frozen allowlist are strictly rejected."""
    guard = ScheduledExecutionGuard(sample_snapshot)
    with pytest.raises(PolicyDeniedError, match="not in frozen allowed tool IDs"):
        guard.check_tool_invocation("unauthorized.tool", {})

    # Allowed tools pass
    guard.check_tool_invocation("filesystem.read", {})


def test_execution_guard_risk_levels(sample_snapshot):
    """Risk 2 is strictly forbidden, and risk > max_risk_level is rejected."""
    guard = ScheduledExecutionGuard(sample_snapshot)
    # Risk 2 tool
    with pytest.raises(PolicyDeniedError, match="Risk 2 prohibited"):
        guard.check_tool_invocation("filesystem.read", {}, tool_risk_level=2)

    # Risk exceeding max_risk_level (e.g. if snapshot max_risk_level is 0)
    strict_snapshot = sample_snapshot.model_copy(update={"max_risk_level": 0})
    strict_guard = ScheduledExecutionGuard(strict_snapshot)
    with pytest.raises(PolicyDeniedError, match="exceeds snapshot max risk level"):
        strict_guard.check_tool_invocation("filesystem.write", {}, tool_risk_level=1)


def test_execution_guard_path_containment(sample_snapshot, tmp_path):
    """Path arguments outside workspace root are rejected."""
    guard = ScheduledExecutionGuard(sample_snapshot)
    inside_file = Path(sample_snapshot.workspace_root) / "notes.txt"
    outside_file = tmp_path / "outside.txt"

    # Inside passes
    guard.check_tool_invocation("filesystem.write", {"path": str(inside_file)}, tool_risk_level=1)

    # Outside fails
    with pytest.raises(PolicyDeniedError, match="outside authorized workspace root"):
        guard.check_tool_invocation("filesystem.write", {"path": str(outside_file)}, tool_risk_level=1)


def test_execution_guard_resource_caps(sample_snapshot):
    """Exceeding tool calls or token budget raises PolicyDeniedError."""
    guard = ScheduledExecutionGuard(sample_snapshot)
    # Tool call cap = 5
    for _ in range(5):
        guard.check_tool_invocation("filesystem.read", {})
    with pytest.raises(PolicyDeniedError, match="Tool call limit exceeded"):
        guard.check_tool_invocation("filesystem.read", {})

    # Token budget cap = 1000
    guard.record_tokens(500)
    guard.record_tokens(500)
    with pytest.raises(PolicyDeniedError, match="Token budget exceeded"):
        guard.record_tokens(1)


@pytest_asyncio.fixture
async def scheduler_db(tmp_path):
    db_file = tmp_path / "scheduler_worker.db"
    mgr = SchedulerDatabaseManager(db_file)
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.mark.asyncio
async def test_worker_successful_turn_execution(scheduler_db, sample_snapshot):
    """Worker claims job, runs execution, updates counters, and completes run."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-exec-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Exec Test",
        prompt="Perform check",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 5,  # Due now
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    async def mock_runner(j, r, guard, cancel):
        guard.check_tool_invocation("filesystem.read", {})
        guard.record_tokens(250)
        return ScheduledTurnResult(
            success=True,
            final_state=RunState.SUCCESS,
            consumed_tokens=250,
            output_summary="Everything checked successfully",
        )

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-test-1",
        poll_interval_seconds=0.1,
        turn_runner=mock_runner,
    )

    await worker.start()
    # Allow worker to claim and execute
    await asyncio.sleep(0.5)
    await worker.stop()

    runs = await scheduler_db.list_runs(job_id="job-exec-1")
    assert len(runs) == 1
    assert runs[0].state == RunState.SUCCESS
    assert runs[0].consumed_tokens == 250
    assert "Everything checked" in (runs[0].output_summary or "")

    # One-shot job is completed
    finished_job = await scheduler_db.get_job("job-exec-1")
    assert finished_job.state == ScheduleState.COMPLETED
    assert finished_job.run_count == 1


@pytest.mark.asyncio
async def test_worker_watchdog_timeout(scheduler_db, sample_snapshot):
    """Watchdog timer terminates runaway turn and records TIMEOUT."""
    # Configure 1-second timeout
    timed_snapshot = sample_snapshot.model_copy(update={"duration_seconds_per_run": 1})
    now = int(time.time())
    job = ScheduledJob(
        id="job-timeout-1",
        session_id="sess-1",
        workspace_root=timed_snapshot.workspace_root,
        title="Timeout Test",
        prompt="Hang forever",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 2,
        state=ScheduleState.ACTIVE,
        permission_snapshot=timed_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    async def hanging_runner(j, r, guard, cancel):
        await asyncio.sleep(10)  # Exceeds 1s timeout
        return ScheduledTurnResult(success=True, final_state=RunState.SUCCESS)

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-test-to",
        poll_interval_seconds=0.1,
        turn_runner=hanging_runner,
    )

    await worker.start()
    await asyncio.sleep(1.8)
    await worker.stop()

    runs = await scheduler_db.list_runs(job_id="job-timeout-1")
    assert len(runs) == 1
    assert runs[0].state == RunState.TIMEOUT
    assert "hard timeout limit" in (runs[0].error_summary or "")

    # Job is paused for human review
    updated_job = await scheduler_db.get_job("job-timeout-1")
    assert updated_job.state == ScheduleState.PAUSED


@pytest.mark.asyncio
async def test_worker_policy_denial_pauses_job(scheduler_db, sample_snapshot):
    """Policy denied tool call terminates run with DENIED and pauses schedule."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-denied-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Denied Test",
        prompt="Spawn subagent",
        schedule_type=ScheduleType.CRON,
        cron_expression="*/10 * * * *",
        next_run_at_utc=now - 2,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    async def denied_runner(j, r, guard, cancel):
        # Attempt forbidden recursion tool
        guard.check_tool_invocation("subagent.invoke", {})

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-test-denied",
        poll_interval_seconds=0.1,
        turn_runner=denied_runner,
    )

    await worker.start()
    await asyncio.sleep(0.5)
    await worker.stop()

    runs = await scheduler_db.list_runs(job_id="job-denied-1")
    assert len(runs) == 1
    assert runs[0].state == RunState.DENIED
    assert "anti-recursion" in (runs[0].error_summary or "")

    # Job must be paused so human can review
    paused_job = await scheduler_db.get_job("job-denied-1")
    assert paused_job.state == ScheduleState.PAUSED


@pytest.mark.asyncio
async def test_worker_skips_overdue_jobs(scheduler_db, sample_snapshot):
    """Overdue jobs past 60s admission grace are skipped with zero backlog replay."""
    now = int(time.time())
    # Scheduled 300 seconds ago (grace window of 60s is long gone)
    overdue_time = now - 300
    job = ScheduledJob(
        id="job-overdue-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Overdue Test",
        prompt="Catch up test",
        schedule_type=ScheduleType.CRON,
        cron_expression="*/15 * * * *",
        next_run_at_utc=overdue_time,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now - 1000,
        updated_at_utc=now - 1000,
    )
    await scheduler_db.create_job(job)

    runner_called = False

    async def tracking_runner(j, r, guard, cancel):
        nonlocal runner_called
        runner_called = True

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-test-overdue",
        poll_interval_seconds=0.1,
        turn_runner=tracking_runner,
    )

    await worker.start()
    await asyncio.sleep(0.5)
    await worker.stop()

    # Runner was NOT executed!
    assert not runner_called

    # Skipped run record exists
    runs = await scheduler_db.list_runs(job_id="job-overdue-1")
    assert len(runs) == 1
    assert runs[0].state == RunState.SKIPPED
    assert runs[0].scheduled_for_utc == overdue_time

    # Job's next run advanced to future calendar occurrence (> now)
    updated_job = await scheduler_db.get_job("job-overdue-1")
    assert updated_job.next_run_at_utc is not None
    assert updated_job.next_run_at_utc > now
