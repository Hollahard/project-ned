"""SQLite WAL database manager for Friday."""

import logging
from pathlib import Path
import aiosqlite

logger = logging.getLogger(__name__)

INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    working_directory TEXT NOT NULL,
    model_profile TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls TEXT,
    tool_call_id TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS model_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    context_window INTEGER NOT NULL DEFAULT 32768,
    max_tokens INTEGER NOT NULL DEFAULT 4096,
    temperature REAL NOT NULL DEFAULT 0.7,
    top_p REAL NOT NULL DEFAULT 0.9,
    resident INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

-- Virtual table for FTS5 full text search
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='rowid'
);

-- Triggers to keep FTS index synchronized
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

-- Semantic Memory (Long-term persistent facts, preferences, domain knowledge)
CREATE TABLE IF NOT EXISTS semantic_memory (
    id TEXT PRIMARY KEY,
    workspace_root TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS semantic_memory_fts USING fts5(
    title,
    content,
    content='semantic_memory',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS semantic_memory_ai AFTER INSERT ON semantic_memory BEGIN
    INSERT INTO semantic_memory_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_memory_ad AFTER DELETE ON semantic_memory BEGIN
    INSERT INTO semantic_memory_fts(semantic_memory_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_memory_au AFTER UPDATE ON semantic_memory BEGIN
    INSERT INTO semantic_memory_fts(semantic_memory_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
    INSERT INTO semantic_memory_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;

-- Procedural Memory (Playbooks, recipes, reproduction workflows)
CREATE TABLE IF NOT EXISTS procedural_memory (
    id TEXT PRIMARY KEY,
    workspace_root TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    title TEXT NOT NULL,
    steps TEXT NOT NULL,
    source TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS procedural_memory_fts USING fts5(
    title,
    steps,
    source,
    content='procedural_memory',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS procedural_memory_ai AFTER INSERT ON procedural_memory BEGIN
    INSERT INTO procedural_memory_fts(rowid, title, steps, source) VALUES (new.rowid, new.title, new.steps, new.source);
END;

CREATE TRIGGER IF NOT EXISTS procedural_memory_ad AFTER DELETE ON procedural_memory BEGIN
    INSERT INTO procedural_memory_fts(procedural_memory_fts, rowid, title, steps, source) VALUES('delete', old.rowid, old.title, old.steps, old.source);
END;

CREATE TRIGGER IF NOT EXISTS procedural_memory_au AFTER UPDATE ON procedural_memory BEGIN
    INSERT INTO procedural_memory_fts(procedural_memory_fts, rowid, title, steps, source) VALUES('delete', old.rowid, old.title, old.steps, old.source);
    INSERT INTO procedural_memory_fts(rowid, title, steps, source) VALUES (new.rowid, new.title, new.steps, new.source);
END;

-- Skills Metadata (Phase 10: State lives in SQLite, never in the file)
CREATE TABLE IF NOT EXISTS skills_metadata (
    workspace_root TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    sensitive INTEGER NOT NULL DEFAULT 0,
    approved_tool_ids TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    PRIMARY KEY (workspace_root, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_skills_metadata_hash
    ON skills_metadata(content_hash);
"""


class DatabaseManager:
    """Manages SQLite database with WAL mode and asynchronous queries."""

    def __init__(self, db_path: Path | str = "state.db") -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open DB connection and execute migration scripts."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(INIT_SQL)
        await self._db.commit()
        logger.info("Initialized Friday SQLite storage at %s", self.db_path)

    async def get_connection(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def get_skill_metadata(self, workspace_root: str, skill_name: str) -> dict | None:
        """Retrieve skills_metadata record for a skill within a workspace."""
        db = await self.get_connection()
        async with db.execute(
            """
            SELECT workspace_root, skill_name, content_hash, approved, disabled, sensitive, approved_tool_ids, updated_at
            FROM skills_metadata
            WHERE workspace_root = ? AND skill_name = ?
            """,
            (workspace_root, skill_name),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            import json
            return {
                "workspace_root": row[0],
                "skill_name": row[1],
                "content_hash": row[2],
                "approved": bool(row[3]),
                "disabled": bool(row[4]),
                "sensitive": bool(row[5]),
                "approved_tool_ids": json.loads(row[6]),
                "updated_at": row[7],
            }

    async def set_skill_approval(
        self,
        workspace_root: str,
        skill_name: str,
        content_hash: str,
        approved_tool_ids: list[str],
        sensitive: bool = False,
    ) -> None:
        """UI transaction: approve a specific content hash and checked tools.
        
        The only writer of approved=1 is this UI transaction that verified the modal hash.
        """
        import json
        import time
        db = await self.get_connection()
        now = time.time()
        await db.execute(
            """
            INSERT INTO skills_metadata (workspace_root, skill_name, content_hash, approved, disabled, sensitive, approved_tool_ids, updated_at)
            VALUES (?, ?, ?, 1, 0, ?, ?, ?)
            ON CONFLICT(workspace_root, skill_name) DO UPDATE SET
                content_hash = excluded.content_hash,
                approved = 1,
                sensitive = excluded.sensitive,
                approved_tool_ids = excluded.approved_tool_ids,
                updated_at = excluded.updated_at
            """,
            (workspace_root, skill_name, content_hash, int(sensitive), json.dumps(approved_tool_ids), now),
        )
        await db.commit()

    async def invalidate_skill_approval(self, workspace_root: str, skill_name: str) -> None:
        """Invalidate approval upon hash drift or external modifications."""
        import time
        db = await self.get_connection()
        await db.execute(
            """
            UPDATE skills_metadata
            SET approved = 0, approved_tool_ids = '[]', updated_at = ?
            WHERE workspace_root = ? AND skill_name = ?
            """,
            (time.time(), workspace_root, skill_name),
        )
        await db.commit()

    async def set_skill_disabled(self, workspace_root: str, skill_name: str, disabled: bool) -> None:
        """Desktop UI toggle to disable/enable skill."""
        import time
        db = await self.get_connection()
        await db.execute(
            """
            UPDATE skills_metadata
            SET disabled = ?, updated_at = ?
            WHERE workspace_root = ? AND skill_name = ?
            """,
            (int(disabled), time.time(), workspace_root, skill_name),
        )
        await db.commit()

    async def upsert_inert_skill(self, workspace_root: str, skill_name: str, content_hash: str) -> None:
        """Record an unapproved skill seen on disk. Never sets approved=1."""
        import time
        db = await self.get_connection()
        await db.execute(
            """
            INSERT INTO skills_metadata (workspace_root, skill_name, content_hash, approved, disabled, sensitive, approved_tool_ids, updated_at)
            VALUES (?, ?, ?, 0, 0, 0, '[]', ?)
            ON CONFLICT(workspace_root, skill_name) DO UPDATE SET
                content_hash = excluded.content_hash,
                updated_at = excluded.updated_at
            WHERE skills_metadata.content_hash != excluded.content_hash
            """,
            (workspace_root, skill_name, content_hash, time.time()),
        )
        await db.commit()

    async def delete_skill_metadata(self, workspace_root: str, skill_name: str) -> None:
        """Remove skills_metadata record when skill is deleted."""
        db = await self.get_connection()
        await db.execute(
            "DELETE FROM skills_metadata WHERE workspace_root = ? AND skill_name = ?",
            (workspace_root, skill_name),
        )
        await db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
