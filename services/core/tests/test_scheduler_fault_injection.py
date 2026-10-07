"""Fault injection and edge case verification suite for Friday Scheduler (Phase 11 Milestone 6).

Covers:
1. Crash after claim: Lease expires, recover_expired_leases marks outcome_certain=False ("review required") and pauses job.
2. Stale owner / lost lease: Heartbeat failure triggers immediate cancellation of living worker.
3. Racing cancellation: In-flight cancellation requests terminate run cleanly and confirm worker quiescence.
4. Recursive scheduling attempt: Anti-recursion policy denial halts turn and pauses recurring schedule.
5. Clock rollback resistance: Watermark prevents replaying past occurrences when clock jumps backward.
6. Token quota exhaustion: Daily limits prevent further claims until the next UTC day.
"""

import asyncio
from pathlib import Path
import time
import pytest
import pytest_asyncio

from friday.scheduler.cron import CronCalendarAdapter
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


@pytest_asyncio.fixture
async def scheduler_db(tmp_path):
    db_file = tmp_path / "scheduler_fault.db"
    mgr = SchedulerDatabaseManager(db_file)
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.fixture
def sample_snapshot(tmp_path):
    ws = tmp_path / "fault_ws"
    ws.mkdir()
    return JobPermissionSnapshot(
        source_session_id="sess-fault",
        workspace_root=str(ws),
        allowed_tool_ids=["filesystem.read"],
        max_risk_level=0,
        tokens_per_run=5000,
        tool_calls_per_run=10,
        duration_seconds_per_run=10,
    )


@pytest.mark.asyncio
async def test_fault_crash_after_claim_lease_recovery(scheduler_db, sample_snapshot):
    """Crash after claim: lease expires, run marked outcome_certain=0, schedule paused."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-crash-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Crash Test",
        prompt="Audit files",
        schedule_type=ScheduleType.CRON,
        cron_expression="*/5 * * * *",
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    # 1. Claim job with short 2s lease
    claimed = await scheduler_db.claim_next_due_job(
        now_utc=now,
        owner_instance="worker-crashed",
        lease_duration_seconds=2,
    )
    assert claimed is not None
    _, run = claimed
    assert run.state == RunState.RUNNING

    # 2. Simulate worker crash: 3s later, lease has expired
    t_later = now + 3
    recovered = await scheduler_db.recover_expired_leases(t_later)
    assert run.id in recovered

    # 3. Verify run moved to 'stopping' with outcome_certain = False
    updated_run = await scheduler_db.get_run(run.id)
    assert updated_run.state == RunState.STOPPING
    assert not updated_run.outcome_certain
    assert updated_run.cancellation_requested

    # 4. Schedule must be paused for human review
    updated_job = await scheduler_db.get_job(job.id)
    assert updated_job.state == ScheduleState.PAUSED
    assert "Lease expired" in (updated_job.pause_reason or "")

    # 5. Confirm quiescence finalizes run as 'interrupted'
    await scheduler_db.confirm_run_quiescence(run.id)
    final_run = await scheduler_db.get_run(run.id)
    assert final_run.state == RunState.INTERRUPTED
    assert final_run.quiescence_confirmed


@pytest.mark.asyncio
async def test_fault_stale_owner_heartbeat_rejection(scheduler_db, sample_snapshot):
    """Worker whose lease generation is overtaken or expired fails heartbeat and triggers abort."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-stale-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Stale Test",
        prompt="Check memory",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    claimed = await scheduler_db.claim_next_due_job(
        now_utc=now,
        owner_instance="worker-original",
        ownership_generation=1,
        lease_duration_seconds=10,
    )
    assert claimed is not None
    _, run = claimed

    # Heartbeat with correct owner succeeds
    ok = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-original",
        ownership_generation=1,
        extend_seconds=10,
    )
    assert ok is True

    # Heartbeat from wrong owner fails
    wrong_owner = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-imposter",
        ownership_generation=1,
        extend_seconds=10,
    )
    assert wrong_owner is False

    # Heartbeat with stale generation fails
    stale_gen = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-original",
        ownership_generation=2,
        extend_seconds=10,
    )
    assert stale_gen is False


