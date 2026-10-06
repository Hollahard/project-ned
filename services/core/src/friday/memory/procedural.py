"""Procedural memory tier: Playbooks, recipes, and workflow steps."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from friday.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class ProceduralMemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_root: str
    sensitivity: str = "normal"  # "normal" or "security"
    title: str
    steps: str
    source: str
    approved: int = 0  # 0: unapproved, 1: verified / approved by user
    source_session_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ProceduralMemory:
    """Manages procedural memory entries with FTS5 search strictly scoped to workspace_root."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    async def save(self, entry: ProceduralMemoryEntry, is_system_authorized: bool = False) -> str:
        """Insert or replace a procedural entry. Forces approved=0 unless explicitly system-authorized."""
        conn = await self.db.get_connection()
        entry.updated_at = time.time()
        if not is_system_authorized:
            entry.approved = 0  # Client/tool can NEVER self-approve

        sql = """
            INSERT INTO procedural_memory (
                id, workspace_root, sensitivity, title, steps, source,
                approved, source_session_id, created_at, updated_at
            ) VALUES (
                :id, :workspace_root, :sensitivity, :title, :steps, :source,
                :approved, :source_session_id, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                sensitivity = excluded.sensitivity,
                title = excluded.title,
                steps = excluded.steps,
                source = excluded.source,
                approved = excluded.approved,
                updated_at = excluded.updated_at
        """
        await conn.execute(sql, entry.model_dump())
        await conn.commit()
        logger.info("Saved procedural memory '%s' (approved=%d)", entry.id, entry.approved)
        return entry.id

    async def get(self, memory_id: str, workspace_root: str) -> Optional[ProceduralMemoryEntry]:
        """Retrieve an entry by ID, strictly verifying workspace_root match."""
        conn = await self.db.get_connection()
        sql = """
            SELECT id, workspace_root, sensitivity, title, steps, source,
                   approved, source_session_id, created_at, updated_at
            FROM procedural_memory
            WHERE id = :id AND workspace_root = :workspace_root
        """
        async with conn.execute(sql, {"id": memory_id, "workspace_root": workspace_root}) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return ProceduralMemoryEntry(
                id=row[0],
                workspace_root=row[1],
                sensitivity=row[2],
                title=row[3],
                steps=row[4],
                source=row[5],
                approved=row[6],
                source_session_id=row[7],
                created_at=row[8],
                updated_at=row[9],
            )

    async def search(
        self,
        query: str,
        workspace_root: str,
        limit: int = 5,
    ) -> List[ProceduralMemoryEntry]:
        """FTS5 search with mandatory INNER JOIN enforcing workspace_root containment."""
        conn = await self.db.get_connection()
        clean_query = query.strip().replace('"', '""')
        if not clean_query:
            return []

        fts_match = f'"{clean_query}"'
        sql = """
            SELECT p.id, p.workspace_root, p.sensitivity, p.title, p.steps, p.source,
                   p.approved, p.source_session_id, p.created_at, p.updated_at
            FROM procedural_memory p
            JOIN procedural_memory_fts f ON p.rowid = f.rowid
            WHERE procedural_memory_fts MATCH :query
              AND p.workspace_root = :workspace_root
            ORDER BY rank
            LIMIT :limit
        """
        async with conn.execute(sql, {"query": fts_match, "workspace_root": workspace_root, "limit": limit}) as cursor:
            rows = await cursor.fetchall()
            return [
                ProceduralMemoryEntry(
                    id=row[0],
                    workspace_root=row[1],
                    sensitivity=row[2],
                    title=row[3],
                    steps=row[4],
                    source=row[5],
                    approved=row[6],
                    source_session_id=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                )
                for row in rows
            ]

    async def approve(self, memory_id: str, workspace_root: str) -> bool:
        """Promote an entry to approved=1, strictly requiring workspace_root match."""
        conn = await self.db.get_connection()
        sql = """
            UPDATE procedural_memory
            SET approved = 1, updated_at = :now
            WHERE id = :id AND workspace_root = :workspace_root
        """
        cursor = await conn.execute(sql, {"id": memory_id, "workspace_root": workspace_root, "now": time.time()})
        await conn.commit()
        return cursor.rowcount > 0

    async def delete(self, memory_id: str, workspace_root: str) -> bool:
        """Delete an entry by ID, strictly requiring workspace_root match."""
        conn = await self.db.get_connection()
        sql = "DELETE FROM procedural_memory WHERE id = :id AND workspace_root = :workspace_root"
        cursor = await conn.execute(sql, {"id": memory_id, "workspace_root": workspace_root})
        await conn.commit()
        return cursor.rowcount > 0
