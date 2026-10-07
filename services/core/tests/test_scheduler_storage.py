"""Milestone 2 tests: Scheduler database CRUD, atomic claiming, leases, quotas, recovery, and backup."""

import time
import uuid
from pathlib import Path
import pytest

from friday.scheduler.db import SchedulerDatabaseManager
from friday.scheduler.models import (
    JobPermissionSnapshot,
    JobRun,
    RunState,
    ScheduledJob,
    ScheduleState,
    ScheduleType,
)


@pytest.fixture
async def scheduler_db(tmp_path):
    db_path = tmp_path / "scheduler.db"
    mgr = SchedulerDatabaseManager(db_path)
    await mgr.initialize()
    yield mgr
    await mgr.close()


def make_test_job(
    job_id: str,
    workspace_root: str = "G:/test_ws",
    due_at: int = 1000,
    sched_type: ScheduleType = ScheduleType.ONCE,
    idempotency_key: str | None = None,
) -> ScheduledJob:
    snap = JobPermissionSnapshot(
        source_session_id="sess-test",
        workspace_root=workspace_root,
        allowed_tool_ids=["filesystem.read"],
        max_risk_level=0,
    )
    return ScheduledJob(
        id=job_id,
        session_id="sess-test",
        workspace_root=workspace_root,
        title=f"Test Job {job_id}",
        prompt="Inspect repo",
        schedule_type=sched_type,
        next_run_at_utc=due_at,
        permission_snapshot=snap,
        created_at_utc=1000,
        updated_at_utc=1000,
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_job_crud_and_idempotency(scheduler_db):
    """Verify job creation, retrieval, and idempotency key deduplication."""
    job1 = make_test_job("job-1", idempotency_key="idem-key-1")
    created = await scheduler_db.create_job(job1)
    assert created.id == "job-1"

    # Fetch
    fetched = await scheduler_db.get_job("job-1")
    assert fetched is not None
    assert fetched.title == "Test Job job-1"
    assert fetched.state == ScheduleState.ACTIVE

    # Idempotent re-creation
    job1_dup = make_test_job("job-1-dup", idempotency_key="idem-key-1")
    dup_res = await scheduler_db.create_job(job1_dup)
    assert dup_res.id == "job-1"  # Returns existing job without duplicate insertion

    # Pause and resume
    await scheduler_db.pause_job("job-1", reason="Maintenance", actor="admin")
    paused = await scheduler_db.get_job("job-1")
    assert paused.state == ScheduleState.PAUSED
    assert paused.pause_reason == "Maintenance"

    await scheduler_db.resume_job("job-1", next_run_at_utc=2000, actor="desktop_user")
    resumed = await scheduler_db.get_job("job-1")
    assert resumed.state == ScheduleState.ACTIVE
    assert resumed.next_run_at_utc == 2000

    # Cancel
    await scheduler_db.cancel_job("job-1")
    cancelled = await scheduler_db.get_job("job-1")
    assert cancelled.state == ScheduleState.CANCELLED


@pytest.mark.asyncio
async def test_atomic_claiming_concurrency_and_quotas(scheduler_db):
    """Verify atomic claiming, occurrence uniqueness, and concurrency limits."""
    # Create two jobs in the same workspace
    job1 = make_test_job("job-1", workspace_root="G:/ws_alpha", due_at=1000)
    job2 = make_test_job("job-2", workspace_root="G:/ws_alpha", due_at=1000)
    await scheduler_db.create_job(job1)
    await scheduler_db.create_job(job2)

    # 1. Claim first job at t=1050
    claim1 = await scheduler_db.claim_next_due_job(
        now_utc=1050,
        owner_instance="worker-1",
        max_workspace_runs=1,
    )
    assert claim1 is not None
    claimed_job1, run1 = claim1
    assert claimed_job1.id == "job-1"
    assert run1.state == RunState.RUNNING
    assert run1.scheduled_for_utc == 1000
    assert run1.reserved_tokens == 8000

    # 2. Try to claim second job in SAME workspace (max_workspace_runs = 1)
    claim2 = await scheduler_db.claim_next_due_job(
        now_utc=1050,
        owner_instance="worker-2",
        max_workspace_runs=1,
    )
    # Must be blocked by workspace concurrency limit
    assert claim2 is None

    # 3. Complete run1
    ok = await scheduler_db.complete_run(
        run_id=run1.id,
        owner_instance="worker-1",
        ownership_generation=1,
        final_state=RunState.SUCCESS,
        consumed_tokens=3500,
    )
    assert ok is True

    # 4. Now second job in workspace can be claimed
    claim3 = await scheduler_db.claim_next_due_job(
        now_utc=1050,
        owner_instance="worker-1",
        max_workspace_runs=1,
    )
    assert claim3 is not None
    claimed_job2, run2 = claim3
    assert claimed_job2.id == "job-2"


@pytest.mark.asyncio
async def test_lease_heartbeat_and_stale_owner_protection(scheduler_db):
    """Verify lease refresh and rejection of stale ownership generations."""
    job = make_test_job("job-lease", due_at=1000)
    await scheduler_db.create_job(job)

    claim = await scheduler_db.claim_next_due_job(now_utc=1000, owner_instance="worker-1")
    assert claim is not None
    _, run = claim

    # Legitimate owner extends lease
    refreshed = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-1",
        ownership_generation=1,
        extend_seconds=60,
    )
    assert refreshed is True

    # Stale owner instance rejected
    stale_owner = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-stale",
        ownership_generation=1,
    )
    assert stale_owner is False

    # Stale generation rejected
    stale_gen = await scheduler_db.refresh_lease(
        run_id=run.id,
        owner_instance="worker-1",
        ownership_generation=2,
    )
    assert stale_gen is False