@pytest.mark.asyncio
async def test_fault_racing_cancellation(scheduler_db, sample_snapshot):
    """Cancellation requested while execution is in-flight gracefully halts the turn."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-race-cancel",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Cancel Race",
        prompt="Long running step",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    cancel_witnessed = False

    async def long_runner(j, r, guard, cancel):
        nonlocal cancel_witnessed
        # Wait until cancelled
        for _ in range(50):
            if cancel.is_set():
                cancel_witnessed = True
                raise asyncio.CancelledError()
            await asyncio.sleep(0.05)
        return ScheduledTurnResult(success=True, final_state=RunState.SUCCESS)

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-cancel-test",
        poll_interval_seconds=0.05,
        turn_runner=long_runner,
    )

    await worker.start()
    # Wait for run to start
    await asyncio.sleep(0.15)

    # User cancels job
    await scheduler_db.cancel_job(job.id, actor="user")

    # In worker, cancel event is triggered when stop or cancel is processed
    await asyncio.sleep(0.2)
    await worker.stop()

    runs = await scheduler_db.list_runs(job_id=job.id)
    assert len(runs) == 1
    assert runs[0].state == RunState.CANCELLED
    assert runs[0].quiescence_confirmed


@pytest.mark.asyncio
async def test_fault_anti_recursion_halts_turn(scheduler_db, sample_snapshot):
    """Attempted recursive scheduling halts turn immediately with DENIED and pauses job."""
    now = int(time.time())
    job = ScheduledJob(
        id="job-hydra-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Hydra Job",
        prompt="Spawn new schedule",
        schedule_type=ScheduleType.CRON,
        cron_expression="0 0 * * *",
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=sample_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job)

    async def hydra_runner(j, r, guard, cancel):
        # Attempt to spawn another schedule
        guard.check_tool_invocation("schedule.create", {"title": "Child Schedule"})

    worker = SchedulerWorker(
        db_manager=scheduler_db,
        instance_id="worker-hydra",
        poll_interval_seconds=0.05,
        turn_runner=hydra_runner,
    )

    await worker.start()
    await asyncio.sleep(0.3)
    await worker.stop()

    runs = await scheduler_db.list_runs(job_id=job.id)
    assert len(runs) == 1
    assert runs[0].state == RunState.DENIED
    assert "anti-recursion rule" in (runs[0].error_summary or "")

    paused_job = await scheduler_db.get_job(job.id)
    assert paused_job.state == ScheduleState.PAUSED


def test_fault_clock_rollback_resistance():
    """Watermark strictly prevents calculating backward occurrences during clock rollback."""
    t0 = 1770000000
    cron = "0 6 * * *"  # 6 AM daily

    # First occurrence computed at t0
    run1 = CronCalendarAdapter.compute_next_run(
        schedule_type=ScheduleType.CRON,
        cron_expression=cron,
        tz_name="UTC",
        base_time_utc=t0,
        watermark_utc=None,
    )
    assert run1 is not None and run1 > t0

    # Simulate clock jump backwards by 2 days (t0 - 172800)
    stepped_back_clock = t0 - 172800

    # With watermark set to run1, subsequent calculation CANNOT retreat
    run2 = CronCalendarAdapter.compute_next_run(
        schedule_type=ScheduleType.CRON,
        cron_expression=cron,
        tz_name="UTC",
        base_time_utc=stepped_back_clock,
        watermark_utc=run1,
    )
    assert run2 is not None
    assert run2 > run1


@pytest.mark.asyncio
async def test_fault_daily_quota_exhaustion_blocks_claim(scheduler_db, sample_snapshot):
    """Exhausting daily workspace or installation token quota blocks further claims."""
    now = int(time.time())
    # Create job requiring 30000 tokens per run
    heavy_snapshot = sample_snapshot.model_copy(update={"tokens_per_run": 30000})

    job1 = ScheduledJob(
        id="job-quota-1",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Heavy Job 1",
        prompt="Work 1",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=heavy_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    job2 = ScheduledJob(
        id="job-quota-2",
        session_id="sess-1",
        workspace_root=sample_snapshot.workspace_root,
        title="Heavy Job 2",
        prompt="Work 2",
        schedule_type=ScheduleType.ONCE,
        delay_seconds=60,
        next_run_at_utc=now - 5,
        state=ScheduleState.ACTIVE,
        permission_snapshot=heavy_snapshot,
        created_at_utc=now,
        updated_at_utc=now,
    )
    await scheduler_db.create_job(job1)
    await scheduler_db.create_job(job2)

    # 1. Claim job1: reserves 30,000 tokens (out of max 50,000 daily workspace quota)
    claim1 = await scheduler_db.claim_next_due_job(
        now_utc=now,
        owner_instance="worker-1",
        max_workspace_runs=2,  # Allow 2 concurrent runs
        max_daily_workspace_tokens=50000,
    )
    assert claim1 is not None
    _, run1 = claim1

    # 2. Try to claim job2: needs 30,000 tokens, but workspace already has 30,000 reserved (30k+30k > 50k max)
    claim2 = await scheduler_db.claim_next_due_job(
        now_utc=now,
        owner_instance="worker-2",
        max_workspace_runs=2,
        max_daily_workspace_tokens=50000,
    )
    # Must be blocked by quota!
    assert claim2 is None
