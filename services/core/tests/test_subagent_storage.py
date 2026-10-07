"""Tests for Subagent SQLite database persistence and budget accounting (Phase 12 Milestone 2)."""

import pytest
from pathlib import Path
from friday.subagents.db import SubagentDatabaseManager
from friday.subagents.models import (
    InvalidStateTransitionError,
    PolicyDeniedError,
    SubagentRunState,
    SubagentSpec,
)


@pytest.fixture
async def subagent_db(tmp_path):
    db_file = tmp_path / "test_subagents.db"
    manager = SubagentDatabaseManager(db_file)
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_subagent_db_initialization(subagent_db):
    """Verify database initializes properly in WAL mode."""
    active_runs = await subagent_db.list_active_runs()
    assert active_runs == []


@pytest.mark.asyncio
async def test_subagent_reservation_and_concurrency(subagent_db, tmp_path):
    """Verify atomic reservation and session concurrency caps."""
    workspace = str(tmp_path)
    spec1 = SubagentSpec(
        role="Auditor 1",
        task_prompt="Audit 1",
        parent_session_id="session-1",
        parent_turn_id="turn-1",
        workspace_root=workspace,
        token_budget=3000,
    )
    spec2 = SubagentSpec(
        role="Auditor 2",
        task_prompt="Audit 2",
        parent_session_id="session-1",
        parent_turn_id="turn-1",
        workspace_root=workspace,
        token_budget=3000,
    )
    spec3 = SubagentSpec(
        role="Auditor 3",
        task_prompt="Audit 3",
        parent_session_id="session-1",
        parent_turn_id="turn-1",
        workspace_root=workspace,
        token_budget=3000,
    )

    # Admit up to max_concurrency=2
    id1 = await subagent_db.reserve_subagent_run(spec1, max_concurrency=2)
    id2 = await subagent_db.reserve_subagent_run(spec2, max_concurrency=2)
    assert id1 is not None
    assert id2 is not None

    # Exceeding concurrency cap must raise PolicyDeniedError
    with pytest.raises(PolicyDeniedError, match="concurrency limit reached"):
        await subagent_db.reserve_subagent_run(spec3, max_concurrency=2)

    # Check active runs
    active = await subagent_db.list_active_runs()
    assert len(active) == 2
    assert {r["id"] for r in active} == {id1, id2}


@pytest.mark.asyncio
async def test_single_terminal_state_guarantee(subagent_db, tmp_path):
    """Verify once a run is in a terminal state, subsequent transitions fail."""
    workspace = str(tmp_path)
    spec = SubagentSpec(
        role="Auditor",
        task_prompt="Audit code",
        parent_session_id="session-1",
        parent_turn_id="turn-1",
        workspace_root=workspace,
        token_budget=4000,
    )
    run_id = await subagent_db.reserve_subagent_run(spec)

    # Transition to COMPLETED
    await subagent_db.complete_subagent_run(
        run_id=run_id,
        state=SubagentRunState.COMPLETED,
        consumed_tokens=2500,
        tool_calls_count=3,
        output_summary="Audit clean",
    )

    run = await subagent_db.get_run(run_id)
    assert run["state"] == SubagentRunState.COMPLETED
    assert run["consumed_tokens"] == 2500
    assert run["quiescence_confirmed"] is True

    # Attempting to re-complete or transition to FAILED must raise InvalidStateTransitionError
    with pytest.raises(InvalidStateTransitionError, match="already in terminal state"):
        await subagent_db.complete_subagent_run(
            run_id=run_id,
            state=SubagentRunState.FAILED,
            consumed_tokens=0,
            tool_calls_count=0,
            error_summary="Late error",
        )


@pytest.mark.asyncio
async def test_subagent_cancellation_flow(subagent_db, tmp_path):
    """Verify cancellation marks STOPPING and allows final CANCELLED transition."""
    workspace = str(tmp_path)
    spec = SubagentSpec(
        role="Worker",
        task_prompt="Long running work",
        parent_session_id="session-cancel",
        parent_turn_id="turn-cancel",
        workspace_root=workspace,
    )
    run_id = await subagent_db.reserve_subagent_run(spec)

    # Request cancellation
    res = await subagent_db.request_cancellation(run_id)
    assert res is True

    run = await subagent_db.get_run(run_id)
    assert run["state"] == SubagentRunState.STOPPING
    assert run["cancellation_requested"] is True

    # Complete as CANCELLED
    await subagent_db.complete_subagent_run(
        run_id=run_id,
        state=SubagentRunState.CANCELLED,
        consumed_tokens=500,
        tool_calls_count=1,
        output_summary="Partial results",
    )

    final_run = await subagent_db.get_run(run_id)
    assert final_run["state"] == SubagentRunState.CANCELLED


@pytest.mark.asyncio
async def test_crash_recovery_abandoned_runs(subagent_db, tmp_path):
    """Verify non-terminal runs are marked INTERRUPTED during crash recovery."""
    workspace = str(tmp_path)
    spec = SubagentSpec(
        role="Zombie",
        task_prompt="Never finished",
        parent_session_id="session-crash",
        parent_turn_id="turn-crash",
        workspace_root=workspace,
    )
    run_id = await subagent_db.reserve_subagent_run(spec)

    # Verify currently active
    active = await subagent_db.list_active_runs()
    assert len(active) == 1

    # Simulate restart and recovery
    recovered_count = await subagent_db.recover_abandoned_runs()
    assert recovered_count == 1

    # Now no runs should be active
    active_after = await subagent_db.list_active_runs()
    assert len(active_after) == 0

    run = await subagent_db.get_run(run_id)
    assert run["state"] == SubagentRunState.INTERRUPTED
    assert run["quiescence_confirmed"] is True
    assert "interrupted" in run["error_summary"].lower()


@pytest.mark.asyncio
async def test_subagent_summary_truncation(subagent_db, tmp_path):
    """Verify summary is truncated to 64 KiB on complete."""
    workspace = str(tmp_path)
    spec = SubagentSpec(
        role="Verbose",
        task_prompt="Dump everything",
        parent_session_id="session-trunc",
        parent_turn_id="turn-trunc",
        workspace_root=workspace,
    )
    run_id = await subagent_db.reserve_subagent_run(spec)

    giant_summary = "B" * (100 * 1024)  # 100 KiB
    await subagent_db.complete_subagent_run(
        run_id=run_id,
        state=SubagentRunState.COMPLETED,
        consumed_tokens=1000,
        tool_calls_count=1,
        output_summary=giant_summary,
    )

    run = await subagent_db.get_run(run_id)
    stored_bytes = len(run["output_summary"].encode("utf-8"))
    assert stored_bytes <= 65536
    assert "[TRUNCATED 64 KiB]" in run["output_summary"]
