"""Native schedule management tools for Friday (Phase 11 Milestone 5).

Invariants:
1. schedule.create:
   - Risk 0 for read-only permissions (max_risk_level = 0).
   - Risk 1 for workspace write permissions (max_risk_level = 1), requiring execution specification digest approval.
   - Risk 2 (system change / process execution) is strictly prohibited and fails closed.
2. schedule.list / get / runs:
   - Risk 0, untrusted workspace-scoped queries.
3. schedule.pause / cancel:
   - Risk 1 safe modifications.
4. schedule.resume / delete:
   - Risk 1 user/desktop administrative endpoints.
5. Anti-recursion:
   - All tools under schedule.* are blocked from dispatch when is_scheduled_turn is active.
"""

import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

from friday.scheduler.cron import CronCalendarAdapter
from friday.scheduler.db import SchedulerDatabaseManager
from friday.scheduler.models import (
    JobPermissionSnapshot,
    PolicyDeniedError,
    ScheduleState,
    ScheduleType,
    ScheduledJob,
    compute_execution_specification_digest,
)
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class ScheduleCreateTool(Tool):
    """Creates a new durable scheduled job with frozen permission snapshot."""

    name = "schedule.create"
    description = (
        "Create a durable scheduled job (one-shot delay or recurring cron). "
        "Captures an immutable, frozen permission snapshot for unattended execution."
    )
    risk_level = 0  # Dynamic risk: 0 for read-only, 1 for write (Risk 2 forbidden)
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Human-readable label for this schedule"},
            "prompt": {"type": "string", "description": "The exact user instruction/prompt to execute"},
            "schedule_type": {
                "type": "string",
                "enum": ["once", "cron"],
                "description": "'once' for one-shot relative delay, 'cron' for standard 5-field calendar schedule",
            },
            "cron_expression": {
                "type": "string",
                "description": "Standard 5-field cron expression (minute hour dom month dow). Required if schedule_type is 'cron'.",
            },
            "delay_seconds": {
                "type": "integer",
                "description": "Delay in seconds from now (minimum 60s). Required if schedule_type is 'once'.",
            },
            "timezone": {
                "type": "string",
                "default": "America/New_York",
                "description": "IANA timezone identifier (e.g. 'America/New_York' or 'UTC')",
            },
            "workspace_root": {
                "type": "string",
                "description": "Workspace root directory path. Defaults to active workspace.",
            },
            "allowed_tool_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit whitelist of tool IDs permitted during execution.",
            },
            "max_risk_level": {
                "type": "integer",
                "default": 0,
                "description": "0: read-only, 1: workspace writes. Risk 2 (process execution) is strictly forbidden.",
            },
            "tokens_per_run": {
                "type": "integer",
                "default": 8000,
                "description": "Max token consumption budget per scheduled execution turn (max 32000).",
            },
            "tool_calls_per_run": {
                "type": "integer",
                "default": 50,
                "description": "Max tool calls per scheduled execution turn.",
            },
            "duration_seconds_per_run": {
                "type": "integer",
                "default": 300,
                "description": "Hard watchdog execution timeout in seconds (max 300s).",
            },
            "max_runs": {
                "type": "integer",
                "description": "Optional maximum number of execution occurrences before job auto-completes.",
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional client-supplied idempotency key to prevent duplicate creation.",
            },
        },
        "required": ["title", "prompt", "schedule_type"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager, default_workspace_root: Path | str) -> None:
        self.db_manager = db_manager
        self.default_workspace_root = str(Path(default_workspace_root).resolve())

    def classify_risk(self, arguments: Dict[str, Any]) -> int:
        """Classify dynamic risk: 1 if workspace write permission is requested; refuse if Risk >= 2."""
        max_risk = int(arguments.get("max_risk_level", 0))
        if max_risk >= 2:
            return 2
        if max_risk == 1:
            return 1
        return 0

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            title = arguments["title"]
            prompt = arguments["prompt"]
            sched_type_str = arguments["schedule_type"]
            cron_expr = arguments.get("cron_expression")
            delay_sec = arguments.get("delay_seconds")
            tz_name = arguments.get("timezone", "America/New_York")
            workspace_root = str(Path(arguments.get("workspace_root") or self.default_workspace_root).resolve())
            allowed_tool_ids = list(arguments.get("allowed_tool_ids", []))
            max_risk_level = int(arguments.get("max_risk_level", 0))
            tokens_per_run = int(arguments.get("tokens_per_run", 8000))
            tool_calls_per_run = int(arguments.get("tool_calls_per_run", 50))
            duration_sec = int(arguments.get("duration_seconds_per_run", 300))
            max_runs = arguments.get("max_runs")
            if max_runs is not None:
                max_runs = int(max_runs)
            idempotency_key = arguments.get("idempotency_key")

            # Validate risk level
            if max_risk_level >= 2:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Risk {max_risk_level} (process execution / system change) is strictly forbidden for scheduled turns.",
                )

            # Validate schedule type and calculate initial next_run_at_utc
            now_utc = int(time.time())
            if sched_type_str == "once":
                sched_type = ScheduleType.ONCE
                if delay_sec is None:
                    return ToolResult(
                        tool_name=self.name,
                        call_id=call_id,
                        success=False,
                        output="",
                        error="delay_seconds is required when schedule_type is 'once'.",
                    )
                CronCalendarAdapter.validate_delay(delay_sec)
                next_run_at_utc = now_utc + delay_sec
                expr_or_delay = delay_sec
            elif sched_type_str == "cron":
                sched_type = ScheduleType.CRON
                if not cron_expr:
                    return ToolResult(
                        tool_name=self.name,
                        call_id=call_id,
                        success=False,
                        output="",
                        error="cron_expression is required when schedule_type is 'cron'.",
                    )
                CronCalendarAdapter.validate_cron_expression(cron_expr)
                CronCalendarAdapter.validate_timezone(tz_name)
                next_run_at_utc = CronCalendarAdapter.get_next_occurrence(cron_expr, tz_name, now_utc)
                expr_or_delay = cron_expr
            else:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Invalid schedule_type '{sched_type_str}'. Must be 'once' or 'cron'.",
                )

            # Compute execution specification digest
            approval_digest = compute_execution_specification_digest(
                prompt=prompt,
                title=title,
                schedule_type=sched_type.value,
                schedule_expr_or_delay=expr_or_delay,
                timezone_name=tz_name,
                workspace_root=workspace_root,
                allowed_tool_ids=allowed_tool_ids,
                max_risk_level=max_risk_level,
                tokens_per_run=tokens_per_run,
                tool_calls_per_run=tool_calls_per_run,
                duration_seconds_per_run=duration_sec,
                max_runs=max_runs,
            )

            # Mint JobPermissionSnapshot
            snapshot = JobPermissionSnapshot(
                source_session_id=arguments.get("session_id", "default-session"),
                allowed_tool_ids=allowed_tool_ids,
                max_risk_level=max_risk_level,
                workspace_root=workspace_root,
                tokens_per_run=tokens_per_run,
                tool_calls_per_run=tool_calls_per_run,
                duration_seconds_per_run=duration_sec,
                approval_digest=approval_digest,
                is_recurring=(sched_type == ScheduleType.CRON),
            )

            job = ScheduledJob(
                id=str(uuid.uuid4()),
                session_id=arguments.get("session_id", "default-session"),
                workspace_root=workspace_root,
                title=title,
                prompt=prompt,
                schedule_type=sched_type,
                cron_expression=cron_expr,
                delay_seconds=delay_sec,
                timezone=tz_name,
                next_run_at_utc=next_run_at_utc,
                state=ScheduleState.ACTIVE,
                max_runs=max_runs,
                permission_snapshot=snapshot,
                approval_digest=approval_digest,
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
                idempotency_key=idempotency_key,
            )

            persisted = await self.db_manager.create_job(job)

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=json.dumps(
                    {
                        "job_id": persisted.id,
                        "title": persisted.title,
                        "schedule_type": persisted.schedule_type.value,
                        "next_run_at_utc": persisted.next_run_at_utc,
                        "state": persisted.state.value,
                        "approval_digest": persisted.approval_digest,
                    },
                    indent=2,
                ),
            )
        except Exception as exc:
            logger.error("schedule.create failed: %s", exc, exc_info=True)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )


