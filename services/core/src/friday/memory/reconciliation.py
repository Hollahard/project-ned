"""F03 Outbox and recovery reconciliation engine for Project Friday.

Ensures:
- Idempotent processing of pending or failed ingestion outbox events.
- Cursor/high-watermark catchup scanner reconciling unindexed canonical commits after restart or crash.
- Deletion/tombstone synchronization when canonical records are pruned externally.
"""

import hashlib
import logging
import time
from typing import Any

import aiosqlite

from friday.memory.vector import (
    MemoryItemModel,
    MemorySourceModel,
    VectorMemory,
)
from friday.storage.db import DatabaseManager
from friday.storage.vector_db import VectorDatabaseManager

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """Reconciles canonical storage state and vector memory outbox idempotently."""

    def __init__(
        self,
        vector_db: VectorDatabaseManager,
        canonical_db: DatabaseManager,
        vector_memory: VectorMemory,
    ) -> None:
        self.vector_db = vector_db
        self.canonical_db = canonical_db
        self.vector_memory = vector_memory

    async def reconcile_outbox(self, max_batch: int = 100) -> int:
        """Process any pending or failed outbox events idempotently."""
        vdb = await self.vector_db.get_connection()
        async with vdb.execute(
            """
            SELECT event_id, source_id, action, dedup_key, attempts
            FROM ingestion_outbox
            WHERE status IN ('pending', 'failed')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max_batch,),
        ) as cursor:
            events = await cursor.fetchall()

        processed_count = 0
        for event_id, source_id, action, dedup_key, attempts in events:
            try:
                if action == "upsert":
                    await self.vector_memory.process_outbox_event(event_id, source_id)
                elif action == "delete":
                    await vdb.execute(
                        """
                        UPDATE memory_items SET tombstone = 1 WHERE source_id = ?
                        """,
                        (source_id,),
                    )
                    await vdb.execute(
                        """
                        UPDATE ingestion_outbox SET status = 'completed', processed_at = ? WHERE event_id = ?
                        """,
                        (time.time(), event_id),
                    )
                    await vdb.commit()
                elif action == "rewind":
                    await vdb.execute(
                        """
                        UPDATE ingestion_outbox SET status = 'completed', processed_at = ? WHERE event_id = ?
                        """,
                        (time.time(), event_id),
                    )
                    await vdb.commit()
                processed_count += 1
            except (aiosqlite.Error, ValueError, KeyError, RuntimeError, OSError) as e:
                logger.error("Error reconciling outbox event %s: %s", event_id, e)
                await vdb.execute(
                    """
                    UPDATE ingestion_outbox
                    SET attempts = attempts + 1, last_error = ?, status = 'failed'
                    WHERE event_id = ?
                    """,
                    (str(e), event_id),
                )
                await vdb.commit()

        return processed_count

    async def reconcile_canonical(
        self,
        profile: str = "default",
        workspace_root: str | None = None,
    ) -> dict[str, int]:
        """High-watermark scanner catching up unindexed canonical commits and pruned items."""
        # 1. First drain pending outbox events
        outbox_done = await self.reconcile_outbox()

        conn_can = await self.canonical_db.get_connection()
        conn_vec = await self.vector_db.get_connection()

        indexed_count = 0
        tombstoned_count = 0

        # 2. Reconcile canonical messages -> vector memory
        msg_sql = """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.working_directory
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
        """
        params: list[Any] = []
        if workspace_root:
            msg_sql += " WHERE s.working_directory = ?"
            params.append(workspace_root)

        async with conn_can.execute(msg_sql, params) as cursor:
            canonical_messages = await cursor.fetchall()

        canonical_msg_ids = set()
        for msg_id, sess_id, role, content, created_at, s_ws in canonical_messages:
            canonical_msg_ids.add(msg_id)
            source_id = f"msg:{msg_id}"

            # Check if already present in vector DB
            async with conn_vec.execute(
                "SELECT source_id, content_hash, deletion_generation FROM memory_sources WHERE source_id = ?",
                (source_id,),
            ) as v_cur:
                row = await v_cur.fetchone()

            c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if not row or (row[1] != c_hash and row[2] == 0):
                source = MemorySourceModel(
                    source_id=source_id,
                    profile=profile,
                    kind="message",
                    session_id=sess_id,
                    message_id=msg_id,
                    canonical_locator=f"messages:{msg_id}",
                    content_hash=c_hash,
                    created_at=created_at,
                )
                trust_label = "user" if role == "user" else "assistant"
                item = MemoryItemModel(
                    item_id=f"item:{source_id}",
                    source_id=source_id,
                    text=content,
                    author_trust_label=trust_label,
                    valid_from=created_at,
                    created_at=created_at,
                )
                await self.vector_memory.ingest(source, [item], auto_process_outbox=True)
                indexed_count += 1

        # 3. Reconcile canonical semantic_memory -> vector memory
        sem_sql = "SELECT id, workspace_root, title, content, created_at, updated_at FROM semantic_memory"
        sem_params: list[Any] = []
        if workspace_root:
            sem_sql += " WHERE workspace_root = ?"
            sem_params.append(workspace_root)

        async with conn_can.execute(sem_sql, sem_params) as cursor:
            canonical_semantics = await cursor.fetchall()

        canonical_sem_ids = set()
        for sem_id, ws, title, content, created_at, updated_at in canonical_semantics:
            canonical_sem_ids.add(sem_id)
            source_id = f"sem:{sem_id}"
            combined_text = f"{title}\n{content}"
            c_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()

            async with conn_vec.execute(
                "SELECT source_id, content_hash, deletion_generation FROM memory_sources WHERE source_id = ?",
                (source_id,),
            ) as v_cur:
                row = await v_cur.fetchone()

            if not row or (row[1] != c_hash and row[2] == 0):
                source = MemorySourceModel(
                    source_id=source_id,
                    profile=profile,
                    kind="semantic",
                    canonical_locator=f"semantic_memory:{sem_id}",
                    content_hash=c_hash,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                item = MemoryItemModel(
                    item_id=f"item:{source_id}",
                    source_id=source_id,
                    text=combined_text,
                    author_trust_label="system",
                    valid_from=created_at,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                await self.vector_memory.ingest(source, [item], auto_process_outbox=True)
                indexed_count += 1

        # 4. Deletion synchronization: Find vector sources whose canonical counterparts were deleted
        async with conn_vec.execute(
            """
            SELECT source_id, kind, message_id, canonical_locator
            FROM memory_sources
            WHERE profile = ? AND deletion_generation = 0
            """,
            (profile,),
        ) as cursor:
            active_sources = await cursor.fetchall()

        for s_id, s_kind, s_msg_id, s_locator in active_sources:
            if s_kind == "message" and s_msg_id and s_msg_id not in canonical_msg_ids:
                # Canonical message was deleted
                await self.vector_memory.forget(s_id)
                tombstoned_count += 1
            elif s_kind == "semantic" and s_locator.startswith("semantic_memory:"):
                sem_key = s_locator.split(":", 1)[1]
                if sem_key not in canonical_sem_ids:
                    # Canonical semantic entry was deleted
                    await self.vector_memory.forget(s_id)
                    tombstoned_count += 1

        # 5. Update index generation watermark
        now = time.time()
        active_gen = await self.vector_db.get_active_generation()
        async with conn_vec.execute("SELECT COUNT(*) FROM chunk_vectors WHERE index_generation = ?", (active_gen,)) as cursor:
            count = (await cursor.fetchone())[0]

        await conn_vec.execute(
            """
            UPDATE index_generations
            SET counts = ?, source_high_watermark = ?, updated_at = ?
            WHERE generation_id = ?
            """,
            (count, str(now), now, active_gen),
        )
        await conn_vec.commit()

        logger.info(
            "Reconciliation complete: %d indexed, %d tombstoned, %d outbox processed",
            indexed_count,
            tombstoned_count,
            outbox_done,
        )
        return {
            "indexed": indexed_count,
            "tombstoned": tombstoned_count,
            "outbox_processed": outbox_done,
        }
