"""SQLite WAL vector memory database manager for Project Friday.

Supports profile-scoped vector storage with WAL mode, exact schema per Architecture Spec § 10,
and dual-engine retrieval: sqlite-vec (vec0) when available with pure-Python cosine similarity fallback.
"""

import json
import logging
import math
import struct
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

INIT_VECTOR_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

-- 1. Memory Sources: Provenance roots (sessions, messages, documents, semantic facts)
CREATE TABLE IF NOT EXISTS memory_sources (
    source_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL DEFAULT 'default',
    kind TEXT NOT NULL,
    session_id TEXT,
    message_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    canonical_locator TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    retention_policy TEXT NOT NULL DEFAULT 'standard',
    deletion_generation INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_sources_profile ON memory_sources(profile);
CREATE INDEX IF NOT EXISTS idx_memory_sources_session ON memory_sources(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_message ON memory_sources(message_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_locator ON memory_sources(canonical_locator);

-- 2. Memory Items: Discrete atomic facts or knowledge units extracted from sources
CREATE TABLE IF NOT EXISTS memory_items (
    item_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES memory_sources(source_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    provenance_span TEXT,
    author_trust_label TEXT NOT NULL DEFAULT 'untrusted',
    valid_from REAL,
    valid_to REAL,
    tombstone INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_source ON memory_items(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_items_tombstone ON memory_items(tombstone);

-- 3. Memory Chunks: Normalized, tokenized windows of text for embedding
CREATE TABLE IF NOT EXISTS memory_chunks (
    chunk_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES memory_items(item_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_version INTEGER NOT NULL DEFAULT 1,
    token_count INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_chunks_item ON memory_chunks(item_id);

-- 4. Embedding Versions: Pinned embedding model metadata and dimensionality
CREATE TABLE IF NOT EXISTS embedding_versions (
    version_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    metric TEXT NOT NULL DEFAULT 'cosine',
    normalization TEXT NOT NULL DEFAULT 'l2',
    runtime_fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- 5. Chunk Vectors: Serialized dense embedding vectors
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id TEXT NOT NULL REFERENCES memory_chunks(chunk_id) ON DELETE CASCADE,
    embedding_version TEXT NOT NULL REFERENCES embedding_versions(version_id) ON DELETE CASCADE,
    index_generation TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (chunk_id, embedding_version, index_generation)
);

CREATE INDEX IF NOT EXISTS idx_chunk_vectors_gen ON chunk_vectors(index_generation);

-- 6. Ingestion Outbox: Durable, transactional event log for asynchronous indexing
CREATE TABLE IF NOT EXISTS ingestion_outbox (
    event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    action TEXT NOT NULL,
    dedup_key TEXT UNIQUE NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    payload TEXT,
    created_at REAL NOT NULL,
    processed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_ingestion_outbox_status ON ingestion_outbox(status);

-- 7. Retrieval Audit: Access and recall telemetry without persisting raw secrets
CREATE TABLE IF NOT EXISTS retrieval_audit (
    audit_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    item_ids TEXT NOT NULL,
    scores TEXT NOT NULL,
    index_generation TEXT NOT NULL,
    created_at REAL NOT NULL,
    query_hash TEXT
);

-- 8. Index Generations: Vector index generation tracking and watermark management
CREATE TABLE IF NOT EXISTS index_generations (
    generation_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'active',
    counts INTEGER NOT NULL DEFAULT 0,
    checksum TEXT,
    source_high_watermark TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- Virtual table for FTS5 chunk search
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='memory_chunks',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON memory_chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON memory_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
END;
"""

DEFAULT_EMBEDDING_VERSION = "local-cpu-v1"
DEFAULT_MODEL_ID = "friday-local-cpu-128"
DEFAULT_DIMENSION = 128
DEFAULT_GENERATION_ID = "gen-0001"


def pack_vector(vector: list[float]) -> bytes:
    """Pack float array into little-endian 32-bit float bytes."""
    return struct.pack(f"{len(vector)}f", *vector)


def unpack_vector(data: bytes) -> list[float]:
    """Unpack float array from little-endian 32-bit float bytes."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors in pure Python."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class VectorDatabaseManager:
    """Manages profile-scoped SQLite vector memory database with WAL mode and asynchronous queries."""

    def __init__(self, db_path: Path | str = "vector_memory.db") -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self.has_sqlite_vec: bool = False

    async def initialize(self) -> None:
        """Open DB connection, set pragmas, run schema migration, and probe sqlite-vec extension."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)

        # Attempt to load sqlite-vec extension if installed
        try:
            import sqlite_vec
            await self._db.enable_load_extension(True)
            # aiosqlite wraps sqlite3 connection
            sqlite_vec.load(self._db._connection)
            self.has_sqlite_vec = True
            logger.info("Loaded sqlite-vec C extension successfully")
        except (ImportError, aiosqlite.Error, AttributeError, RuntimeError, OSError) as exc:
            self.has_sqlite_vec = False
            logger.debug("sqlite-vec C extension not available, using pure-python vector fallback: %s", exc)

        await self._db.executescript(INIT_VECTOR_SQL)

        # If sqlite-vec is available, ensure vec0 table exists
        if self.has_sqlite_vec:
            try:
                await self._db.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                    f"chunk_id text primary key, "
                    f"embedding float[{DEFAULT_DIMENSION}]"
                    f");"
                )
            except (aiosqlite.Error, RuntimeError) as e:
                logger.warning("Could not initialize vec0 virtual table: %s", e)
                self.has_sqlite_vec = False

        # Seed default embedding version and default active generation
        now = time.time()
        await self._db.execute(
            """
            INSERT OR IGNORE INTO embedding_versions (
                version_id, model_id, dimension, metric, normalization, runtime_fingerprint, created_at
            ) VALUES (?, ?, ?, 'cosine', 'l2', 'sha256:local_cpu_128_v1', ?)
            """,
            (DEFAULT_EMBEDDING_VERSION, DEFAULT_MODEL_ID, DEFAULT_DIMENSION, now),
        )

        await self._db.execute(
            """
            INSERT OR IGNORE INTO index_generations (
                generation_id, state, counts, checksum, source_high_watermark, schema_version, created_at, updated_at
            ) VALUES (?, 'active', 0, 'sha256:genesis', '0', 1, ?, ?)
            """,
            (DEFAULT_GENERATION_ID, now, now),
        )

        await self._db.commit()
        logger.info("Initialized Friday SQLite vector storage at %s (sqlite-vec=%s)", self.db_path, self.has_sqlite_vec)

    async def get_connection(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def get_active_generation(self) -> str:
        """Retrieve current active index generation ID."""
        db = await self.get_connection()
        async with db.execute(
            "SELECT generation_id FROM index_generations WHERE state = 'active' ORDER BY created_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return DEFAULT_GENERATION_ID

    async def search_vectors(
        self,
        query_vector: list[float],
        profile: str = "default",
        top_k: int = 5,
        min_score: float = 0.0,
        generation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Exact cosine similarity KNN search with profile filtering and tombstone exclusion."""
        db = await self.get_connection()
        active_gen = generation_id or await self.get_active_generation()

        # Query all candidate chunks for the profile and generation where source/item are valid
        sql = """
            SELECT 
                cv.chunk_id,
                cv.vector,
                mc.text AS chunk_text,
                mc.ordinal,
                mi.item_id,
                mi.text AS item_text,
                mi.provenance_span,
                mi.author_trust_label,
                mi.valid_from,
                mi.valid_to,
                ms.source_id,
                ms.kind AS source_kind,
                ms.profile,
                ms.session_id,
                ms.message_id,
                ms.canonical_locator,
                ms.revision,
                ms.deletion_generation
            FROM chunk_vectors cv
            JOIN memory_chunks mc ON cv.chunk_id = mc.chunk_id
            JOIN memory_items mi ON mc.item_id = mi.item_id
            JOIN memory_sources ms ON mi.source_id = ms.source_id
            WHERE ms.profile = ?
              AND cv.index_generation = ?
              AND mi.tombstone = 0
              AND ms.deletion_generation = 0
        """
        async with db.execute(sql, (profile, active_gen)) as cursor:
            rows = await cursor.fetchall()

        candidates: list[dict[str, Any]] = []
        for row in rows:
            chunk_id = row[0]
            raw_blob = row[1]
            chunk_vec = unpack_vector(raw_blob)
            score = cosine_similarity(query_vector, chunk_vec)
            if score >= min_score:
                candidates.append({
                    "chunk_id": chunk_id,
                    "score": score,
                    "text": row[2],
                    "ordinal": row[3],
                    "item_id": row[4],
                    "item_text": row[5],
                    "provenance_span": row[6],
                    "author_trust_label": row[7],
                    "valid_from": row[8],
                    "valid_to": row[9],
                    "source_id": row[10],
                    "source_kind": row[11],
                    "profile": row[12],
                    "session_id": row[13],
                    "message_id": row[14],
                    "canonical_locator": row[15],
                    "revision": row[16],
                    "deletion_generation": row[17],
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    async def search_chunks_fts(
        self,
        query: str,
        profile: str = "default",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memory chunks using SQLite FTS5."""
        db = await self.get_connection()
        clean_query = query.strip().replace('"', '""')
        if not clean_query:
            return []
        fts_match = f'"{clean_query}"'

        sql = """
            SELECT 
                mc.chunk_id,
                mc.text AS chunk_text,
                mc.ordinal,
                mi.item_id,
                mi.text AS item_text,
                mi.author_trust_label,
                ms.source_id,
                ms.kind AS source_kind,
                ms.profile,
                ms.session_id,
                ms.message_id,
                ms.canonical_locator
            FROM memory_chunks mc
            JOIN memory_items mi ON mc.item_id = mi.item_id
            JOIN memory_sources ms ON mi.source_id = ms.source_id
            JOIN chunks_fts f ON mc.rowid = f.rowid
            WHERE chunks_fts MATCH ?
              AND ms.profile = ?
              AND mi.tombstone = 0
              AND ms.deletion_generation = 0
            LIMIT ?
        """
        async with db.execute(sql, (fts_match, profile, limit)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "chunk_id": r[0],
                    "text": r[1],
                    "ordinal": r[2],
                    "item_id": r[3],
                    "item_text": r[4],
                    "author_trust_label": r[5],
                    "source_id": r[6],
                    "source_kind": r[7],
                    "profile": r[8],
                    "session_id": r[9],
                    "message_id": r[10],
                    "canonical_locator": r[11],
                    "score": 1.0,
                }
                for r in rows
            ]

    async def record_audit(
        self,
        request_id: str,
        item_ids: list[str],
        scores: list[float],
        index_generation: str,
        query_hash: str = "",
    ) -> str:
        """Persist retrieval audit record."""
        db = await self.get_connection()
        audit_id = str(uuid.uuid4())
        now = time.time()
        await db.execute(
            """
            INSERT INTO retrieval_audit (
                audit_id, request_id, item_ids, scores, index_generation, created_at, query_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                request_id,
                json.dumps(item_ids),
                json.dumps(scores),
                index_generation,
                now,
                query_hash,
            ),
        )
        await db.commit()
        return audit_id

    async def close(self) -> None:
        """Close DB connection cleanly."""
        if self._db:
            await self._db.close()
            self._db = None
