from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiosqlite

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

INIT_MIGRATION_V1 = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    cron_expression TEXT,
    delay_seconds INTEGER,
    timezone TEXT NOT NULL DEFAULT 'America/New_York',
    next_run_at_utc INTEGER,
    last_run_at_utc INTEGER,
    state TEXT NOT NULL DEFAULT 'active',
    pause_reason TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    max_runs INTEGER,
    watermark_utc INTEGER,
    permission_snapshot TEXT NOT NULL,
    approval_digest TEXT,
    created_at_utc INTEGER NOT NULL,
    updated_at_utc INTEGER NOT NULL,
    deleted_at_utc INTEGER,
    idempotency_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_claim
    ON scheduled_jobs(state, next_run_at_utc)
    WHERE state = 'active' AND deleted_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_workspace
    ON scheduled_jobs(workspace_root, state);

CREATE TABLE IF NOT EXISTS job_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
    scheduled_for_utc INTEGER NOT NULL,
    state TEXT NOT NULL,
    owner_instance TEXT NOT NULL,
    ownership_generation INTEGER NOT NULL DEFAULT 1,
    lease_expires_at_utc INTEGER NOT NULL,
    started_at_utc INTEGER NOT NULL,
    completed_at_utc INTEGER,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,
    quiescence_confirmed INTEGER NOT NULL DEFAULT 0,
    outcome_certain INTEGER NOT NULL DEFAULT 1,
    reserved_tokens INTEGER NOT NULL DEFAULT 8000,
    consumed_tokens INTEGER NOT NULL DEFAULT 0,
    output_summary TEXT,
    error_summary TEXT,
    UNIQUE(job_id, scheduled_for_utc)
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job
    ON job_runs(job_id, started_at_utc);

CREATE INDEX IF NOT EXISTS idx_job_runs_active
    ON job_runs(state)
    WHERE state IN ('running', 'stopping');

CREATE TABLE IF NOT EXISTS scheduler_quota_usage (
    accounting_day_utc TEXT NOT NULL,
    scope TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL DEFAULT 0,
    consumed_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (accounting_day_utc, scope, scope_id)
);

