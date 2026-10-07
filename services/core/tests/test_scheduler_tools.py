"""Tests for Friday Schedule Tools (Phase 11 Milestone 5).

Verifies:
1. schedule.create: Risk 0 for read-only, Risk 1 for workspace writes, Risk 2 strictly forbidden.
2. Parameter validation (5-field cron, delay >= 60s, IANA timezone).
3. Deterministic execution specification digest computation.
4. schedule.list, schedule.get, schedule.runs query capabilities.
5. schedule.pause, schedule.resume, schedule.cancel, and schedule.delete lifecycle control.
6. Anti-recursion enforcement: scheduled execution guard denies all schedule.* tools.
"""

import json
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
)
from friday.scheduler.worker import ScheduledExecutionGuard
from friday.tools.schedule import (
    ScheduleCancelTool,
    ScheduleCreateTool,
    ScheduleDeleteTool,
    ScheduleGetTool,
    ScheduleListTool,
    SchedulePauseTool,
    ScheduleResumeTool,
    ScheduleRunsTool,
)


@pytest_asyncio.fixture
async def scheduler_db(tmp_path):
    db_file = tmp_path / "scheduler_tools.db"
    mgr = SchedulerDatabaseManager(db_file)
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.fixture
def workspace_dir(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    return ws


@pytest.mark.asyncio
async def test_schedule_create_risk_classification_and_execution(scheduler_db, workspace_dir):
    """Verifies Risk 0 creation, Risk 1 classification, and Risk 2 prohibition."""
    tool = ScheduleCreateTool(scheduler_db, workspace_dir)

    # 1. Dynamic risk classification
    assert tool.classify_risk({"max_risk_level": 0}) == 0
    assert tool.classify_risk({"max_risk_level": 1}) == 1
    assert tool.classify_risk({"max_risk_level": 2}) == 2

    # 2. Risk 2 creation attempt fails closed
    res_risk2 = await tool.execute(
        "call-1",
        {
            "title": "Malicious Exec Job",
            "prompt": "Run powershell script",
            "schedule_type": "once",
            "delay_seconds": 120,
            "max_risk_level": 2,
        },
    )
    assert not res_risk2.success
    assert "strictly forbidden" in (res_risk2.error or "")

    # 3. Valid Risk 0 creation
    res_valid = await tool.execute(
        "call-2",
        {
            "title": "Clean Read Job",
            "prompt": "Check build artifacts",
            "schedule_type": "cron",
            "cron_expression": "*/10 * * * *",
            "timezone": "America/New_York",
            "allowed_tool_ids": ["filesystem.read"],
            "max_risk_level": 0,
        },
    )
    assert res_valid.success
    data = json.loads(res_valid.output)
    assert data["title"] == "Clean Read Job"
    assert data["state"] == "active"
    assert data["approval_digest"] is not None

    # Verify job persisted in DB
    job_id = data["job_id"]
    persisted = await scheduler_db.get_job(job_id)
    assert persisted is not None
    assert persisted.schedule_type == ScheduleType.CRON
    assert persisted.permission_snapshot.max_risk_level == 0


@pytest.mark.asyncio
async def test_schedule_create_validation_and_idempotency(scheduler_db, workspace_dir):
    """Verifies validation of delays and cron expressions, plus idempotency."""
    tool = ScheduleCreateTool(scheduler_db, workspace_dir)

    # Sub-60s delay rejected
    res_sub60 = await tool.execute(
        "call-delay-1",
        {
            "title": "Too Fast",
            "prompt": "Ping",
            "schedule_type": "once",
            "delay_seconds": 30,
        },
    )
    assert not res_sub60.success
    assert "at least 60 seconds" in (res_sub60.error or "")

    # Invalid 6-field cron rejected
    res_cron6 = await tool.execute(
        "call-cron-1",
        {
            "title": "Too Many Fields",
            "prompt": "Ping",
            "schedule_type": "cron",
            "cron_expression": "0 */5 * * * *",
        },
    )
    assert not res_cron6.success
    assert "5 whitespace-separated fields" in (res_cron6.error or "")

    # Idempotent creation
    idem_args = {
        "title": "Idempotent Job",
        "prompt": "Perform audit",
        "schedule_type": "once",
        "delay_seconds": 300,
        "idempotency_key": "my-idempotent-key-1",
    }
    res_first = await tool.execute("call-id-1", idem_args)
    res_second = await tool.execute("call-id-2", idem_args)
    assert res_first.success and res_second.success
    data1 = json.loads(res_first.output)
    data2 = json.loads(res_second.output)
    assert data1["job_id"] == data2["job_id"]


@pytest.mark.asyncio
async def test_schedule_management_tools(scheduler_db, workspace_dir):
    """Verifies schedule.list, get, runs, pause, resume, cancel, delete."""
    create_tool = ScheduleCreateTool(scheduler_db, workspace_dir)
    list_tool = ScheduleListTool(scheduler_db, workspace_dir)
    get_tool = ScheduleGetTool(scheduler_db)
    runs_tool = ScheduleRunsTool(scheduler_db)
    pause_tool = SchedulePauseTool(scheduler_db)
    resume_tool = ScheduleResumeTool(scheduler_db)
    cancel_tool = ScheduleCancelTool(scheduler_db)
    delete_tool = ScheduleDeleteTool(scheduler_db)

    # Create job
    create_res = await create_tool.execute(
        "call-c",
        {
            "title": "Lifecycle Test",
            "prompt": "Audit disk usage",
            "schedule_type": "cron",
            "cron_expression": "0 12 * * *",
            "allowed_tool_ids": ["filesystem.read"],
        },
    )
    assert create_res.success
    job_id = json.loads(create_res.output)["job_id"]

    # List jobs
    list_res = await list_tool.execute("call-l", {})
    assert list_res.success
    jobs_list = json.loads(list_res.output)
    assert any(j["job_id"] == job_id for j in jobs_list)

    # Get job
    get_res = await get_tool.execute("call-g", {"job_id": job_id})
    assert get_res.success
    job_data = json.loads(get_res.output)
    assert job_data["id"] == job_id
    assert job_data["state"] == "active"

    # Pause job
    pause_res = await pause_tool.execute("call-p", {"job_id": job_id, "reason": "Operator pause"})
    assert pause_res.success
    paused_job = await scheduler_db.get_job(job_id)
    assert paused_job.state == ScheduleState.PAUSED

    # Resume job
    resume_res = await resume_tool.execute("call-r", {"job_id": job_id})
    assert resume_res.success
    resumed_job = await scheduler_db.get_job(job_id)
    assert resumed_job.state == ScheduleState.ACTIVE
    assert resumed_job.next_run_at_utc is not None

    # Runs list
    runs_res = await runs_tool.execute("call-runs", {"job_id": job_id})
    assert runs_res.success
    runs_data = json.loads(runs_res.output)
    assert isinstance(runs_data, list)

    # Cancel job
    cancel_res = await cancel_tool.execute("call-x", {"job_id": job_id})
    assert cancel_res.success
    cancelled_job = await scheduler_db.get_job(job_id)
    assert cancelled_job.state == ScheduleState.CANCELLED

    # Delete job (tombstone)
    delete_res = await delete_tool.execute("call-d", {"job_id": job_id})
    assert delete_res.success
    deleted_job = await scheduler_db.get_job(job_id)
    assert deleted_job.deleted_at_utc is not None


def test_anti_recursion_guard_blocks_schedule_tools(workspace_dir):
    """Anti-recursion: Snapshot rejects forbidden tools and Guard denies invocation."""
    from pydantic import ValidationError

    # 1. Model rejects forbidden tools at creation time
    with pytest.raises(ValidationError, match="cannot be granted in scheduled execution"):
        JobPermissionSnapshot(
            source_session_id="sess-sched",
            workspace_root=str(workspace_dir),
            allowed_tool_ids=["schedule.create"],
            max_risk_level=1,
        )

    # 2. Guard rejects invocation even if somehow dispatched
    valid_snapshot = JobPermissionSnapshot(
        source_session_id="sess-sched",
        workspace_root=str(workspace_dir),
        allowed_tool_ids=["filesystem.read"],
        max_risk_level=1,
    )
    guard = ScheduledExecutionGuard(valid_snapshot)

    schedule_tools = [
        "schedule.create",
        "schedule.list",
        "schedule.get",
        "schedule.runs",
        "schedule.pause",
        "schedule.cancel",
        "schedule.resume",
        "schedule.delete",
    ]
    for st in schedule_tools:
        with pytest.raises(PolicyDeniedError, match="anti-recursion rule"):
            guard.check_tool_invocation(st, {})
