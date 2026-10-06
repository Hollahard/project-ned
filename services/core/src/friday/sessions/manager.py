"""Session and history management backed by SQLite."""

import json
import time
import uuid
import logging
from typing import List
from pydantic import BaseModel, Field

from friday.inference.protocol import ChatMessage
from friday.storage.db import DatabaseManager

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

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

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
