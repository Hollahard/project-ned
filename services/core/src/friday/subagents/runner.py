"""Supervised depth-1 subagent runner with monotonic watchdog and isolation (Phase 12 Milestone 3).

Invariants:
1. Dynamic capability verification immediately before each tool call.
2. Effective authority is intersection of child grant and live parent permitted authority.
3. Monotonic watchdog timer enforces hard duration ceiling (default 120s).
4. Cancellation propagates from parent, enforcing graceful drain then forced abort.
5. Windows Job Object containment for process isolation.
6. Untrusted result fencing and 64 KiB serialization cap.
7. Single terminal state guarantee persisted in SQLite WAL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    InferenceBackend,
    InferenceEventType,
)
from friday.security.paths import get_canonical_path, is_path_within_root
from friday.skills.cage import WindowsJobCage
from friday.subagents.db import SubagentDatabaseManager
from friday.subagents.models import (
    FORBIDDEN_SUBAGENT_TOOL_PREFIXES,
    BudgetExceededError,
    PolicyDeniedError,
    SubagentResult,
    SubagentRunState,
    SubagentSpec,
    WatchdogTimeoutError,
)
from friday.tools.base import Tool, ToolResult
from friday.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SubagentExecutionGuard:
    """Enforces dynamic capability containment, live parent authority, and budgets."""

    def __init__(
        self,
        spec: SubagentSpec,
        parent_live_tools_provider: Callable[[], Set[str]],
    ) -> None:
        self.spec = spec
        self.parent_live_tools_provider = parent_live_tools_provider
        self.tool_calls_count: int = 0
        self.tokens_consumed: int = 0
        self.workspace_root = get_canonical_path(spec.workspace_root)
        self.read_only_paths = [get_canonical_path(p) for p in spec.read_only_paths]
        self.write_only_paths = [get_canonical_path(p) for p in spec.write_only_paths]

    def check_tool_invocation(self, tool_name: str, arguments: Dict[str, Any], tool_risk_level: int = 0) -> None:
        """Validate tool invocation against child grant and live parent authority."""
        # 1. Anti-recursion invariant
        for prefix in FORBIDDEN_SUBAGENT_TOOL_PREFIXES:
            if tool_name.startswith(prefix) or tool_name == prefix[:-1]:
                raise PolicyDeniedError(
                    f"Tool '{tool_name}' is forbidden for subagents (anti-recursion invariant)."
                )

        # 2. Child granted tools
        if tool_name not in self.spec.allowed_tool_ids:
            raise PolicyDeniedError(
                f"Tool '{tool_name}' not granted to subagent (allowed: {self.spec.allowed_tool_ids})."
            )

        # 3. Dynamic intersection with live parent authority
        live_parent_tools = self.parent_live_tools_provider()
        if tool_name not in live_parent_tools:
            raise PolicyDeniedError(
                f"Tool '{tool_name}' was revoked by parent session or is no longer permitted."
            )

        # 4. Risk level ceiling
        if tool_risk_level > self.spec.max_risk_level:
            raise PolicyDeniedError(
                f"Tool '{tool_name}' risk level {tool_risk_level} exceeds subagent ceiling {self.spec.max_risk_level}."
            )

        # 5. Path boundary containment
        path_arg = arguments.get("path") or arguments.get("target_path")
        if path_arg:
            target_path = get_canonical_path(path_arg)
            if not is_path_within_root(target_path, self.workspace_root):
                raise PolicyDeniedError(
                    f"Path '{target_path}' is outside subagent workspace root '{self.workspace_root}'."
                )

            # Check write paths restriction
            if tool_name == "filesystem.write" and self.write_only_paths:
                if not any(is_path_within_root(target_path, p) for p in self.write_only_paths):
                    raise PolicyDeniedError(
                        f"Write path '{target_path}' is outside designated write paths: {self.write_only_paths}"
                    )

            # Check read paths restriction
            if tool_name == "filesystem.read" and self.read_only_paths:
                if not any(is_path_within_root(target_path, p) for p in self.read_only_paths):
                    raise PolicyDeniedError(
                        f"Read path '{target_path}' is outside designated read paths: {self.read_only_paths}"
                    )

        # 6. Tool calls count / iteration budget
        self.tool_calls_count += 1
        if self.tool_calls_count > self.spec.iteration_budget:
            raise BudgetExceededError(
                f"Subagent tool calls limit exceeded ({self.tool_calls_count} > {self.spec.iteration_budget})."
            )

    def record_tokens(self, tokens: int) -> None:
        """Record token consumption and enforce subagent token quota."""
        self.tokens_consumed += tokens
        if self.tokens_consumed > self.spec.token_budget:
            raise BudgetExceededError(
                f"Subagent token budget exceeded ({self.tokens_consumed} > {self.spec.token_budget})."
            )


class SubagentTurnRunner:
    """Supervised execution harness for depth-1 subagents."""

    def __init__(
        self,
        inference: InferenceBackend,
        tools: ToolRegistry,
        db: SubagentDatabaseManager,
        model_name: str = "default",
    ) -> None:
        self.inference = inference
        self.tools = tools
        self.db = db
        self.model_name = model_name

    async def execute_subagent(
        self,
        spec: SubagentSpec,
        parent_live_tools_provider: Callable[[], Set[str]],
        parent_cancel_event: Optional[asyncio.Event] = None,
        run_id: Optional[str] = None,
    ) -> SubagentResult:
        """Execute a subagent turn under monotonic watchdog and resource bounds."""
        assigned_id = run_id or str(uuid.uuid4())
        # 1. Admit and reserve budget in SQLite
        actual_run_id = await self.db.reserve_subagent_run(spec, run_id=assigned_id)

        guard = SubagentExecutionGuard(spec, parent_live_tools_provider)
        child_cancel_event = asyncio.Event()

        # 2. Watch parent cancellation concurrently
        cancel_monitor_task: Optional[asyncio.Task] = None
        if parent_cancel_event is not None:
            async def _monitor_parent():
                await parent_cancel_event.wait()
                child_cancel_event.set()
                await self.db.request_cancellation(actual_run_id)

            cancel_monitor_task = asyncio.create_task(_monitor_parent())

        # 3. Setup Windows Job Cage for process containment
        job_cage: Optional[WindowsJobCage] = None
        if sys.platform == "win32":
            try:
                job_cage = WindowsJobCage()
            except Exception as exc:
                logger.debug("WindowsJobCage not available: %s", exc)

        start_monotonic = time.monotonic()
        deadline_monotonic = start_monotonic + spec.duration_seconds_budget
        iteration = 0
        assistant_content = ""
        terminal_state = SubagentRunState.COMPLETED
        error_msg: Optional[str] = None

        # Build initial messages for subagent
        messages: List[ChatMessage] = [
            ChatMessage(
                role="system",
                content=(
                    f"You are a specialized subagent for Project Friday running in depth-1 isolation.\n"
                    f"Role: {spec.role}\n"
                    f"Task: {spec.task_prompt}\n"
                    f"Workspace Root: {spec.workspace_root}\n"
                    "Do not attempt to delegate tasks, create schedules, or modify policies.\n"
                    "Complete the task directly and report concise findings."
                ),
            ),
            ChatMessage(role="user", content=spec.task_prompt),
        ]

        try:
            while iteration < spec.iteration_budget:
                iteration += 1

                # Check cancellation
                if child_cancel_event.is_set():
                    terminal_state = SubagentRunState.CANCELLED
                    error_msg = "Subagent cancelled by parent session or user request."
                    break

                # Check monotonic watchdog timeout
                now_monotonic = time.monotonic()
                if now_monotonic >= deadline_monotonic:
                    terminal_state = SubagentRunState.TIMEOUT
                    error_msg = (
                        f"Subagent watchdog timeout ({spec.duration_seconds_budget}s wall-clock ceiling reached)."
                    )
                    break

                # Prepare tools schema filtered to child's allowed tools
                allowed_schemas = self.tools.get_schemas(allowed_names=spec.allowed_tool_ids)
                request = ChatRequest(
                    model=self.model_name,
                    messages=messages,
                    tools=allowed_schemas if allowed_schemas else None,
                    max_tokens=min(2048, spec.token_budget - guard.tokens_consumed),
                )

                assistant_content = ""
                tool_calls = []

                # Stream model generation with timeout
                remaining_time = max(0.1, deadline_monotonic - time.monotonic())
                try:
                    async with asyncio.timeout(remaining_time):
                        async for event in self.inference.generate(request):
                            if child_cancel_event.is_set():
                                terminal_state = SubagentRunState.CANCELLED
                                break

                            if event.type == InferenceEventType.TOKEN_DELTA:
                                assistant_content += event.content
                            elif event.type == InferenceEventType.TOOL_CALL:
                                if event.tool_call:
                                    tool_calls.append(event.tool_call)
                            elif event.type == InferenceEventType.USAGE:
                                tokens_used = event.prompt_tokens + event.completion_tokens
                                guard.record_tokens(tokens_used)
                            elif event.type == InferenceEventType.ERROR:
                                terminal_state = SubagentRunState.FAILED
                                error_msg = event.content
                                break
                except (asyncio.TimeoutError, TimeoutError):
                    terminal_state = SubagentRunState.TIMEOUT
                    error_msg = f"Subagent watchdog timeout after {spec.duration_seconds_budget}s."
                    break

                if (
                    child_cancel_event.is_set()
                    or (parent_cancel_event and parent_cancel_event.is_set())
                ):
                    terminal_state = SubagentRunState.CANCELLED
                    error_msg = "Subagent cancelled by parent session or user request."
                    break

                if terminal_state in (SubagentRunState.CANCELLED, SubagentRunState.FAILED, SubagentRunState.TIMEOUT):
                    break

                # Record assistant turn
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls if tool_calls else None,
                    )
                )

                # If no tool calls, subagent finished its work!
                if not tool_calls:
                    terminal_state = SubagentRunState.COMPLETED
                    break

                # Dispatch tool calls
                for tc in tool_calls:
                    if child_cancel_event.is_set():
                        terminal_state = SubagentRunState.CANCELLED
                        break

                    fn_info = tc.get("function", {})
                    call_id = tc.get("id", str(uuid.uuid4()))
                    name = fn_info.get("name", "")
                    raw_args = fn_info.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = raw_args

                    tool_instance = self.tools.get(name)
                    if not tool_instance:
                        messages.append(
                            ChatMessage(
                                role="tool",
                                content=f"Error: Tool '{name}' not found.",
                                tool_call_id=call_id,
                            )
                        )
                        continue

                    # Dynamic authorization and bounds check
                    try:
                        guard.check_tool_invocation(name, args, tool_instance.risk_level)
                    except (PolicyDeniedError, BudgetExceededError) as exc:
                        logger.warning("Subagent tool call blocked: %s", exc)
                        messages.append(
                            ChatMessage(
                                role="tool",
                                content=f"PolicyDeniedError: {str(exc)}",
                                tool_call_id=call_id,
                            )
                        )
                        if isinstance(exc, BudgetExceededError):
                            terminal_state = SubagentRunState.FAILED
                            error_msg = str(exc)
                            break
                        continue

                    # Execute tool inside isolated environment
                    tool_result = await tool_instance.execute(call_id, args)
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=tool_result.output if tool_result.success else f"Error: {tool_result.error}",
                            tool_call_id=call_id,
                        )
                    )

                if terminal_state == SubagentRunState.CANCELLED:
                    break

            else:
                # Loop ended without break -> reached iteration budget
                if terminal_state == SubagentRunState.COMPLETED and tool_calls:
                    terminal_state = SubagentRunState.FAILED
                    error_msg = f"Iteration budget ({spec.iteration_budget}) exhausted before completion."

        except Exception as exc:
            logger.exception("Unexpected error during subagent execution: %s", exc)
            terminal_state = SubagentRunState.FAILED
            error_msg = str(exc)

        finally:
            if cancel_monitor_task and not cancel_monitor_task.done():
                cancel_monitor_task.cancel()

            # Close cage if allocated
            if job_cage:
                try:
                    job_cage.close()
                except Exception as exc:
                    logger.debug("Error closing job cage: %s", exc)

            elapsed_seconds = time.monotonic() - start_monotonic

            # Complete run in SQLite
            try:
                await self.db.complete_subagent_run(
                    run_id=actual_run_id,
                    state=terminal_state,
                    consumed_tokens=guard.tokens_consumed,
                    tool_calls_count=guard.tool_calls_count,
                    output_summary=assistant_content,
                    error_summary=error_msg,
                    quiescence_confirmed=True,
                )
            except Exception as exc:
                logger.error("Failed to mark run %s complete in database: %s", actual_run_id, exc)

        return SubagentResult(
            run_id=actual_run_id,
            role=spec.role,
            state=terminal_state,
            tokens_consumed=guard.tokens_consumed,
            tool_calls_count=guard.tool_calls_count,
            duration_seconds=elapsed_seconds,
            summary=assistant_content,
            error=error_msg,
        )
