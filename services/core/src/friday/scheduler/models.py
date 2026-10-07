"""Pydantic contracts, state models, frozen permission snapshot, and error definitions for Friday Scheduler (Phase 11).

Invariants:
1. Frozen permission snapshot is created only in trusted code with extra='forbid'.
2. Risk 2 (process execution / system change) is strictly forbidden for scheduled jobs.
3. Recursive scheduling and delegation tools (schedule.*, subagent.*, policy.*) are strictly forbidden.
4. Schedule and Run states have well-defined valid transitions; impossible transitions raise InvalidStateTransitionError.
5. All timestamps are integer UTC.
"""

from enum import Enum
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_SCHEDULE_TRANSITIONS = {
    ScheduleState.ACTIVE: {ScheduleState.PAUSED, ScheduleState.COMPLETED, ScheduleState.FAILED, ScheduleState.CANCELLED},
    ScheduleState.PAUSED: {ScheduleState.ACTIVE, ScheduleState.CANCELLED},
    ScheduleState.COMPLETED: set(),  # Terminal
    ScheduleState.FAILED: set(),     # Terminal
    ScheduleState.CANCELLED: set(),  # Terminal
}


class RunState(str, Enum):
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"


VALID_RUN_TRANSITIONS = {
    RunState.RUNNING: {
        RunState.STOPPING,
        RunState.SUCCESS,
        RunState.FAILED,
        RunState.DENIED,
        RunState.CANCELLED,
        RunState.TIMEOUT,
        RunState.INTERRUPTED,
    },
    RunState.STOPPING: {
        RunState.CANCELLED,
        RunState.INTERRUPTED,
        RunState.TIMEOUT,
        RunState.FAILED,
    },
    RunState.SUCCESS: set(),
    RunState.FAILED: set(),
    RunState.DENIED: set(),
    RunState.CANCELLED: set(),
    RunState.TIMEOUT: set(),
    RunState.INTERRUPTED: set(),
    RunState.SKIPPED: set(),
}


class ScheduleType(str, Enum):
    ONCE = "once"
    CRON = "cron"


# Forbidden tools in scheduled execution to prevent recursion, hydras, and bypasses
FORBIDDEN_SCHEDULED_TOOL_PREFIXES = ("schedule.", "subagent.", "policy.", "system.shutdown")


