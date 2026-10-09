"""Canonical Session Memory Manager with sqlite-vec and mutation routing.

Enforces:
1. Zero external network calls, cloud embeddings, or telemetry dependencies.
2. Canonical mutation routes: delete, rewind, replace, undo.
3. Stale-result fencing: tombstoned/rewound items never leak into query results.
4. Cold crash recovery: durable outbox catchup across restarts.
5. Async database hygiene with explicit close() teardown on Windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
import time
import uuid
from typing import Any

import aiosqlite

from friday.memory.vector import (
    LocalCpuEmbedder,
    MemoryItemModel,
    MemorySearchResult,
    MemorySourceModel,
    VectorMemory,
)
from friday.storage.db import DatabaseManager
from friday.storage.vector_db import (
    DEFAULT_DIMENSION,
    DEFAULT_EMBEDDING_VERSION,
    VectorDatabaseManager,
    pack_vector,
)

logger = logging.getLogger(__name__)


@dataclass
class MutationRecord:
    mutation_id: str
    action: str  # "delete", "rewind", "replace"
    target_id: str
    previous_state: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)


class SessionMemoryManager:
    """Manages canonical session memory mutations, stale-result fencing, and crash recovery."""

    def __init__(
        self,
        vector_db: VectorDatabaseManager,
        canonical_db: DatabaseManager | None = None,
        embedder: LocalCpuEmbedder | None = None,
    ) -> None:
        self.vector_db = vector_db
        self.canonical_db = canonical_db
        self.embedder = embedder or LocalCpuEmbedder()
        self.vector_memory = VectorMemory(
            vector_db=vector_db,
            canonical_db=canonical_db,
            embedder=self.embedder,
        )
        self._undo_stack: list[MutationRecord] = []

    async def initialize(self) -> None:
        """Initializes database schema and ensures WAL mode."""
        await self.vector_db.initialize()
        if self.canonical_db:
            await self.canonical_db.initialize()

    async def add_session_memory(
        self,
        session_id: str,
        message_id: str,
        text: str,
        profile: str = "default",
        workspace_root: str = "default_ws",
    ) -> str:
        """Adds a canonical session message fact to memory."""
        source = MemorySourceModel(
            profile=profile,
            kind="message",
            session_id=session_id,
            message_id=message_id,
            canonical_locator=f"session:{session_id}:msg:{message_id}",
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        item = MemoryItemModel(
            source_id=source.source_id,
            text=text,
            author_trust_label="trusted",
        )
        if self.canonical_db:
            conn = await self.canonical_db.get_connection()
            await conn.execute(
                """
                INSERT OR IGNORE INTO messages (id, session_id, role, content, created_at)
                VALUES (?, ?, 'user', ?, ?)
                """,
                (message_id, session_id, text, time.time()),
            )
            await conn.commit()

        await self.vector_memory.ingest(source, [item], auto_process_outbox=True)
        return item.item_id

    async def memory_delete(self, item_id: str) -> str:
        """memory.delete: Tombstones item, fences retrieval, records undo state."""
        db = await self.vector_db.get_connection()
        now = time.time()
        mutation_id = f"mut-del-{uuid.uuid4().hex[:8]}"

        # Query previous state
        async with db.execute(
            "SELECT item_id, source_id, text, tombstone, revision FROM memory_items WHERE item_id = ?",
            (item_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise KeyError(f"Memory item {item_id} not found")

        prev_state = {
            "item_id": row[0],
            "source_id": row[1],
            "text": row[2],
            "tombstone": row[3],
            "revision": row[4],
        }

        # Apply tombstone
        await db.execute(
            """
            UPDATE memory_items
            SET tombstone = 1, revision = revision + 1, updated_at = ?
            WHERE item_id = ?
            """,
            (now, item_id),
        )

        # Write to ingestion outbox
        event_id = str(uuid.uuid4())
        dedup_key = f"{item_id}:{int(now)}:delete"
        await db.execute(
            """
            INSERT INTO ingestion_outbox (
                event_id, source_id, revision, action, dedup_key, status, created_at, processed_at
            ) VALUES (?, ?, ?, 'delete', ?, 'completed', ?, ?)
            """,
            (event_id, prev_state["source_id"], prev_state["revision"] + 1, dedup_key, now, now),
        )
        await db.commit()

        self._undo_stack.append(
            MutationRecord(
                mutation_id=mutation_id,
                action="delete",
                target_id=item_id,
                previous_state=prev_state,
                timestamp=now,
            )
        )
        return mutation_id

    async def memory_rewind(self, session_id: str, valid_until_timestamp: float) -> int:
        """memory.rewind: Tombstones session items after timestamp (F02 Rewind Validity)."""
        db = await self.vector_db.get_connection()
        now = time.time()
        mutation_id = f"mut-rew-{uuid.uuid4().hex[:8]}"

        # Identify items to rewind
        sql = """
            SELECT mi.item_id, mi.source_id, mi.text, mi.tombstone, mi.revision
            FROM memory_items mi
            JOIN memory_sources ms ON mi.source_id = ms.source_id
            WHERE ms.session_id = ? AND mi.tombstone = 0 AND mi.created_at > ?
        """
        async with db.execute(sql, (session_id, valid_until_timestamp)) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return 0

        affected = 0
        for r in rows:
            prev_state = {
                "item_id": r[0],
                "source_id": r[1],
                "text": r[2],
                "tombstone": r[3],
                "revision": r[4],
            }
            await db.execute(
                "UPDATE memory_items SET tombstone = 1, revision = revision + 1, updated_at = ? WHERE item_id = ?",
                (now, r[0]),
            )
            self._undo_stack.append(
                MutationRecord(
                    mutation_id=mutation_id,
                    action="rewind",
                    target_id=r[0],
                    previous_state=prev_state,
                    timestamp=now,
                )
            )
            affected += 1

        # Outbox entry
        event_id = str(uuid.uuid4())
        dedup_key = f"rewind:{session_id}:{int(valid_until_timestamp)}"
        await db.execute(
            """
            INSERT INTO ingestion_outbox (
                event_id, source_id, revision, action, dedup_key, status, created_at, processed_at
            ) VALUES (?, ?, 1, 'rewind', ?, 'completed', ?, ?)
            """,
            (event_id, session_id, dedup_key, now, now),
        )
        await db.commit()
        return affected

    async def memory_replace(self, item_id: str, new_text: str) -> str:
        """memory.replace: Atomically updates text and vectors, increments revision, logs undo."""
        db = await self.vector_db.get_connection()
        now = time.time()
        mutation_id = f"mut-rep-{uuid.uuid4().hex[:8]}"

        async with db.execute(
            "SELECT item_id, source_id, text, tombstone, revision FROM memory_items WHERE item_id = ?",
            (item_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise KeyError(f"Memory item {item_id} not found")

        prev_state = {
            "item_id": row[0],
            "source_id": row[1],
            "text": row[2],
            "tombstone": row[3],
            "revision": row[4],
        }

        # Update text & revision
        await db.execute(
            """
            UPDATE memory_items
            SET text = ?, tombstone = 0, revision = revision + 1, updated_at = ?
            WHERE item_id = ?
            """,
            (new_text, now, item_id),
        )

        # Recompute embedding and update chunk vector
        active_gen = await self.vector_db.get_active_generation()
        chunk_id = f"{item_id}:c:0"
        vector = self.embedder.embed(new_text)
        vec_blob = pack_vector(vector)

        await db.execute("DELETE FROM memory_chunks WHERE item_id = ?", (item_id,))
        await db.execute(
            """
            INSERT INTO memory_chunks (
                chunk_id, item_id, ordinal, content_hash, extraction_version, token_count, text
            ) VALUES (?, ?, 0, ?, 1, ?, ?)
            """,
            (chunk_id, item_id, hashlib.sha256(new_text.encode("utf-8")).hexdigest(), len(new_text.split()), new_text),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO chunk_vectors (
                chunk_id, embedding_version, index_generation, vector
            ) VALUES (?, ?, ?, ?)
            """,
            (chunk_id, DEFAULT_EMBEDDING_VERSION, active_gen, vec_blob),
        )

        # Write outbox event
        event_id = str(uuid.uuid4())
        dedup_key = f"{item_id}:{prev_state['revision'] + 1}:replace"
        await db.execute(
            """
            INSERT INTO ingestion_outbox (
                event_id, source_id, revision, action, dedup_key, status, created_at, processed_at
            ) VALUES (?, ?, ?, 'replace', ?, 'completed', ?, ?)
            """,
            (event_id, prev_state["source_id"], prev_state["revision"] + 1, dedup_key, now, now),
        )

        if self.canonical_db:
            conn = await self.canonical_db.get_connection()
            async with db.execute("SELECT message_id FROM memory_sources WHERE source_id = ?", (prev_state["source_id"],)) as cur:
                m_row = await cur.fetchone()
                if m_row and m_row[0]:
                    await conn.execute("UPDATE messages SET content = ? WHERE id = ?", (new_text, m_row[0]))
                    await conn.commit()

        await db.commit()

        self._undo_stack.append(
            MutationRecord(
                mutation_id=mutation_id,
                action="replace",
                target_id=item_id,
                previous_state=prev_state,
                timestamp=now,
            )
        )
        return mutation_id

    async def memory_undo(self) -> str:
        """memory.undo: Inverts the most recent mutation from undo stack."""
        if not self._undo_stack:
            raise IndexError("No mutations to undo")

        last = self._undo_stack.pop()
        db = await self.vector_db.get_connection()
        now = time.time()
        prev = last.previous_state

        if not prev:
            raise ValueError(f"No previous state stored for mutation {last.mutation_id}")

        item_id = prev["item_id"]

        if last.action in ("delete", "rewind"):
            # Un-tombstone
            await db.execute(
                """
                UPDATE memory_items
                SET tombstone = ?, revision = revision + 1, updated_at = ?
                WHERE item_id = ?
                """,
                (prev["tombstone"], now, item_id),
            )
        elif last.action == "replace":
            # Revert text and re-embed
            old_text = prev["text"]
            await db.execute(
                """
                UPDATE memory_items
                SET text = ?, tombstone = ?, revision = revision + 1, updated_at = ?
                WHERE item_id = ?
                """,
                (old_text, prev["tombstone"], now, item_id),
            )
            active_gen = await self.vector_db.get_active_generation()
            chunk_id = f"{item_id}:c:0"
            vec_blob = pack_vector(self.embedder.embed(old_text))
            await db.execute("DELETE FROM memory_chunks WHERE item_id = ?", (item_id,))
            await db.execute(
                """
                INSERT INTO memory_chunks (
                    chunk_id, item_id, ordinal, content_hash, extraction_version, token_count, text
                ) VALUES (?, ?, 0, ?, 1, ?, ?)
                """,
                (chunk_id, item_id, hashlib.sha256(old_text.encode("utf-8")).hexdigest(), len(old_text.split()), old_text),
            )
            await db.execute(
                """
                INSERT OR REPLACE INTO chunk_vectors (
                    chunk_id, embedding_version, index_generation, vector
                ) VALUES (?, ?, ?, ?)
                """,
                (chunk_id, DEFAULT_EMBEDDING_VERSION, active_gen, vec_blob),
            )
            if self.canonical_db:
                conn = await self.canonical_db.get_connection()
                async with db.execute("SELECT message_id FROM memory_sources WHERE source_id = ?", (prev["source_id"],)) as cur:
                    m_row = await cur.fetchone()
                    if m_row and m_row[0]:
                        await conn.execute("UPDATE messages SET content = ? WHERE id = ?", (old_text, m_row[0]))
                        await conn.commit()

        await db.commit()
        return last.mutation_id

    async def search(
        self,
        query: str,
        profile: str = "default",
        top_k: int = 5,
        min_score: float = 0.0,
        workspace_root: str | None = None,
    ) -> list[MemorySearchResult]:
        """Search vector memory with Stale-Result Fencing."""
        return await self.vector_memory.search(
            query=query,
            profile=profile,
            top_k=top_k,
            min_score=min_score,
            workspace_root=workspace_root,
        )

    async def recover_from_crash(self) -> int:
        """Cold crash recovery: reconciles any pending outbox events across restarts."""
        db = await self.vector_db.get_connection()
        async with db.execute(
            "SELECT event_id, source_id, action FROM ingestion_outbox WHERE status = 'pending'"
        ) as cursor:
            pending = await cursor.fetchall()

        reconciled = 0
        now = time.time()
        for event_id, source_id, action in pending:
            if action in ("upsert", "replace"):
                await self.vector_memory.process_outbox_event(event_id, source_id)
            elif action == "delete":
                await db.execute("UPDATE memory_items SET tombstone = 1 WHERE source_id = ?", (source_id,))
                await db.execute("UPDATE ingestion_outbox SET status = 'completed', processed_at = ? WHERE event_id = ?", (now, event_id))
            reconciled += 1

        await db.commit()
        return reconciled

    async def close(self) -> None:
        """Closes all database handles."""
        await self.vector_db.close()
        if self.canonical_db:
            await self.canonical_db.close()
