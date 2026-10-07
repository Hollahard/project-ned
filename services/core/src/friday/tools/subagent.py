"""Native Subagent delegation tools for Project Friday (Phase 12 Milestone 4).

Invariants:
1. subagent.run:
   - Only callable by depth 0 parent turns (subagents and scheduled turns denied).
   - Dynamic risk classification: Risk 2 if child is granted exec / risk 2 tools, Risk 1 if workspace write, Risk 0 if read-only.
   - Monotonic capability validation before admission.
   - Bounded execution under supervised runner.
   - Untrusted result returned inside explicit fence capped at 64 KiB.
2. subagent.list:
   - Risk 0 read of session subagent history.
3. subagent.cancel:
   - Risk 1 administrative cancellation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set
import uuid

from friday.subagents.db import SubagentDatabaseManager
from friday.subagents.models import (
    ParentCapabilities,
    PolicyDeniedError,
    SubagentResult,
    SubagentRunState,
    SubagentSpec,
    validate_capability_containment,
)
if TYPE_CHECKING:
    from friday.subagents.runner import SubagentTurnRunner
from friday.tools.base import Tool, ToolResult
from friday.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SubagentRunTool(Tool):
    """Delegates a bounded task to an isolated depth-1 subagent."""

    name = "subagent.run"
    description = (
        "Delegate a scoped, bounded task to a depth-1 isolated child subagent. "
        "Child authority must be a strict subset of parent authority."
    )
    risk_level = 0  # Dynamic risk classified via classify_risk()
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": "Concise role description (e.g. 'Security Auditor', 'Code Explorer')",
            },
            "task_prompt": {
                "type": "string",
                "description": "The exact prompt/instructions for the child subagent to execute",
            },
            "allowed_tool_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Subset of parent tools granted to the child. Cannot include delegation tools.",
            },
            "max_risk_level": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2,
                "default": 0,
                "description": "Ceiling risk level permitted for child actions (0: read, 1: write, 2: exec)",
            },
            "workspace_root": {
                "type": "string",
                "description": "Filesystem workspace root for child, strictly contained in parent root",
            },
            "read_only_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of read-only paths inside workspace",
            },
            "write_only_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of write-only paths inside workspace",
            },
            "token_budget": {
                "type": "integer",
                "minimum": 100,
                "maximum": 32000,
                "default": 4000,
                "description": "Token budget reserved for child execution (default 4000)",
            },
            "iteration_budget": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 10,
                "description": "Maximum reasoning iterations (max 10)",
            },
            "duration_seconds_budget": {
                "type": "integer",
                "minimum": 5,
                "maximum": 120,
                "default": 120,
                "description": "Monotonic watchdog timeout in seconds (max 120s)",
            },
        },
        "required": ["role", "task_prompt"],
    }

    def __init__(
        self,
        runner: SubagentTurnRunner,
        parent_capabilities_provider: Callable[[], ParentCapabilities],
        parent_live_tools_provider: Callable[[], Set[str]],
        parent_cancel_event_provider: Optional[Callable[[], Optional[asyncio.Event]]] = None,
        tool_registry: Optional[ToolRegistry] = None,
        is_depth_0_caller: Callable[[], bool] = lambda: True,
    ) -> None:
        self.runner = runner
        self.parent_capabilities_provider = parent_capabilities_provider
        self.parent_live_tools_provider = parent_live_tools_provider
        self.parent_cancel_event_provider = parent_cancel_event_provider
        self.tool_registry = tool_registry
        self.is_depth_0_caller = is_depth_0_caller

    def classify_risk(self, arguments: Dict[str, Any]) -> int:
        """Classify dynamic risk based on requested child permissions."""
        requested_risk = arguments.get("max_risk_level", 0)
        if requested_risk >= 2:
            return 2

        # Check tool registry risk levels for requested tools
        if self.tool_registry:
            tool_ids = arguments.get("allowed_tool_ids", [])
            for tid in tool_ids:
                tool_obj = self.tool_registry.get(tid)
                if tool_obj and tool_obj.risk_level >= 2:
                    return 2
                if tool_obj and tool_obj.risk_level == 1:
                    requested_risk = max(requested_risk, 1)

        return requested_risk

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute delegation to child subagent after strict monotonic validation."""
        # 1. Anti-recursion / caller depth check
        if not self.is_depth_0_caller():
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="PolicyDeniedError: Subagents and scheduled turns cannot delegate (depth-1 invariant).",
            )

        try:
            parent_caps = self.parent_capabilities_provider()
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Failed to resolve parent authority: {exc}",
            )

        # 2. Build SubagentSpec
        try:
            spec = SubagentSpec(
                role=str(arguments.get("role", "")).strip(),
                task_prompt=str(arguments.get("task_prompt", "")).strip(),
                parent_session_id=parent_caps.session_id,
                parent_turn_id=call_id,
                depth=1,
                allowed_tool_ids=arguments.get("allowed_tool_ids", []),
                max_risk_level=arguments.get("max_risk_level", 0),
                workspace_root=arguments.get("workspace_root") or parent_caps.workspace_root,
                read_only_paths=arguments.get("read_only_paths", []),
                write_only_paths=arguments.get("write_only_paths", []),
                token_budget=arguments.get("token_budget", 4000),
                iteration_budget=arguments.get("iteration_budget", 10),
                duration_seconds_budget=arguments.get("duration_seconds_budget", 120),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Invalid SubagentSpec parameters: {exc}",
            )

        # 3. Monotonic capability validation
        try:
            validate_capability_containment(parent_caps, spec)
        except PolicyDeniedError as exc:
            logger.warning("Delegation rejected by monotonic containment: %s", exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=str(exc),
            )

        # 4. Resolve cancellation event
        parent_cancel_ev = None
        if self.parent_cancel_event_provider:
            parent_cancel_ev = self.parent_cancel_event_provider()

        # 5. Execute subagent
        result: SubagentResult = await self.runner.execute_subagent(
            spec=spec,
            parent_live_tools_provider=self.parent_live_tools_provider,
            parent_cancel_event=parent_cancel_ev,
        )

        formatted_output = result.format_untrusted_result()
        is_success = result.state == SubagentRunState.COMPLETED

        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=is_success,
            output=formatted_output,
            metadata={
                "run_id": result.run_id,
                "role": result.role,
                "state": result.state.value,
                "tokens_consumed": result.tokens_consumed,
                "tool_calls_count": result.tool_calls_count,
                "duration_seconds": result.duration_seconds,
                "truncated": result.truncated,
            },
            error=result.error if not is_success else None,
        )


