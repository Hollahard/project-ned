"""Session and history management backed by SQLite."""

import json
import time
import uuid
import logging
from typing import List
from pydantic import BaseModel, Field

from friday.inference.protocol import ChatMessage
from friday.storage.db import DatabaseManager
from friday.sessions.budget import ContextBudget

logger = logging.getLogger(__name__)


class Session(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    working_directory: str
    model_profile: str


class SessionManager:
    """Provides transactional session creation, message storage, and history querying."""

    def __init__(
        self, db_manager: DatabaseManager, context_budget: ContextBudget | None = None
    ) -> None:
        self.db_manager = db_manager
        self.context_budget = context_budget or ContextBudget()

    async def create_session(
        self,
        title: str = "New Session",
        working_directory: str = ".",
        model_profile: str = "default",
    ) -> Session:
        session_id = str(uuid.uuid4())
        now = time.time()
        db = await self.db_manager.get_connection()
        await db.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, working_directory, model_profile)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, title, now, now, working_directory, model_profile),
        )
        await db.commit()
        return Session(
            id=session_id,
            title=title,
            created_at=now,
            updated_at=now,
            working_directory=working_directory,
            model_profile=model_profile,
        )

    async def get_session(self, session_id: str) -> Session | None:
        db = await self.db_manager.get_connection()
        async with db.execute(
            "SELECT id, title, created_at, updated_at, working_directory, model_profile FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Session(
                id=row[0],
                title=row[1],
                created_at=row[2],
                updated_at=row[3],
                working_directory=row[4],
                model_profile=row[5],
            )

    async def list_sessions(self) -> List[Session]:
        db = await self.db_manager.get_connection()
        async with db.execute(
            "SELECT id, title, created_at, updated_at, working_directory, model_profile FROM sessions ORDER BY updated_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                Session(
                    id=r[0],
                    title=r[1],
                    created_at=r[2],
                    updated_at=r[3],
                    working_directory=r[4],
                    model_profile=r[5],
                )
                for r in rows
            ]

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        msg_id = str(uuid.uuid4())
        now = time.time()
        tc_json = json.dumps(tool_calls) if tool_calls else None
        db = await self.db_manager.get_connection()
        await db.execute(
            """
            INSERT INTO messages (id, session_id, role, content, tool_calls, tool_call_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, role, content, tc_json, tool_call_id, now),
        )
        await db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        await db.commit()

    async def get_history(self, session_id: str, limit: int = 100) -> List[ChatMessage]:
        db = await self.db_manager.get_connection()
        async with db.execute(
            """
            SELECT role, content, tool_calls, tool_call_id FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            messages = []
            for r in rows:
                tc = json.loads(r[2]) if r[2] else None
                messages.append(
                    ChatMessage(
                        role=r[0],
                        content=r[1],
                        tool_calls=tc,
                        tool_call_id=r[3],
                    )
                )
            return messages

    async def delete_session(self, session_id: str) -> None:
        db = await self.db_manager.get_connection()
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()

    async def get_compacted_history(
        self,
        session_id: str,
        budget_tokens: int | None = None,
        limit: int = 100,
    ) -> List[ChatMessage]:
        """Fetch history and compact it to fit within context budget."""
        raw_history = await self.get_history(session_id, limit=limit)
        return self.context_budget.compact_history(raw_history, budget_tokens=budget_tokens)

    async def search_messages(self, query: str, limit: int = 20) -> List[dict]:
        """Search message content using SQLite FTS5."""
        db = await self.db_manager.get_connection()
        async with db.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at
            FROM messages_fts f
            JOIN messages m ON f.rowid = m.rowid
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "session_id": r[1],
                    "role": r[2],
                    "content": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]

    async def get_setting(self, key: str) -> str | None:
        db = await self.db_manager.get_connection()
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        db = await self.db_manager.get_connection()
        now = time.time()
        await db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        await db.commit()

    async def list_model_profiles(self) -> List[dict]:
        db = await self.db_manager.get_connection()
        async with db.execute(
            "SELECT id, name, context_window, max_tokens, temperature, top_p, resident, created_at FROM model_profiles"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "context_window": r[2],
                    "max_tokens": r[3],
                    "temperature": r[4],
                    "top_p": r[5],
                    "resident": bool(r[6]),
                    "created_at": r[7],
                }
                for r in rows
            ]

    async def save_model_profile(self, profile: dict) -> None:
        db = await self.db_manager.get_connection()
        now = time.time()
        await db.execute(
            """
            INSERT INTO model_profiles (id, name, context_window, max_tokens, temperature, top_p, resident, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                context_window = excluded.context_window,
                max_tokens = excluded.max_tokens,
                temperature = excluded.temperature,
                top_p = excluded.top_p,
                resident = excluded.resident
            """,
            (
                profile["id"],
                profile.get("name", profile["id"]),
                profile.get("context_window", 32768),
                profile.get("max_tokens", 4096),
                profile.get("temperature", 0.7),
                profile.get("top_p", 0.9),
                1 if profile.get("resident", True) else 0,
                now,
            ),
        )
        await db.commit()
