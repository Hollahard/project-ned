"""Milestone 1 contract tests: Pydantic models, snapshots, state transitions, and database pragmas."""

import json
import pytest
from pathlib import Path

from friday.scheduler.db import SchedulerDatabaseManager
from friday.scheduler.models import (
    JobPermissionSnapshot,
    RunState,
    ScheduleState,
    ScheduleType,
    VALID_RUN_TRANSITIONS,
    VALID_SCHEDULE_TRANSITIONS,
    compute_execution_specification_digest,
)


def test_permission_snapshot_risk_2_forbidden():
    """Verify that Risk 2 is strictly forbidden in scheduled job snapshots."""
    with pytest.raises(ValueError, match="Risk 2 .* is strictly forbidden"):
        JobPermissionSnapshot(
            source_session_id="sess-1",
            workspace_root="G:/test",
            max_risk_level=2,
        )

    with pytest.raises(ValueError, match="Risk 3 .* is strictly forbidden"):
        JobPermissionSnapshot(
            source_session_id="sess-1",
            workspace_root="G:/test",
            max_risk_level=3,
        )


def test_permission_snapshot_valid_risks():
    """Verify that Risk 0 (read-only) and Risk 1 (workspace write) are accepted."""
    snap0 = JobPermissionSnapshot(
        source_session_id="sess-1",
        workspace_root="G:/test",
        max_risk_level=0,
    )
    assert snap0.max_risk_level == 0

    snap1 = JobPermissionSnapshot(
        source_session_id="sess-1",
        workspace_root="G:/test",
        max_risk_level=1,
        approval_digest="abcdef123456",
    )
    assert snap1.max_risk_level == 1


def test_permission_snapshot_forbidden_tools_rejected():
    """Verify anti-recursion rule: scheduled turns cannot hold schedule.*, subagent.*, policy.* tools."""
    for bad_tool in ["schedule.create", "schedule.cancel", "subagent.spawn", "policy.evaluate"]:
        with pytest.raises(ValueError, match="cannot be granted in scheduled execution"):
            JobPermissionSnapshot(
                source_session_id="sess-1",
                workspace_root="G:/test",
                allowed_tool_ids=[bad_tool],
            )


def test_permission_snapshot_extra_keys_forbidden():
    """Verify that extra keys in permission snapshot fail closed."""
    raw = {
        "source_session_id": "sess-1",
        "workspace_root": "G:/test",
        "unauthorized_field": True,
    }
    with pytest.raises(ValueError):
        JobPermissionSnapshot.model_validate(raw)


def test_execution_specification_digest():
    """Verify deterministic digest calculation over execution specification."""
    digest1 = compute_execution_specification_digest(
        prompt="Scan workspace",
        title="Nightly Scan",
        schedule_type="cron",
        schedule_expr_or_delay="0 2 * * *",
        timezone_name="America/New_York",
        workspace_root="G:/Project_Ned",
        allowed_tool_ids=["filesystem.read", "git.status"],
        max_risk_level=0,
        tokens_per_run=8000,
        tool_calls_per_run=50,
        duration_seconds_per_run=300,
    )
    # Different order of allowed tools must produce identical digest
    digest2 = compute_execution_specification_digest(
        prompt="Scan workspace",
        title="Nightly Scan",
        schedule_type="cron",
        schedule_expr_or_delay="0 2 * * *",
        timezone_name="America/New_York",
        workspace_root="G:/Project_Ned",
        allowed_tool_ids=["git.status", "filesystem.read"],
        max_risk_level=0,
        tokens_per_run=8000,
        tool_calls_per_run=50,
        duration_seconds_per_run=300,
    )
    assert digest1 == digest2
    assert len(digest1) == 64  # SHA-256


def test_schedule_state_transitions():
    """Verify valid and invalid transitions for ScheduleState."""
    assert ScheduleState.PAUSED in VALID_SCHEDULE_TRANSITIONS[ScheduleState.ACTIVE]
    assert ScheduleState.COMPLETED in VALID_SCHEDULE_TRANSITIONS[ScheduleState.ACTIVE]
    assert ScheduleState.ACTIVE in VALID_SCHEDULE_TRANSITIONS[ScheduleState.PAUSED]

    # Terminal states cannot transition to anything
    assert len(VALID_SCHEDULE_TRANSITIONS[ScheduleState.COMPLETED]) == 0
    assert len(VALID_SCHEDULE_TRANSITIONS[ScheduleState.CANCELLED]) == 0
    assert len(VALID_SCHEDULE_TRANSITIONS[ScheduleState.FAILED]) == 0


def test_run_state_transitions():
    """Verify valid and invalid transitions for RunState."""
    assert RunState.SUCCESS in VALID_RUN_TRANSITIONS[RunState.RUNNING]
    assert RunState.STOPPING in VALID_RUN_TRANSITIONS[RunState.RUNNING]
    assert RunState.INTERRUPTED in VALID_RUN_TRANSITIONS[RunState.STOPPING]

    # Terminal states
    assert len(VALID_RUN_TRANSITIONS[RunState.SUCCESS]) == 0
    assert len(VALID_RUN_TRANSITIONS[RunState.FAILED]) == 0
    assert len(VALID_RUN_TRANSITIONS[RunState.SKIPPED]) == 0


@pytest.mark.asyncio
async def test_scheduler_database_pragmas_and_migrations(tmp_path):
    """Verify WAL mode, synchronous=FULL, foreign keys, and tables in scheduler.db."""
    db_file = tmp_path / "scheduler.db"
    db_manager = SchedulerDatabaseManager(db_file)
    await db_manager.initialize()

    conn = await db_manager.get_connection()

    # Check pragmas
    async with conn.execute("PRAGMA journal_mode;") as cur:
        row = await cur.fetchone()
        assert row[0].lower() == "wal"

    async with conn.execute("PRAGMA synchronous;") as cur:
        row = await cur.fetchone()
        assert row[0] == 2  # 2 corresponds to FULL

    async with conn.execute("PRAGMA foreign_keys;") as cur:
        row = await cur.fetchone()
        assert row[0] == 1

    # Check tables exist
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ) as cur:
        tables = [r[0] for r in await cur.fetchall()]
        assert "scheduled_jobs" in tables
        assert "job_runs" in tables
        assert "scheduler_quota_usage" in tables
        assert "scheduler_events" in tables
        assert "schema_migrations" in tables

    # Check migration version
    async with conn.execute("SELECT version FROM schema_migrations;") as cur:
        row = await cur.fetchone()
        assert row[0] == 1

    await db_manager.close()