class SubagentListTool(Tool):
    """Lists subagent runs for the current parent session."""

    name = "subagent.list"
    description = "List recent subagent runs and their lifecycle states for the active session."
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Parent session ID to query",
            }
        },
        "required": ["session_id"],
    }

    def __init__(self, db: SubagentDatabaseManager) -> None:
        self.db = db

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        session_id = arguments.get("session_id", "").strip()
        if not session_id:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="session_id is required.",
            )

        runs = await self.db.list_runs_for_session(session_id)
        sanitized = []
        for r in runs:
            sanitized.append(
                {
                    "id": r["id"],
                    "role": r["role"],
                    "state": r["state"].value,
                    "tokens_consumed": r["consumed_tokens"],
                    "started_at": r["started_at_utc"],
                    "completed_at": r["completed_at_utc"],
                    "error": r["error_summary"],
                }
            )

        import json
        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=True,
            output=json.dumps(sanitized, indent=2),
            metadata={"count": len(sanitized)},
        )


class SubagentCancelTool(Tool):
    """Requests cancellation of an active subagent run."""

    name = "subagent.cancel"
    description = "Request cancellation of an active child subagent run."
    risk_level = 1
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "ID of the subagent run to cancel",
            }
        },
        "required": ["run_id"],
    }

    def __init__(self, db: SubagentDatabaseManager) -> None:
        self.db = db

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        run_id = arguments.get("run_id", "").strip()
        if not run_id:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error="run_id is required.",
            )

        cancelled = await self.db.request_cancellation(run_id)
        if cancelled:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=f"Cancellation requested for subagent run {run_id}.",
                metadata={"run_id": run_id, "state": "stopping"},
            )
        else:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"Could not cancel run {run_id} (not active or not found).",
            )