class JobPermissionSnapshot(BaseModel):
    """Immutable security snapshot captured and approved at job creation time."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at_utc: int = Field(default_factory=lambda: int(time.time()))
    owning_principal: str = "default_user"
    source_session_id: str
    allowed_tool_ids: List[str] = Field(default_factory=list)
    max_risk_level: int = 0  # 0: read-only, 1: workspace write (Risk 2 forbidden)
    workspace_root: str
    tokens_per_run: int = 8000
    tool_calls_per_run: int = 50
    duration_seconds_per_run: int = 300  # 5 minutes
    model_profile: str = "default"
    approval_digest: Optional[str] = None
    is_recurring: bool = False

    @field_validator("max_risk_level")
    @classmethod
    def validate_risk_level(cls, v: int) -> int:
        if v >= 2:
            raise ValueError(f"Risk {v} (process execution / system change) is strictly forbidden for scheduled turns.")
        if v < 0:
            raise ValueError("Risk level cannot be negative.")
        return v

    @field_validator("allowed_tool_ids")
    @classmethod
    def validate_allowed_tools(cls, tools: List[str]) -> List[str]:
        for t in tools:
            for prefix in FORBIDDEN_SCHEDULED_TOOL_PREFIXES:
                if t.startswith(prefix) or t == prefix[:-1]:
                    raise ValueError(f"Tool '{t}' cannot be granted in scheduled execution (anti-recursion rule).")
        return tools

    @field_validator("tokens_per_run")
    @classmethod
    def validate_tokens(cls, v: int) -> int:
        if v <= 0 or v > 32000:
            raise ValueError("tokens_per_run must be between 1 and 32000.")
        return v

    @field_validator("duration_seconds_per_run")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v <= 0 or v > 1800:
            raise ValueError("duration_seconds_per_run must be between 1 and 1800 (max 30m).")
        return v


def compute_execution_specification_digest(
    prompt: str,
    title: str,
    schedule_type: str,
    schedule_expr_or_delay: str | int,
    timezone_name: str,
    workspace_root: str,
    allowed_tool_ids: List[str],
    max_risk_level: int,
    tokens_per_run: int,
    tool_calls_per_run: int,
    duration_seconds_per_run: int,
    max_runs: Optional[int] = None,
) -> str:
    """Compute deterministic SHA-256 digest of execution specification for native modal approval."""
    spec = {
        "prompt": prompt,
        "title": title,
        "schedule_type": schedule_type,
        "schedule_detail": str(schedule_expr_or_delay),
        "timezone": timezone_name,
        "workspace_root": workspace_root,
        "allowed_tool_ids": sorted(list(set(allowed_tool_ids))),
        "max_risk_level": max_risk_level,
        "tokens_per_run": tokens_per_run,
        "tool_calls_per_run": tool_calls_per_run,
        "duration_seconds_per_run": duration_seconds_per_run,
        "max_runs": max_runs,
    }
    canonical_json = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ScheduledJob(BaseModel):
    """Durable scheduled job record."""
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    workspace_root: str
    title: str
    prompt: str
    schedule_type: ScheduleType
    cron_expression: Optional[str] = None
    delay_seconds: Optional[int] = None
    timezone: str = "America/New_York"
    next_run_at_utc: Optional[int] = None
    last_run_at_utc: Optional[int] = None
    state: ScheduleState = ScheduleState.ACTIVE
    pause_reason: Optional[str] = None
    run_count: int = 0
    max_runs: Optional[int] = None
    watermark_utc: Optional[int] = None
    permission_snapshot: JobPermissionSnapshot
    approval_digest: Optional[str] = None
    created_at_utc: int
    updated_at_utc: int
    deleted_at_utc: Optional[int] = None
    idempotency_key: Optional[str] = None


class JobRun(BaseModel):
    """Record of a single admitted execution attempt of a scheduled job."""
    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    scheduled_for_utc: int
    state: RunState = RunState.RUNNING
    owner_instance: str
    ownership_generation: int = 1
    lease_expires_at_utc: int
    started_at_utc: int
    completed_at_utc: Optional[int] = None
    cancellation_requested: bool = False
    quiescence_confirmed: bool = False
    outcome_certain: bool = True
    reserved_tokens: int = 8000
    consumed_tokens: int = 0
    output_summary: Optional[str] = None
    error_summary: Optional[str] = None


class SchedulerQuotaUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounting_day_utc: str
    scope: str
    scope_id: str
    reserved_tokens: int = 0
    consumed_tokens: int = 0


class SchedulerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: Optional[str] = None
    run_id: Optional[str] = None
    timestamp_utc: int = Field(default_factory=lambda: int(time.time()))
    actor: str = "system"
    event_type: str
    reason_code: str
    details: Dict[str, Any] = Field(default_factory=dict)


# Scheduler Exception Hierarchy
class SchedulerError(Exception):
    """Base error for Friday Scheduler."""


class InvalidScheduleError(SchedulerError):
    """Invalid cron expression, out-of-range delay, or invalid timezone."""


class InvalidSnapshotError(SchedulerError):
    """Invalid or malformed permission snapshot."""


class PolicyDeniedError(SchedulerError):
    """Operation or tool call denied by scheduler policy."""


class QuotaExceededError(SchedulerError):
    """Daily token quota or job limit exceeded."""


class ConcurrencyLimitError(SchedulerError):
    """Workspace or installation concurrent run limit reached."""


class InvalidStateTransitionError(SchedulerError):
    """Attempted illegal lifecycle transition."""


class StaleOwnerError(SchedulerError):
    """Lease or ownership generation mismatch."""


class QuiescencePendingError(SchedulerError):
    """Operation blocked because worker quiescence has not yet been confirmed."""
