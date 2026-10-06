"""Multi-step agent loop with guardrails, cancellation, and strict policy enforcement."""

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncIterator, List

from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    InferenceBackend,
    InferenceEventType,
)
from friday.tools.base import ToolResult
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentTurnBudget:
    def __init__(
        self,
        max_iterations: int = 20,
        max_wall_clock_seconds: int = 900,
        max_consecutive_tool_failures: int = 5,
    ) -> None:
        self.max_iterations = max_iterations
        self.max_wall_clock_seconds = max_wall_clock_seconds
        self.max_consecutive_tool_failures = max_consecutive_tool_failures
        self.start_time = time.time()
        self.iteration = 0
        self.consecutive_failures = 0

    def check_limits(self) -> None:
        elapsed = time.time() - self.start_time
        if elapsed > self.max_wall_clock_seconds:
            raise TimeoutError(f"Turn exceeded max wall-clock time ({self.max_wall_clock_seconds}s)")
        if self.iteration >= self.max_iterations:
            raise RuntimeError(f"Turn exceeded max iterations ({self.max_iterations})")
        if self.consecutive_failures >= self.max_consecutive_tool_failures:
            raise RuntimeError(
                f"Turn aborted after {self.max_consecutive_tool_failures} consecutive tool failures"
            )


class AgentLoop:
    """Manages multi-turn multi-step reasoning and tool execution loop."""

    def __init__(
        self,
        inference: InferenceBackend,
        tools: ToolRegistry,
        policy: PolicyEngine,
    ) -> None:
        self.inference = inference
        self.tools = tools
        self.policy = policy

    async def run_turn(
        self,
        session_id: str,
        user_prompt: str,
        conversation_history: List[ChatMessage],
        model_name: str = "default",
        budget: AgentTurnBudget | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict]:
        """Execute one complete turn of the agent loop, yielding streaming events."""
        turn_id = str(uuid.uuid4())
        budget = budget or AgentTurnBudget()

        yield {
            "type": "turn.started",
            "session_id": session_id,
            "turn_id": turn_id,
            "payload": {"prompt": user_prompt},
        }

        # Context order: system prompt, history, user request
        messages: List[ChatMessage] = [
            ChatMessage(
                role="system",
                content=(
                    "You are Project Friday, an AI desktop assistant. "
                    "You have access to tools for inspecting the system and workspace. "
                    "Use tools when needed to verify facts before answering."
                ),
            )
        ]
        messages.extend(conversation_history)
        messages.append(ChatMessage(role="user", content=user_prompt))

        assistant_content = ""
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    yield {
                        "type": "turn.canceled",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {"partial_answer": assistant_content},
                    }
                    return

                budget.check_limits()
                budget.iteration += 1

                tool_schemas = self.tools.get_schemas()
                request = ChatRequest(
                    model=model_name,
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                )

                assistant_content = ""
                tool_calls = []

                async for event in self.inference.generate(request):
                    if cancel_event and cancel_event.is_set():
                        yield {
                            "type": "turn.canceled",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "payload": {"partial_answer": assistant_content},
                        }
                        return

                    if event.type == InferenceEventType.TOKEN_DELTA:
                        assistant_content += event.content
                        yield {
                            "type": "assistant.delta",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "payload": {"content": event.content},
                        }
                    elif event.type == InferenceEventType.REASONING_DELTA:
                        yield {
                            "type": "reasoning.delta",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "payload": {"reasoning": event.content},
                        }
                    elif event.type == InferenceEventType.TOOL_CALL:
                        if event.tool_call:
                            tool_calls.append(event.tool_call)
                    elif event.type == InferenceEventType.ERROR:
                        yield {
                            "type": "error",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "payload": {"error": event.content},
                        }
                        return

                # Append the assistant's response to the context
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls if tool_calls else None,
                    )
                )

                # If no tool calls were requested, turn is complete!
                if not tool_calls:
                    yield {
                        "type": "turn.completed",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {"final_answer": assistant_content},
                    }
                    break

                # Handle proposed tool calls
                for tc in tool_calls:
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

                    yield {
                        "type": "tool.requested",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {"call_id": call_id, "tool": name, "arguments": args},
                    }

                    tool_instance = self.tools.get(name)
                    if not tool_instance:
                        res = ToolResult(
                            tool_name=name,
                            call_id=call_id,
                            success=False,
                            output="",
                            error=f"Tool not found: {name}",
                        )
                    else:
                        decision = self.policy.evaluate(tool_instance, args)
                        if decision.requires_approval:
                            yield {
                                "type": "approval.required",
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "payload": {
                                    "call_id": call_id,
                                    "tool": name,
                                    "reason": decision.reason,
                                    "canonical_args": decision.canonical_args,
                                },
                            }
                            # In headless/unapproved runs without approval token, halt tool exec
                            res = ToolResult(
                                tool_name=name,
                                call_id=call_id,
                                success=False,
                                output="",
                                error=f"Approval required: {decision.reason}",
                            )
                        elif not decision.allowed:
                            res = ToolResult(
                                tool_name=name,
                                call_id=call_id,
                                success=False,
                                output="",
                                error=f"Policy rejected: {decision.reason}",
                            )
                        else:
                            yield {
                                "type": "tool.started",
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "payload": {"call_id": call_id, "tool": name},
                            }
                            res = await tool_instance.execute(call_id, args)

                    if res.success:
                        budget.consecutive_failures = 0
                    else:
                        budget.consecutive_failures += 1

                    yield {
                        "type": "tool.completed",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {
                            "call_id": call_id,
                            "tool": name,
                            "success": res.success,
                            "output": res.output,
                            "error": res.error,
                        },
                    }

                    # Feed tool result back as untrusted tool role
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=res.output if res.success else f"Error: {res.error}",
                            tool_call_id=call_id,
                        )
                    )
        except asyncio.CancelledError:
            yield {
                "type": "turn.canceled",
                "session_id": session_id,
                "turn_id": turn_id,
                "payload": {"partial_answer": assistant_content},
            }
            return