@pytest.mark.asyncio
async def test_lease_expiry_recovery_and_quiescence(scheduler_db):
    """Verify lease recovery pauses schedule and marks outcome uncertain until quiescence."""
    job = make_test_job("job-recover", due_at=1000)
    await scheduler_db.create_job(job)

    claim = await scheduler_db.claim_next_due_job(
        now_utc=1000,
        owner_instance="worker-1",
        lease_duration_seconds=30,  # Expires at t=1030
    )
    assert claim is not None
    _, run = claim

    # Time advances to t=1050 (lease expired at 1030)
    expired_runs = await scheduler_db.recover_expired_leases(now_utc=1050)
    assert run.id in expired_runs

    # Run moved to 'stopping' with outcome_certain = 0
    updated_run = await scheduler_db.get_run(run.id)
    assert updated_run.state == RunState.STOPPING
    assert updated_run.outcome_certain is False
    assert updated_run.quiescence_confirmed is False

    # Job is paused
    updated_job = await scheduler_db.get_job("job-recover")
    assert updated_job.state == ScheduleState.PAUSED
    assert "Lease expired" in updated_job.pause_reason

    # Worker quiescence is confirmed
    await scheduler_db.confirm_run_quiescence(run.id)
    finalized_run = await scheduler_db.get_run(run.id)
    assert finalized_run.state == RunState.INTERRUPTED
    assert finalized_run.quiescence_confirmed is True


@pytest.mark.asyncio
async def test_database_online_backup_and_retention_purge(scheduler_db, tmp_path):
    """Verify online backup generation and history retention purge."""
    job = make_test_job("job-backup", due_at=1000)
    await scheduler_db.create_job(job)

    backup_file = tmp_path / "backup" / "scheduler_backup.db"
    await scheduler_db.backup_database(backup_file)
    assert backup_file.exists()

    # Verify backup is valid SQLite database
    backup_mgr = SchedulerDatabaseManager(backup_file)
    await backup_mgr.initialize()
    backed_up_job = await backup_mgr.get_job("job-backup")
    assert backed_up_job is not None
    assert backed_up_job.id == "job-backup"
    await backup_mgr.close()

    # Delete job (soft tombstone)
    await scheduler_db.delete_job("job-backup")

    # Purge with future cutoff
    purged = await scheduler_db.purge_retained_history(now_utc=int(time.time()) + 100000, retention_days=0)
    assert purged >= 1

    # Job record purged
    purged_job = await scheduler_db.get_job("job-backup")
    assert purged_job is None
