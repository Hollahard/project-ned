"""Episodic memory tier: Query interface over session history and message FTS5 index."""

import logging
from typing import Any, Dict, List, Optional
from friday.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """Queries existing session timeline and message FTS5 index strictly bounded to workspace_root."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    async def search(
        self,
        query: str,
        workspace_root: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search historical conversation messages via FTS5 strictly joined to active workspace_root."""
        conn = await self.db.get_connection()
        clean_query = query.strip().replace('"', '""')
        if not clean_query:
            return []

        # Safe FTS5 match token
        fts_match = f'"{clean_query}"'

        sql = """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title as session_title
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            JOIN messages_fts f ON m.rowid = f.rowid
            WHERE messages_fts MATCH :query
              AND s.working_directory = :workspace_root
            ORDER BY m.created_at DESC
            LIMIT :limit
        """
        async with conn.execute(sql, {"query": fts_match, "workspace_root": workspace_root, "limit": limit}) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "message_id": row[0],
                    "session_id": row[1],
                    "role": row[2],
                    "content": row[3],
                    "created_at": row[4],
                    "session_title": row[5],
                }
                for row in rows
            ]

    async def get_recent_session_turns(
        self,
        session_id: str,
        workspace_root: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent turns for an explicit session verified against active workspace_root."""
        conn = await self.db.get_connection()
        sql = """
            SELECT m.id, m.role, m.content, m.created_at
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.session_id = :session_id
              AND s.working_directory = :workspace_root
            ORDER BY m.created_at DESC
            LIMIT :limit
        """
        async with conn.execute(sql, {"session_id": session_id, "workspace_root": workspace_root, "limit": limit}) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "message_id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "created_at": row[3],
                }
                for row in reversed(rows)
            ]
