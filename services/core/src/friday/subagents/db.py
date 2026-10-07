"""SQLite persistence and budget accounting for Friday Subagents (Phase 12 Milestone 2).

Invariants:
1. SQLite WAL mode with synchronous=FULL/NORMAL, foreign keys enabled, busy timeout 5000ms.
2. Single terminal state guarantee: runs entering terminal states cannot be transitioned back.
3. Atomic reservation: token budget reserved upon admission, reconciled on completion.
4. Concurrency cap: max active subagents per parent session strictly bounded.
5. Crash recovery: orphaned non-terminal runs marked INTERRUPTED on startup.
6. Summary truncation: summaries capped at 64 KiB during persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid
import aiosqlite

from friday.subagents.models import (
    TERMINAL_STATES,
    VALID_SUBAGENT_TRANSITIONS,
    InvalidStateTransitionError,
    PolicyDeniedError,
    SubagentRunState,
    SubagentSpec,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS subagent_runs (
    id TEXT PRIMARY KEY,
    parent_session_id TEXT NOT NULL,
    parent_turn_id TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL,
    task_prompt TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'running',
    reserved_tokens INTEGER NOT NULL,
    consumed_tokens INTEGER NOT NULL DEFAULT 0,
    tool_calls_count INTEGER NOT NULL DEFAULT 0,
    started_at_utc REAL NOT NULL,
    completed_at_utc REAL,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,
    quiescence_confirmed INTEGER NOT NULL DEFAULT 0,
    output_summary TEXT,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent
    ON subagent_runs(parent_session_id, started_at_utc);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_active
    ON subagent_runs(state)
    WHERE state IN ('running', 'stopping');
"""

MAX_SUMMARY_BYTES = 65536  # 64 KiB cap


def _truncate_summary(text: Optional[str]) -> Optional[str]:
    """Ensure summary text does not exceed 64 KiB."""
    if not text:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_SUMMARY_BYTES:
        truncated_bytes = encoded[: MAX_SUMMARY_BYTES - 64]
        return truncated_bytes.decode("utf-8", errors="ignore") + "\n... [TRUNCATED 64 KiB]"
    return text


