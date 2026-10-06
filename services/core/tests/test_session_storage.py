"""Unit and integration tests for SQLite session storage, 100-message persistence, FTS5, and cascade deletion."""

import pytest
from pathlib import Path
from friday.storage.db import DatabaseManager
from friday.sessions.manager import SessionManager


@pytest.mark.asyncio
async def test_session_100_message_persistence_across_restarts(tmp_path: Path):
    db_file = tmp_path / "test_friday.db"

    # Step 1: Open DB and create a session with 100 messages
    db_mgr = DatabaseManager(db_file)
    session_mgr = SessionManager(db_mgr)

    session = await session_mgr.create_session(
        title="100 Turn Long Conversation",
        working_directory=".",
        model_profile="qwen-30b",
    )

    for i in range(100):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Turn {i}: Query or answer regarding topic-{i} with unique keyword zebra_{i}"
        await session_mgr.add_message(session.id, role=role, content=content)

    # Verify history has 100 messages
    history = await session_mgr.get_history(session.id, limit=150)
    assert len(history) == 100
    assert "zebra_0" in history[0].content
    assert "zebra_99" in history[99].content

    # Step 2: Simulate restart by closing connection and creating a fresh manager
    await db_mgr.close()

    db_mgr_restarted = DatabaseManager(db_file)
    session_mgr_restarted = SessionManager(db_mgr_restarted)

    restarted_session = await session_mgr_restarted.get_session(session.id)
    assert restarted_session is not None
    assert restarted_session.title == "100 Turn Long Conversation"

    restarted_history = await session_mgr_restarted.get_history(session.id, limit=150)
    assert len(restarted_history) == 100
    assert "zebra_0" in restarted_history[0].content
    assert "zebra_99" in restarted_history[99].content

    # Step 3: Test FTS5 full-text search across messages
    search_results = await session_mgr_restarted.search_messages("zebra_42")
    assert len(search_results) == 1
    assert "zebra_42" in search_results[0]["content"]
    assert search_results[0]["session_id"] == session.id

    # Step 4: Test cascade deletion
    await session_mgr_restarted.delete_session(session.id)
    assert await session_mgr_restarted.get_session(session.id) is None

    # Verify messages and FTS entries were cascade deleted
    db_conn = await db_mgr_restarted.get_connection()
    async with db_conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session.id,)) as cur:
        row = await cur.fetchone()
        assert row[0] == 0

    async with db_conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'zebra_42'") as cur:
        row = await cur.fetchone()
        assert row[0] == 0

    await db_mgr_restarted.close()


@pytest.mark.asyncio
async def test_settings_and_model_profiles_storage(tmp_path: Path):
    db_file = tmp_path / "test_settings.db"
    db_mgr = DatabaseManager(db_file)
    session_mgr = SessionManager(db_mgr)

    # Test settings
    assert await session_mgr.get_setting("theme") is None
    await session_mgr.set_setting("theme", "dark")
    assert await session_mgr.get_setting("theme") == "dark"

    # Update existing setting
    await session_mgr.set_setting("theme", "midnight")
    assert await session_mgr.get_setting("theme") == "midnight"

    # Test model profiles
    profile = {
        "id": "exl3-mistral-24b",
        "name": "Mistral Small 24B",
        "context_window": 32768,
        "max_tokens": 4096,
        "temperature": 0.6,
        "top_p": 0.95,
        "resident": True,
    }
    await session_mgr.save_model_profile(profile)

    profiles = await session_mgr.list_model_profiles()
    assert len(profiles) == 1
    p = profiles[0]
    assert p["id"] == "exl3-mistral-24b"
    assert p["name"] == "Mistral Small 24B"
    assert p["context_window"] == 32768
    assert p["resident"] is True

    await db_mgr.close()