class ScheduleListTool(Tool):
    """Lists scheduled jobs for a workspace."""

    name = "schedule.list"
    description = "List all scheduled jobs in the workspace with their current status and next scheduled run."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "workspace_root": {"type": "string", "description": "Optional workspace root filter"},
            "state": {"type": "string", "enum": ["active", "paused", "completed", "failed", "cancelled"]},
        },
    }

    def __init__(self, db_manager: SchedulerDatabaseManager, default_workspace_root: Path | str) -> None:
        self.db_manager = db_manager
        self.default_workspace_root = str(Path(default_workspace_root).resolve())

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            ws = arguments.get("workspace_root") or self.default_workspace_root
            state = arguments.get("state")
            jobs = await self.db_manager.list_jobs(workspace_root=ws, state=state)
            summaries = [
                {
                    "job_id": j.id,
                    "title": j.title,
                    "state": j.state.value,
                    "schedule_type": j.schedule_type.value,
                    "next_run_at_utc": j.next_run_at_utc,
                    "run_count": j.run_count,
                    "max_runs": j.max_runs,
                }
                for j in jobs
            ]
            return ToolResult(tool_name=self.name, call_id=call_id, success=True, output=json.dumps(summaries, indent=2))
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class ScheduleGetTool(Tool):
    """Retrieves detailed information about a specific scheduled job."""

    name = "schedule.get"
    description = "Get detailed specification and permission snapshot for a scheduled job."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The unique ID of the scheduled job"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            job = await self.db_manager.get_job(job_id)
            if not job:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Scheduled job '{job_id}' not found.",
                )
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=job.model_dump_json(indent=2),
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class ScheduleRunsTool(Tool):
    """Retrieves paginated execution run history for a scheduled job."""

    name = "schedule.runs"
    description = "Get paginated execution history and token accounting for a scheduled job."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The ID of the scheduled job"},
            "limit": {"type": "integer", "default": 20, "description": "Maximum runs to return"},
            "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            limit = int(arguments.get("limit", 20))
            offset = int(arguments.get("offset", 0))
            runs = await self.db_manager.list_runs(job_id=job_id, limit=limit, offset=offset)
            runs_data = [r.model_dump() for r in runs]
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=json.dumps(runs_data, indent=2),
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class SchedulePauseTool(Tool):
    """Pauses an active scheduled job."""

    name = "schedule.pause"
    description = "Pause an active scheduled job. Suspends future occurrences until resumed."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The ID of the scheduled job to pause"},
            "reason": {"type": "string", "default": "User requested pause", "description": "Reason for pausing"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            reason = arguments.get("reason", "User requested pause")
            await self.db_manager.pause_job(job_id=job_id, reason=reason, actor="user")
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Job '{job_id}' paused successfully.",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class ScheduleCancelTool(Tool):
    """Cancels a scheduled job permanently."""

    name = "schedule.cancel"
    description = "Cancel a scheduled job. Cancels active runs and terminates future occurrences."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The ID of the scheduled job to cancel"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            await self.db_manager.cancel_job(job_id=job_id, actor="user")
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Job '{job_id}' cancelled successfully.",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class ScheduleResumeTool(Tool):
    """Resumes a paused scheduled job."""

    name = "schedule.resume"
    description = "Resume a paused scheduled job and compute its next future occurrence."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The ID of the scheduled job to resume"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            job = await self.db_manager.get_job(job_id)
            if not job:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=f"Job '{job_id}' not found.",
                )

            now_utc = int(time.time())
            if job.schedule_type == ScheduleType.ONCE:
                next_run = now_utc + (job.delay_seconds or 60)
            else:
                next_run = CronCalendarAdapter.compute_next_run(
                    schedule_type=ScheduleType.CRON,
                    cron_expression=job.cron_expression,
                    tz_name=job.timezone,
                    base_time_utc=now_utc,
                    watermark_utc=job.watermark_utc,
                )

            await self.db_manager.resume_job(job_id=job_id, next_run_at_utc=next_run, actor="user")
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Job '{job_id}' resumed. Next run scheduled for {next_run} UTC.",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))


class ScheduleDeleteTool(Tool):
    """Tombstones a scheduled job for desktop administrative management."""

    name = "schedule.delete"
    description = "Tombstone a scheduled job, preserving history for 30 days."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The ID of the scheduled job to delete"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db_manager: SchedulerDatabaseManager) -> None:
        self.db_manager = db_manager

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            job_id = arguments["job_id"]
            await self.db_manager.delete_job(job_id=job_id, actor="desktop_user")
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Job '{job_id}' deleted (tombstoned for 30-day retention).",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, call_id=call_id, success=False, output="", error=str(exc))