class SubagentDatabaseManager:
    """Manages transactional state persistence and budget accounting for subagents."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize database connection, apply WAL mode and migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.execute("PRAGMA busy_timeout=5000;")

        async with self._lock:
            await self._conn.executescript(INIT_SQL)
            async with self._conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await self._conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?)",
                        (SCHEMA_VERSION, time.time()),
                    )
        logger.info("SubagentDatabaseManager initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close database connection cleanly."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SubagentDatabaseManager closed.")

    async def reserve_subagent_run(
        self,
        spec: SubagentSpec,
        max_concurrency: int = 3,
        run_id: Optional[str] = None,
    ) -> str:
        """Atomically admit a subagent run, enforcing concurrency limits and token reservation."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        assigned_id = run_id or str(uuid.uuid4())
        now = time.time()
        spec_json = spec.model_dump_json()

        async with self._lock:
            # Check concurrency limit for parent session
            async with self._conn.execute(
                "SELECT COUNT(*) FROM subagent_runs WHERE parent_session_id = ? AND state IN ('running', 'stopping')",
                (spec.parent_session_id,),
            ) as cursor:
                count_row = await cursor.fetchone()
                active_count = count_row[0] if count_row else 0
                if active_count >= max_concurrency:
                    raise PolicyDeniedError(
                        f"Subagent concurrency limit reached for session {spec.parent_session_id} "
                        f"({active_count}/{max_concurrency} active runs)."
                    )

            # Insert new run record in RUNNING state
            await self._conn.execute(
                """
                INSERT INTO subagent_runs (
                    id, parent_session_id, parent_turn_id, depth, role, task_prompt,
                    spec_json, state, reserved_tokens, consumed_tokens, tool_calls_count,
                    started_at_utc, completed_at_utc, cancellation_requested, quiescence_confirmed,
                    output_summary, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, NULL, 0, 0, NULL, NULL)
                """,
                (
                    assigned_id,
                    spec.parent_session_id,
                    spec.parent_turn_id,
                    spec.depth,
                    spec.role,
                    spec.task_prompt,
                    spec_json,
                    SubagentRunState.RUNNING.value,
                    spec.token_budget,
                    now,
                ),
            )

        logger.info(
            "Admitted subagent run %s (role='%s', reserved_tokens=%d)",
            assigned_id,
            spec.role,
            spec.token_budget,
        )
        return assigned_id

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a subagent run record by ID."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        async with self._conn.execute(
            """
            SELECT id, parent_session_id, parent_turn_id, depth, role, task_prompt,
                   spec_json, state, reserved_tokens, consumed_tokens, tool_calls_count,
                   started_at_utc, completed_at_utc, cancellation_requested, quiescence_confirmed,
                   output_summary, error_summary
            FROM subagent_runs WHERE id = ?
            """,
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "parent_session_id": row[1],
                "parent_turn_id": row[2],
                "depth": row[3],
                "role": row[4],
                "task_prompt": row[5],
                "spec_json": row[6],
                "state": SubagentRunState(row[7]),
                "reserved_tokens": row[8],
                "consumed_tokens": row[9],
                "tool_calls_count": row[10],
                "started_at_utc": row[11],
                "completed_at_utc": row[12],
                "cancellation_requested": bool(row[13]),
                "quiescence_confirmed": bool(row[14]),
                "output_summary": row[15],
                "error_summary": row[16],
            }

    async def list_runs_for_session(self, parent_session_id: str) -> List[Dict[str, Any]]:
        """List all subagent runs associated with a parent session."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        async with self._conn.execute(
            """
            SELECT id, parent_session_id, parent_turn_id, depth, role, task_prompt,
                   spec_json, state, reserved_tokens, consumed_tokens, tool_calls_count,
                   started_at_utc, completed_at_utc, cancellation_requested, quiescence_confirmed,
                   output_summary, error_summary
            FROM subagent_runs WHERE parent_session_id = ?
            ORDER BY started_at_utc ASC
            """,
            (parent_session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row[0],
                        "parent_session_id": row[1],
                        "parent_turn_id": row[2],
                        "depth": row[3],
                        "role": row[4],
                        "task_prompt": row[5],
                        "spec_json": row[6],
                        "state": SubagentRunState(row[7]),
                        "reserved_tokens": row[8],
                        "consumed_tokens": row[9],
                        "tool_calls_count": row[10],
                        "started_at_utc": row[11],
                        "completed_at_utc": row[12],
                        "cancellation_requested": bool(row[13]),
                        "quiescence_confirmed": bool(row[14]),
                        "output_summary": row[15],
                        "error_summary": row[16],
                    }
                )
            return results

    async def list_active_runs(self) -> List[Dict[str, Any]]:
        """List all currently active runs (running or stopping)."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        async with self._conn.execute(
            """
            SELECT id, parent_session_id, parent_turn_id, depth, role, task_prompt,
                   spec_json, state, reserved_tokens, consumed_tokens, tool_calls_count,
                   started_at_utc, completed_at_utc, cancellation_requested, quiescence_confirmed,
                   output_summary, error_summary
            FROM subagent_runs WHERE state IN ('running', 'stopping')
            ORDER BY started_at_utc ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row[0],
                        "parent_session_id": row[1],
                        "parent_turn_id": row[2],
                        "depth": row[3],
                        "role": row[4],
                        "task_prompt": row[5],
                        "spec_json": row[6],
                        "state": SubagentRunState(row[7]),
                        "reserved_tokens": row[8],
                        "consumed_tokens": row[9],
                        "tool_calls_count": row[10],
                        "started_at_utc": row[11],
                        "completed_at_utc": row[12],
                        "cancellation_requested": bool(row[13]),
                        "quiescence_confirmed": bool(row[14]),
                        "output_summary": row[15],
                        "error_summary": row[16],
                    }
                )
            return results

    async def request_cancellation(self, run_id: str) -> bool:
        """Mark cancellation requested and transition state to STOPPING if RUNNING."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        async with self._lock:
            run = await self.get_run(run_id)
            if not run:
                return False

            current_state = run["state"]
            if current_state in TERMINAL_STATES:
                logger.info("Run %s already in terminal state %s; cannot cancel", run_id, current_state)
                return False

            await self._conn.execute(
                """
                UPDATE subagent_runs
                SET cancellation_requested = 1, state = ?
                WHERE id = ? AND state = ?
                """,
                (SubagentRunState.STOPPING.value, run_id, SubagentRunState.RUNNING.value),
            )
            return True

    async def complete_subagent_run(
        self,
        run_id: str,
        state: SubagentRunState,
        consumed_tokens: int,
        tool_calls_count: int,
        output_summary: Optional[str] = None,
        error_summary: Optional[str] = None,
        quiescence_confirmed: bool = True,
    ) -> bool:
        """Transition run into a terminal state with reconciled tokens and bounded summary.
        
        Enforces single terminal state guarantee.
        """
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        if state not in TERMINAL_STATES:
            raise ValueError(f"Target state {state} is not a terminal state.")

        trunc_output = _truncate_summary(output_summary)
        trunc_error = _truncate_summary(error_summary)
        now = time.time()

        async with self._lock:
            run = await self.get_run(run_id)
            if not run:
                raise KeyError(f"Run {run_id} not found.")

            current_state = run["state"]
            if current_state in TERMINAL_STATES:
                # Single terminal state guarantee: cannot transition away from terminal state
                raise InvalidStateTransitionError(
                    f"Illegal state transition: run {run_id} already in terminal state {current_state}."
                )

            valid_targets = VALID_SUBAGENT_TRANSITIONS.get(current_state, set())
            if state not in valid_targets:
                raise InvalidStateTransitionError(
                    f"Invalid transition from {current_state} to {state} for run {run_id}."
                )

            await self._conn.execute(
                """
                UPDATE subagent_runs
                SET state = ?,
                    consumed_tokens = ?,
                    tool_calls_count = ?,
                    completed_at_utc = ?,
                    quiescence_confirmed = ?,
                    output_summary = ?,
                    error_summary = ?
                WHERE id = ?
                """,
                (
                    state.value,
                    consumed_tokens,
                    tool_calls_count,
                    now,
                    1 if quiescence_confirmed else 0,
                    trunc_output,
                    trunc_error,
                    run_id,
                ),
            )

        logger.info(
            "Subagent run %s transitioned %s -> %s (consumed_tokens=%d)",
            run_id,
            current_state.value,
            state.value,
            consumed_tokens,
        )
        return True

    async def recover_abandoned_runs(self) -> int:
        """Scan for non-terminal runs after restart/crash and transition to INTERRUPTED."""
        if not self._conn:
            raise RuntimeError("Database not initialized.")

        now = time.time()
        async with self._lock:
            async with self._conn.execute(
                "SELECT id, state FROM subagent_runs WHERE state IN ('running', 'stopping')"
            ) as cursor:
                active_rows = await cursor.fetchall()

            if not active_rows:
                return 0

            count = len(active_rows)
            for row in active_rows:
                run_id = row[0]
                await self._conn.execute(
                    """
                    UPDATE subagent_runs
                    SET state = ?,
                        completed_at_utc = ?,
                        quiescence_confirmed = 1,
                        error_summary = 'Subagent interrupted by system restart or unexpected crash.'
                    WHERE id = ?
                    """,
                    (SubagentRunState.INTERRUPTED.value, now, run_id),
                )
            logger.warning("Recovered %d orphaned subagent runs to INTERRUPTED state", count)
            return count
