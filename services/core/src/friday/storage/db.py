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

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