CREATE TABLE IF NOT EXISTS scheduler_events (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    run_id TEXT,
    timestamp_utc INTEGER NOT NULL,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    details TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduler_events_job
    ON scheduler_events(job_id, timestamp_utc);
"""


class SchedulerDatabaseManager:
    """Manages dedicated scheduler.db with WAL mode, synchronous=FULL, and migrations."""

    def __init__(self, db_path: Path | str = "scheduler.db") -> None:
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def initialize(self) -> None:
        """Connect to SQLite, configure pragmas, and run migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        # Configure connection pragmas
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=FULL;")
        await self._db.execute("PRAGMA foreign_keys=ON;")
        await self._db.execute("PRAGMA busy_timeout=5000;")

        # Apply schema migrations
        await self._db.executescript(INIT_MIGRATION_V1)
        await self._db.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, applied_at_utc)
            VALUES (?, unixepoch())
            """,
            (CURRENT_SCHEMA_VERSION,),
        )
        await self._db.commit()
        logger.info("Initialized Friday Scheduler database at %s (v%d)", self.db_path, CURRENT_SCHEMA_VERSION)

    async def get_connection(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    def _row_to_job(self, row: Any) -> ScheduledJob:
        from friday.scheduler.models import JobPermissionSnapshot, ScheduledJob, ScheduleState, ScheduleType
        return ScheduledJob(
            id=row["id"],
            session_id=row["session_id"],
            workspace_root=row["workspace_root"],
            title=row["title"],
            prompt=row["prompt"],
            schedule_type=ScheduleType(row["schedule_type"]),
            cron_expression=row["cron_expression"],
            delay_seconds=row["delay_seconds"],
            timezone=row["timezone"],
            next_run_at_utc=row["next_run_at_utc"],
            last_run_at_utc=row["last_run_at_utc"],
            state=ScheduleState(row["state"]),
            pause_reason=row["pause_reason"],
            run_count=row["run_count"],
            max_runs=row["max_runs"],
            watermark_utc=row["watermark_utc"],
            permission_snapshot=JobPermissionSnapshot.model_validate_json(row["permission_snapshot"]),
            approval_digest=row["approval_digest"],
            created_at_utc=row["created_at_utc"],
            updated_at_utc=row["updated_at_utc"],
            deleted_at_utc=row["deleted_at_utc"],
            idempotency_key=row["idempotency_key"],
        )

    def _row_to_run(self, row: Any) -> JobRun:
        from friday.scheduler.models import JobRun, RunState
        return JobRun(
            id=row["id"],
            job_id=row["job_id"],
            scheduled_for_utc=row["scheduled_for_utc"],
            state=RunState(row["state"]),
            owner_instance=row["owner_instance"],
            ownership_generation=row["ownership_generation"],
            lease_expires_at_utc=row["lease_expires_at_utc"],
            started_at_utc=row["started_at_utc"],
            completed_at_utc=row["completed_at_utc"],
            cancellation_requested=bool(row["cancellation_requested"]),
            quiescence_confirmed=bool(row["quiescence_confirmed"]),
            outcome_certain=bool(row["outcome_certain"]),
            reserved_tokens=row["reserved_tokens"],
            consumed_tokens=row["consumed_tokens"],
            output_summary=row["output_summary"],
            error_summary=row["error_summary"],
        )

    async def create_job(self, job: "ScheduledJob") -> "ScheduledJob":
        """Persist a new validated, authorized scheduled job."""
        from friday.scheduler.models import SchedulerError
        conn = await self.get_connection()
        if job.idempotency_key:
            async with conn.execute(
                "SELECT * FROM scheduled_jobs WHERE idempotency_key = ?", (job.idempotency_key,)
            ) as cur:
                existing = await cur.fetchone()
                if existing:
                    return self._row_to_job(existing)

        snapshot_json = job.permission_snapshot.model_dump_json()
        await conn.execute(
            """
            INSERT INTO scheduled_jobs (
                id, session_id, workspace_root, title, prompt, schedule_type,
                cron_expression, delay_seconds, timezone, next_run_at_utc,
                last_run_at_utc, state, pause_reason, run_count, max_runs,
                watermark_utc, permission_snapshot, approval_digest,
                created_at_utc, updated_at_utc, deleted_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id, job.session_id, job.workspace_root, job.title, job.prompt,
                job.schedule_type.value, job.cron_expression, job.delay_seconds, job.timezone,
                job.next_run_at_utc, job.last_run_at_utc, job.state.value, job.pause_reason,
                job.run_count, job.max_runs, job.watermark_utc, snapshot_json,
                job.approval_digest, job.created_at_utc, job.updated_at_utc,
                job.deleted_at_utc, job.idempotency_key,
            ),
        )
        await conn.execute(
            """
            INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
            VALUES (hex(randomblob(16)), ?, NULL, unixepoch(), 'user', 'job_created', 'created', ?)
            """,
            (job.id, json.dumps({"title": job.title, "schedule_type": job.schedule_type.value})),
        )
        await conn.commit()
        return job

    async def get_job(self, job_id: str) -> Optional["ScheduledJob"]:
        conn = await self.get_connection()
        async with conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    async def list_jobs(
        self, workspace_root: Optional[str] = None, state: Optional[str] = None
    ) -> List["ScheduledJob"]:
        conn = await self.get_connection()
        query = "SELECT * FROM scheduled_jobs WHERE deleted_at_utc IS NULL"
        params: List[Any] = []
        if workspace_root:
            query += " AND workspace_root = ?"
            params.append(workspace_root)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY next_run_at_utc ASC NULLS LAST"

        async with conn.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [self._row_to_job(r) for r in rows]

    async def pause_job(self, job_id: str, reason: str, actor: str = "user") -> None:
        conn = await self.get_connection()
        await conn.execute(
            """
            UPDATE scheduled_jobs
            SET state = 'paused', pause_reason = ?, updated_at_utc = unixepoch()
            WHERE id = ? AND deleted_at_utc IS NULL
            """,
            (reason, job_id),
        )
        await conn.execute(
            """
            INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
            VALUES (hex(randomblob(16)), ?, NULL, unixepoch(), ?, 'job_paused', 'paused', ?)
            """,
            (job_id, actor, json.dumps({"reason": reason})),
        )
        await conn.commit()

    async def resume_job(self, job_id: str, next_run_at_utc: int, actor: str = "desktop_user") -> None:
        conn = await self.get_connection()
        await conn.execute(
            """
            UPDATE scheduled_jobs
            SET state = 'active', pause_reason = NULL, next_run_at_utc = ?, updated_at_utc = unixepoch()
            WHERE id = ? AND deleted_at_utc IS NULL
            """,
            (next_run_at_utc, job_id),
        )
        await conn.execute(
            """
            INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
            VALUES (hex(randomblob(16)), ?, NULL, unixepoch(), ?, 'job_resumed', 'resumed', ?)
            """,
            (job_id, actor, json.dumps({"next_run_at_utc": next_run_at_utc})),
        )
        await conn.commit()

    async def cancel_job(self, job_id: str, actor: str = "user") -> None:
        conn = await self.get_connection()
        await conn.execute(
            """
            UPDATE scheduled_jobs
            SET state = 'cancelled', updated_at_utc = unixepoch()
            WHERE id = ? AND deleted_at_utc IS NULL
            """,
            (job_id,),
        )
        # Request cancellation of any currently active run
        await conn.execute(
            """
            UPDATE job_runs
            SET cancellation_requested = 1
            WHERE job_id = ? AND state IN ('running', 'stopping')
            """,
            (job_id,),
        )
        await conn.execute(
            """
            INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
            VALUES (hex(randomblob(16)), ?, NULL, unixepoch(), ?, 'job_cancelled', 'cancelled', '{}')
            """,
            (job_id, actor),
        )
        await conn.commit()

    async def delete_job(self, job_id: str, actor: str = "desktop_user") -> None:
        """Tombstone job to preserve run history for the 30-day retention period."""
        conn = await self.get_connection()
        await conn.execute(
            """
            UPDATE scheduled_jobs
            SET state = 'cancelled', deleted_at_utc = unixepoch(), updated_at_utc = unixepoch()
            WHERE id = ?
            """,
            (job_id,),
        )
        await conn.execute(
            """
            UPDATE job_runs
            SET cancellation_requested = 1
            WHERE job_id = ? AND state IN ('running', 'stopping')
            """,
            (job_id,),
        )
        await conn.execute(
            """
            INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
            VALUES (hex(randomblob(16)), ?, NULL, unixepoch(), ?, 'job_deleted', 'deleted', '{}')
            """,
            (job_id, actor),
        )
        await conn.commit()

    async def claim_next_due_job(
        self,
        now_utc: int,
        owner_instance: str,
        ownership_generation: int = 1,
        lease_duration_seconds: int = 60,
        grace_seconds: int = 60,
        max_workspace_runs: int = 1,
        max_installation_runs: int = 2,
        max_daily_workspace_tokens: int = 50000,
        max_daily_installation_tokens: int = 100000,
    ) -> Optional[tuple["ScheduledJob", "JobRun"]]:
        """Atomically claim the next due job within concurrency and quota bounds.
        
        Guarantees one admitted attempt per scheduled occurrence via unique constraint.
        """
        import datetime
        import uuid
        from friday.scheduler.models import RunState

        conn = await self.get_connection()
        day_str = datetime.datetime.fromtimestamp(now_utc, datetime.timezone.utc).strftime("%Y-%m-%d")

        await self._get_lock().acquire()
        try:
            # Atomic transaction: ensure no dangling transaction then BEGIN IMMEDIATE
            try:
                await conn.rollback()
            except Exception:
                pass
            await conn.execute("BEGIN IMMEDIATE;")
            # 1. Check total installation concurrency
            async with conn.execute(
                "SELECT COUNT(*) FROM job_runs WHERE state IN ('running', 'stopping');"
            ) as cur:
                total_running = (await cur.fetchone())[0]
                if total_running >= max_installation_runs:
                    await conn.rollback()
                    return None

            # 2. Check total installation token quota
            async with conn.execute(
                """
                SELECT reserved_tokens + consumed_tokens FROM scheduler_quota_usage
                WHERE accounting_day_utc = ? AND scope = 'installation' AND scope_id = 'global'
                """,
                (day_str,),
            ) as cur:
                row = await cur.fetchone()
                inst_tokens = row[0] if row else 0
                if inst_tokens >= max_daily_installation_tokens:
                    await conn.rollback()
                    return None

            # 3. Find candidates due for execution
            async with conn.execute(
                """
                SELECT * FROM scheduled_jobs
                WHERE state = 'active'
                  AND deleted_at_utc IS NULL
                  AND next_run_at_utc IS NOT NULL
                  AND next_run_at_utc <= ?
                  AND (max_runs IS NULL OR run_count < max_runs)
                ORDER BY next_run_at_utc ASC
                """,
                (now_utc,),
            ) as cur:
                candidates = await cur.fetchall()

            skipped_any = False

            for cand_row in candidates:
                cand = self._row_to_job(cand_row)

                # Check if this candidate is overdue past admission grace window
                if cand.next_run_at_utc is not None and now_utc > (cand.next_run_at_utc + grace_seconds):
                    # Overdue! Advance occurrence forward and record skipped run without backlog replay.
                    from friday.scheduler.cron import CronCalendarAdapter
                    from friday.scheduler.models import ScheduleType

                    if cand.schedule_type == ScheduleType.ONCE or (cand.max_runs is not None and cand.run_count + 1 >= cand.max_runs):
                        next_occ = None
                        new_state = "completed"
                    else:
                        next_occ = CronCalendarAdapter.compute_next_run(
                            ScheduleType.CRON,
                            cand.cron_expression,
                            cand.delay_seconds,
                            cand.timezone,
                            base_time_utc=now_utc,
                            watermark_utc=cand.next_run_at_utc,
                        )
                        new_state = cand.state.value

                    skip_run_id = str(uuid.uuid4())
                    await conn.execute(
                        """
                        INSERT INTO job_runs (
                            id, job_id, scheduled_for_utc, state, owner_instance,
                            ownership_generation, lease_expires_at_utc, started_at_utc,
                            completed_at_utc, reserved_tokens, consumed_tokens,
                            cancellation_requested, quiescence_confirmed, outcome_certain,
                            output_summary
                        ) VALUES (?, ?, ?, 'skipped', ?, ?, ?, ?, ?, 0, 0, 0, 1, 1, 'Overdue occurrence skipped (missed admission grace)')
                        """,
                        (skip_run_id, cand.id, cand.next_run_at_utc, owner_instance, ownership_generation, now_utc, now_utc, now_utc),
                    )
                    await conn.execute(
                        """
                        UPDATE scheduled_jobs
                        SET next_run_at_utc = ?,
                            state = ?,
                            watermark_utc = max(coalesce(watermark_utc, 0), ?),
                            updated_at_utc = ?
                        WHERE id = ?
                        """,
                        (next_occ, new_state, cand.next_run_at_utc, now_utc, cand.id),
                    )
                    await conn.execute(
                        """
                        INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
                        VALUES (hex(randomblob(16)), ?, ?, ?, ?, 'run_skipped', 'overdue_grace_expired', ?)
                        """,
                        (cand.id, skip_run_id, now_utc, owner_instance, json.dumps({"skipped_scheduled_for": cand.next_run_at_utc, "advanced_to": next_occ})),
                    )
                    skipped_any = True
                    continue

                # Check if this job already has an active run
                async with conn.execute(
                    "SELECT COUNT(*) FROM job_runs WHERE job_id = ? AND state IN ('running', 'stopping')",
                    (cand.id,),
                ) as cur:
                    if (await cur.fetchone())[0] > 0:
                        continue

                # Check workspace concurrency
                async with conn.execute(
                    """
                    SELECT COUNT(*) FROM job_runs jr
                    JOIN scheduled_jobs sj ON jr.job_id = sj.id
                    WHERE sj.workspace_root = ? AND jr.state IN ('running', 'stopping')
                    """,
                    (cand.workspace_root,),
                ) as cur:
                    if (await cur.fetchone())[0] >= max_workspace_runs:
                        continue

                # Check workspace quota
                async with conn.execute(
                    """
                    SELECT reserved_tokens + consumed_tokens FROM scheduler_quota_usage
                    WHERE accounting_day_utc = ? AND scope = 'workspace' AND scope_id = ?
                    """,
                    (day_str, cand.workspace_root),
                ) as cur:
                    row = await cur.fetchone()
                    ws_tokens = row[0] if row else 0
                    if ws_tokens + cand.permission_snapshot.tokens_per_run > max_daily_workspace_tokens:
                        continue

                # Candidate is eligible! Create run and claim.
                run_id = str(uuid.uuid4())
                scheduled_for = cand.next_run_at_utc
                lease_expires = now_utc + lease_duration_seconds
                reserved_tokens = cand.permission_snapshot.tokens_per_run

                # Insert unique run occurrence
                await conn.execute(
                    """
                    INSERT INTO job_runs (
                        id, job_id, scheduled_for_utc, state, owner_instance,
                        ownership_generation, lease_expires_at_utc, started_at_utc,
                        reserved_tokens, consumed_tokens, cancellation_requested,
                        quiescence_confirmed, outcome_certain
                    ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, 0, 0, 0, 1)
                    """,
                    (
                        run_id, cand.id, scheduled_for, owner_instance,
                        ownership_generation, lease_expires, now_utc, reserved_tokens,
                    ),
                )

                # Update job counters & watermark
                await conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET run_count = run_count + 1,
                        last_run_at_utc = ?,
                        watermark_utc = max(coalesce(watermark_utc, 0), ?),
                        updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (now_utc, scheduled_for, now_utc, cand.id),
                )

                # Reserve quota
                await conn.execute(
                    """
                    INSERT INTO scheduler_quota_usage (accounting_day_utc, scope, scope_id, reserved_tokens, consumed_tokens)
                    VALUES (?, 'workspace', ?, ?, 0)
                    ON CONFLICT(accounting_day_utc, scope, scope_id) DO UPDATE SET
                        reserved_tokens = reserved_tokens + excluded.reserved_tokens
                    """,
                    (day_str, cand.workspace_root, reserved_tokens),
                )
                await conn.execute(
                    """
                    INSERT INTO scheduler_quota_usage (accounting_day_utc, scope, scope_id, reserved_tokens, consumed_tokens)
                    VALUES (?, 'installation', 'global', ?, 0)
                    ON CONFLICT(accounting_day_utc, scope, scope_id) DO UPDATE SET
                        reserved_tokens = reserved_tokens + excluded.reserved_tokens
                    """,
                    (day_str, reserved_tokens),
                )

                # Log event
                await conn.execute(
                    """
                    INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
                    VALUES (hex(randomblob(16)), ?, ?, ?, ?, 'run_claimed', 'claimed', ?)
                    """,
                    (
                        cand.id, run_id, now_utc, owner_instance,
                        json.dumps({"scheduled_for_utc": scheduled_for, "lease_expires": lease_expires}),
                    ),
                )

                await conn.commit()

                # Refresh job record
                refreshed_job = await self.get_job(cand.id)
                run_obj = await self.get_run(run_id)
                assert refreshed_job is not None and run_obj is not None
                return refreshed_job, run_obj

            if skipped_any:
                await conn.commit()
            else:
                await conn.rollback()
            return None

        except BaseException as e:
            try:
                await conn.rollback()
            except Exception:
                pass
            if not isinstance(e, asyncio.CancelledError):
                logger.error("Error during claim_next_due_job: %s", e)
            raise
        finally:
            self._get_lock().release()

    async def refresh_lease(
        self,
        run_id: str,
        owner_instance: str,
        ownership_generation: int,
        extend_seconds: int = 60,
    ) -> bool:
        """Heartbeat to extend active worker lease. Fails closed if ownership is lost."""
        conn = await self.get_connection()
        now_utc = int(time.time())
        new_expiry = now_utc + extend_seconds
        res = await conn.execute(
            """
            UPDATE job_runs
            SET lease_expires_at_utc = ?
            WHERE id = ?
              AND owner_instance = ?
              AND ownership_generation = ?
              AND state = 'running'
            """,
            (new_expiry, run_id, owner_instance, ownership_generation),
        )
        await conn.commit()
        return res.rowcount > 0

    async def complete_run(
        self,
        run_id: str,
        owner_instance: str,
        ownership_generation: int,
        final_state: "RunState",
        consumed_tokens: int,
        output_summary: Optional[str] = None,
        error_summary: Optional[str] = None,
        outcome_certain: bool = True,
        next_run_at_utc: Optional[int] = None,
    ) -> bool:
        """Finalize an admitted run and adjust quotas atomically."""
        import datetime
        from friday.scheduler.models import RunState, ScheduleState

        conn = await self.get_connection()
        now_utc = int(time.time())
        day_str = datetime.datetime.fromtimestamp(now_utc, datetime.timezone.utc).strftime("%Y-%m-%d")

        await self._get_lock().acquire()
        try:
            try:
                await conn.rollback()
            except Exception:
                pass
            await conn.execute("BEGIN IMMEDIATE;")
            # 1. Fetch run and job
            async with conn.execute(
                """
                SELECT jr.*, sj.workspace_root, sj.schedule_type, sj.max_runs, sj.run_count
                FROM job_runs jr
                JOIN scheduled_jobs sj ON jr.job_id = sj.id
                WHERE jr.id = ? AND jr.owner_instance = ? AND jr.ownership_generation = ?
                """,
                (run_id, owner_instance, ownership_generation),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    logger.warning("Attempted to complete run %s with stale ownership", run_id)
                    return False

            job_id = row["job_id"]
            ws_root = row["workspace_root"]
            sched_type = row["schedule_type"]
            max_runs = row["max_runs"]
            run_count = row["run_count"]
            reserved_tokens = row["reserved_tokens"]

            # Cap output/error summaries at 256 KiB
            capped_output = output_summary[: 256 * 1024] if output_summary else None
            capped_error = error_summary[: 256 * 1024] if error_summary else None

            # 2. Update run record
            await conn.execute(
                """
                UPDATE job_runs
                SET state = ?, completed_at_utc = ?, consumed_tokens = ?,
                    output_summary = ?, error_summary = ?, outcome_certain = ?,
                    quiescence_confirmed = 1
                WHERE id = ?
                """,
                (
                    final_state.value, now_utc, consumed_tokens,
                    capped_output, capped_error, int(outcome_certain), run_id,
                ),
            )

            # 3. Update quota usage: unreserve and record actual consumption
            await conn.execute(
                """
                UPDATE scheduler_quota_usage
                SET reserved_tokens = max(0, reserved_tokens - ?),
                    consumed_tokens = consumed_tokens + ?
                WHERE accounting_day_utc = ? AND scope = 'workspace' AND scope_id = ?
                """,
                (reserved_tokens, consumed_tokens, day_str, ws_root),
            )
            await conn.execute(
                """
                UPDATE scheduler_quota_usage
                SET reserved_tokens = max(0, reserved_tokens - ?),
                    consumed_tokens = consumed_tokens + ?
                WHERE accounting_day_utc = ? AND scope = 'installation' AND scope_id = 'global'
                """,
                (reserved_tokens, consumed_tokens, day_str),
            )

            # 4. Update scheduled job state
            if final_state in (RunState.FAILED, RunState.DENIED, RunState.TIMEOUT, RunState.INTERRUPTED):
                # Failures or security blocks pause recurring jobs for user review
                await conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET state = 'paused', pause_reason = ?, updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (f"Run completed with {final_state.value}", now_utc, job_id),
                )
            elif sched_type == "once" or (max_runs is not None and run_count >= max_runs):
                await conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET state = 'completed', next_run_at_utc = NULL, updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (now_utc, job_id),
                )
            else:
                # Advance cron occurrence
                await conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET next_run_at_utc = ?, updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (next_run_at_utc, now_utc, job_id),
                )

            # 5. Log completion event
            await conn.execute(
                """
                INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
                VALUES (hex(randomblob(16)), ?, ?, ?, ?, 'run_completed', ?, ?)
                """,
                (
                    job_id, run_id, now_utc, owner_instance, final_state.value,
                    json.dumps({
                        "consumed_tokens": consumed_tokens,
                        "outcome_certain": outcome_certain,
                        "next_run_at_utc": next_run_at_utc,
                    }),
                ),
            )

            await conn.commit()
            return True

        except BaseException as e:
            try:
                await conn.rollback()
            except Exception:
                pass
            if not isinstance(e, asyncio.CancelledError):
                logger.error("Error during complete_run for %s: %s", run_id, e)
            raise
        finally:
            self._get_lock().release()

    async def get_run(self, run_id: str) -> Optional["JobRun"]:
        conn = await self.get_connection()
        async with conn.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._row_to_run(row)

    async def list_runs(
        self,
        job_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["JobRun"]:
        """List job run history with pagination, optionally filtered by job_id or state."""
        conn = await self.get_connection()
        query = "SELECT * FROM job_runs WHERE 1=1"
        params: List[Any] = []
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY started_at_utc DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with conn.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [self._row_to_run(r) for r in rows]

    async def get_active_run_for_job(self, job_id: str) -> Optional["JobRun"]:
        conn = await self.get_connection()
        async with conn.execute(
            "SELECT * FROM job_runs WHERE job_id = ? AND state IN ('running', 'stopping')", (job_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._row_to_run(row)

    async def list_runs_for_job(self, job_id: str, limit: int = 50) -> List["JobRun"]:
        conn = await self.get_connection()
        async with conn.execute(
            "SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at_utc DESC LIMIT ?",
            (job_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_run(r) for r in rows]

    async def recover_expired_leases(self, now_utc: int) -> List[str]:
        """Detect expired leases, move to stopping, and pause schedules for review."""
        conn = await self.get_connection()
        await self._get_lock().acquire()
        try:
            await conn.execute("BEGIN IMMEDIATE;")
            async with conn.execute(
                """
                SELECT id, job_id FROM job_runs
                WHERE state = 'running' AND lease_expires_at_utc < ?
                """,
                (now_utc,),
            ) as cur:
                expired = await cur.fetchall()

            recovered_ids = []
            for row in expired:
                run_id = row["id"]
                job_id = row["job_id"]
                recovered_ids.append(run_id)

                await conn.execute(
                    """
                    UPDATE job_runs
                    SET state = 'stopping', outcome_certain = 0, cancellation_requested = 1
                    WHERE id = ?
                    """,
                    (run_id,),
                )
                await conn.execute(
                    """
                    UPDATE scheduled_jobs
                    SET state = 'paused', pause_reason = 'Lease expired / worker unverified', updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (now_utc, job_id),
                )
                await conn.execute(
                    """
                    INSERT INTO scheduler_events (id, job_id, run_id, timestamp_utc, actor, event_type, reason_code, details)
                    VALUES (hex(randomblob(16)), ?, ?, ?, 'supervisor', 'lease_expired', 'unverified', '{}')
                    """,
                    (job_id, run_id, now_utc),
                )

            await conn.commit()
            return recovered_ids
        except Exception as e:
            await conn.rollback()
            logger.error("Error in recover_expired_leases: %s", e)
            raise
        finally:
            self._get_lock().release()

    async def confirm_run_quiescence(self, run_id: str) -> None:
        """Mark worker quiescence confirmed and finalize interrupted run."""
        conn = await self.get_connection()
        await conn.execute(
            """
            UPDATE job_runs
            SET state = 'interrupted', quiescence_confirmed = 1
            WHERE id = ? AND state IN ('running', 'stopping')
            """,
            (run_id,),
        )
        await conn.commit()

    async def purge_retained_history(self, now_utc: int, retention_days: int = 30) -> int:
        """Purge run history and tombstoned jobs older than the retention window."""
        cutoff_utc = now_utc - (retention_days * 86400)
        conn = await self.get_connection()
        await self._get_lock().acquire()
        try:
            await conn.execute("BEGIN IMMEDIATE;")
            res1 = await conn.execute(
                "DELETE FROM job_runs WHERE started_at_utc < ? AND state NOT IN ('running', 'stopping')",
                (cutoff_utc,),
            )
            res2 = await conn.execute(
                "DELETE FROM scheduler_events WHERE timestamp_utc < ?",
                (cutoff_utc,),
            )
            res3 = await conn.execute(
                "DELETE FROM scheduled_jobs WHERE deleted_at_utc IS NOT NULL AND deleted_at_utc < ?",
                (cutoff_utc,),
            )
            await conn.commit()
            return res1.rowcount + res2.rowcount + res3.rowcount
        except Exception as e:
            await conn.rollback()
            logger.error("Error during purge_retained_history: %s", e)
            raise
        finally:
            self._get_lock().release()

    async def backup_database(self, backup_path: Path | str) -> None:
        """Safely backup active SQLite database using online backup API."""
        import sqlite3
        target_path = Path(backup_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        def _do_backup() -> None:
            with sqlite3.connect(self.db_path) as src_conn, sqlite3.connect(target_path) as dst_conn:
                src_conn.backup(dst_conn)

        await asyncio.to_thread(_do_backup)
        logger.info("Successfully created online SQLite backup at %s", target_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
