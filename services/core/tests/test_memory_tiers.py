"""Unit and integration tests for Friday 4-tier memory subsystem."""

import pytest
from pathlib import Path
import aiosqlite

from friday.memory.coordinator import MemoryCoordinator
from friday.memory.episodic import EpisodicMemory
from friday.memory.procedural import ProceduralMemory, ProceduralMemoryEntry
from friday.memory.semantic import SemanticMemory, SemanticMemoryEntry
from friday.memory.working import WorkingMemory
from friday.storage.db import DatabaseManager


@pytest.fixture
async def memory_db(tmp_path: Path):
    db_file = tmp_path / "memory_test.db"
    manager = DatabaseManager(db_file)
    await manager.initialize()
    yield manager
    await manager.close()


def test_working_memory_lifecycle():
    wm = WorkingMemory()
    wm.add_note("Checked repository layout")
    wm.add_note("Found pyproject.toml in services/core")

    notes = wm.get_notes()
    assert len(notes) == 2
    assert "Checked repository layout" in notes[0]

    summary = wm.format_summary(max_chars=50)
    assert "[Working notes truncated]" in summary

    wm.clear()
    assert len(wm.get_notes()) == 0


@pytest.mark.asyncio
async def test_semantic_memory_crud_and_fts_scoped(memory_db: DatabaseManager, tmp_path: Path):
    ws_a = str(tmp_path / "workspace_a")
    ws_b = str(tmp_path / "workspace_b")

    sem = SemanticMemory(memory_db)

    # Save entry in Workspace A
    entry_a = SemanticMemoryEntry(
        workspace_root=ws_a,
        category="architecture",
        title="Blackwell sm_120 Compute",
        content="NVIDIA RTX 5090 Blackwell architecture uses Compute Capability (12, 0).",
    )
    id_a = await sem.save(entry_a)

    # Save entry in Workspace B
    entry_b = SemanticMemoryEntry(
        workspace_root=ws_b,
        category="architecture",
        title="Blackwell sm_120 in Workspace B",
        content="Other workspace notes about Blackwell architecture.",
    )
    id_b = await sem.save(entry_b)

    # 1. Search in Workspace A: Must find entry A, NEVER entry B
    results_a = await sem.search("Blackwell", workspace_root=ws_a)
    assert len(results_a) == 1
    assert results_a[0].id == id_a
    assert results_a[0].title == "Blackwell sm_120 Compute"

    # 2. Search in Workspace B: Must find entry B, NEVER entry A
    results_b = await sem.search("Blackwell", workspace_root=ws_b)
    assert len(results_b) == 1
    assert results_b[0].id == id_b

    # 3. Get verified against workspace
    get_res = await sem.get(id_a, workspace_root=ws_a)
    assert get_res is not None
    assert get_res.title == "Blackwell sm_120 Compute"

    # Cross-workspace get fails
    get_cross = await sem.get(id_a, workspace_root=ws_b)
    assert get_cross is None

    # 4. Delete verified against workspace
    del_res = await sem.delete(id_a, workspace_root=ws_a)
    assert del_res is True
    assert await sem.get(id_a, workspace_root=ws_a) is None


@pytest.mark.asyncio
async def test_procedural_memory_crud_and_approved_flag(memory_db: DatabaseManager, tmp_path: Path):
    ws = str(tmp_path / "workspace")
    proc = ProceduralMemory(memory_db)

    # Attempt to save with approved=1 as client
    entry = ProceduralMemoryEntry(
        workspace_root=ws,
        title="Run Core Pytest Suite",
        steps="pytest services/core/tests/ -v",
        source="unit_test",
        approved=1,  # Client tries to set approved
    )
    # is_system_authorized=False forces approved=0
    proc_id = await proc.save(entry, is_system_authorized=False)

    saved = await proc.get(proc_id, workspace_root=ws)
    assert saved is not None
    assert saved.approved == 0  # Forced to 0!

    # Promote to approved via authorized method
    ok = await proc.approve(proc_id, workspace_root=ws)
    assert ok is True

    promoted = await proc.get(proc_id, workspace_root=ws)
    assert promoted is not None
    assert promoted.approved == 1


@pytest.mark.asyncio
async def test_episodic_memory_workspace_scoped(memory_db: DatabaseManager, tmp_path: Path):
    conn = await memory_db.get_connection()
    ws_1 = str(tmp_path / "ws1")
    ws_2 = str(tmp_path / "ws2")

    # Insert test sessions
    await conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) "
        "VALUES ('s1', 'Session 1', 1.0, 1.0, :ws, 'default')",
        {"ws": ws_1},
    )
    await conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile) "
        "VALUES ('s2', 'Session 2', 2.0, 2.0, :ws, 'default')",
        {"ws": ws_2},
    )

    # Insert test messages
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES ('m1', 's1', 'user', 'Deploy configuration for Friday on port 8200', 1.0)"
    )
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES ('m2', 's2', 'user', 'Deploy configuration for Friday on port 9000', 2.0)"
    )
    await conn.commit()

    episodic = EpisodicMemory(memory_db)

    # Search in ws_1
    res_1 = await episodic.search("Deploy", workspace_root=ws_1)
    assert len(res_1) == 1
    assert res_1[0]["session_id"] == "s1"
    assert "8200" in res_1[0]["content"]

    # Search in ws_2
    res_2 = await episodic.search("Deploy", workspace_root=ws_2)
    assert len(res_2) == 1
    assert res_2[0]["session_id"] == "s2"
    assert "9000" in res_2[0]["content"]
