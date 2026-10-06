"""Semantic memory tier: Long-term persistent facts and architectural knowledge."""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from friday.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class SemanticMemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_root: str
    sensitivity: str = "normal"  # "normal" or "security"
    category: str = "fact"       # "fact", "architecture", "convention", "dependency"
    title: str
    content: str
    source_session_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class SemanticMemory:
    """Manages semantic memory entries with FTS5 search strictly scoped to workspace_root."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    async def save(self, entry: SemanticMemoryEntry) -> str:
        """Insert or replace a semantic memory entry."""
        conn = await self.db.get_connection()
        entry.updated_at = time.time()
        sql = """
            INSERT INTO semantic_memory (
                id, workspace_root, sensitivity, category, title, content,
                source_session_id, created_at, updated_at
            ) VALUES (
                :id, :workspace_root, :sensitivity, :category, :title, :content,
                :source_session_id, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                sensitivity = excluded.sensitivity,
                category = excluded.category,
                title = excluded.title,
                content = excluded.content,
                updated_at = excluded.updated_at
        """
        await conn.execute(sql, entry.model_dump())
        await conn.commit()
        logger.info("Saved semantic memory '%s' in workspace '%s'", entry.id, entry.workspace_root)
        return entry.id

    async def get(self, memory_id: str, workspace_root: str) -> Optional[SemanticMemoryEntry]:
        """Retrieve an entry by ID, strictly verifying workspace_root match."""
        conn = await self.db.get_connection()
        sql = """
            SELECT id, workspace_root, sensitivity, category, title, content,
                   source_session_id, created_at, updated_at
            FROM semantic_memory
            WHERE id = :id AND workspace_root = :workspace_root
        """
        async with conn.execute(sql, {"id": memory_id, "workspace_root": workspace_root}) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return SemanticMemoryEntry(
                id=row[0],
                workspace_root=row[1],
                sensitivity=row[2],
                category=row[3],
                title=row[4],
                content=row[5],
                source_session_id=row[6],
                created_at=row[7],
                updated_at=row[8],
            )

    async def search(
        self,
        query: str,
        workspace_root: str,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[SemanticMemoryEntry]:
        """FTS5 search with mandatory INNER JOIN enforcing workspace_root containment."""
        conn = await self.db.get_connection()
        clean_query = query.strip().replace('"', '""')
        if not clean_query:
            return []

        fts_match = f'"{clean_query}"'
        params: Dict[str, Any] = {
            "query": fts_match,
            "workspace_root": workspace_root,
            "limit": limit,
        }

        category_clause = ""
        if category:
            category_clause = "AND s.category = :category"
            params["category"] = category

        sql = f"""
            SELECT s.id, s.workspace_root, s.sensitivity, s.category, s.title, s.content,
                   s.source_session_id, s.created_at, s.updated_at
            FROM semantic_memory s
            JOIN semantic_memory_fts f ON s.rowid = f.rowid
            WHERE semantic_memory_fts MATCH :query
              AND s.workspace_root = :workspace_root
              {category_clause}
            ORDER BY rank
            LIMIT :limit
        """
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [
                SemanticMemoryEntry(
                    id=row[0],
                    workspace_root=row[1],
                    sensitivity=row[2],
                    category=row[3],
                    title=row[4],
                    content=row[5],
                    source_session_id=row[6],
                    created_at=row[7],
                    updated_at=row[8],
                )
                for row in rows
            ]

    async def delete(self, memory_id: str, workspace_root: str) -> bool:
        """Delete an entry by ID, strictly requiring workspace_root match."""
        conn = await self.db.get_connection()
        sql = "DELETE FROM semantic_memory WHERE id = :id AND workspace_root = :workspace_root"
        cursor = await conn.execute(sql, {"id": memory_id, "workspace_root": workspace_root})
        await conn.commit()
        return cursor.rowcount > 0
