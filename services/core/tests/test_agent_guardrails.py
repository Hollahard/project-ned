"""Tests for Agent Loop iteration, timeout, and consecutive failure guardrails."""

import asyncio
from pathlib import Path
from typing import AsyncIterator, List
import pytest

from friday.agent.loop import AgentLoop, AgentTurnBudget, AgentBudgetExceededError
from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    InferenceBackend,
    InferenceEvent,
    InferenceEventType,
)
from friday.security.tokens import CapabilityTokenManager
from friday.tools.base import Tool, ToolResult
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry


class LoopbackTool(Tool):
    name = "loop.fail"
    description = "A tool that always fails for testing consecutive failure guardrails."
    risk_level = 0
    requires_approval = False

    async def execute(self, call_id: str, arguments: dict) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=False,
            output="",
            error="Simulated failure for guardrail test",
        )


class MockInfinitelyLoopingBackend(InferenceBackend):
    """Generates an endless loop of tool calls to trip iteration and failure guardrails."""

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        # Always request the tool
        yield InferenceEvent(
            type=InferenceEventType.TOOL_CALL,
            tool_call={
                "id": "call-1",
                "type": "function",
                "function": {"name": "loop.fail", "arguments": "{}"},
            },
        )

    async def health(self):
        from friday.inference.protocol import BackendHealth, ModelState
        return BackendHealth(healthy=True, state=ModelState.READY)

    async def list_models(self):
        return []

    async def load_model(self, profile):
        pass

    async def unload_model(self):
        pass


@pytest.mark.asyncio
async def test_agent_turn_budget_max_iterations():
    budget = AgentTurnBudget(max_iterations=3, max_consecutive_tool_failures=10)
    backend = MockInfinitelyLoopingBackend()
    registry = ToolRegistry()
    registry.register(LoopbackTool())
    policy = PolicyEngine(token_manager=CapabilityTokenManager("secret"))

    loop = AgentLoop(inference=backend, tools=registry, policy=policy)

    events = []
    async for event in loop.run_turn(
        session_id="sess-1",
        user_prompt="Run loop",
        conversation_history=[],
        budget=budget,
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.failed" in types
    failed_event = next(e for e in events if e["type"] == "turn.failed")
    assert "maximum iterations limit" in failed_event["payload"]["error"]


@pytest.mark.asyncio
async def test_agent_turn_budget_consecutive_failures():
    # 2 consecutive tool failures should abort immediately
    budget = AgentTurnBudget(max_iterations=10, max_consecutive_tool_failures=2)
    backend = MockInfinitelyLoopingBackend()
    registry = ToolRegistry()
    registry.register(LoopbackTool())
    policy = PolicyEngine(token_manager=CapabilityTokenManager("secret"))

    loop = AgentLoop(inference=backend, tools=registry, policy=policy)

    events = []
    async for event in loop.run_turn(
        session_id="sess-2",
        user_prompt="Fail twice",
        conversation_history=[],
        budget=budget,
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.failed" in types
    failed_event = next(e for e in events if e["type"] == "turn.failed")
    assert "maximum consecutive tool failures reached" in failed_event["payload"]["error"]


@pytest.mark.asyncio
async def test_agent_turn_budget_wall_clock_timeout():
    # 0 second timeout should fail on first limit check
    budget = AgentTurnBudget(max_wall_clock_seconds=0)
    backend = MockInfinitelyLoopingBackend()
    registry = ToolRegistry()
    registry.register(LoopbackTool())
    policy = PolicyEngine(token_manager=CapabilityTokenManager("secret"))

    loop = AgentLoop(inference=backend, tools=registry, policy=policy)

    # Force a slight sleep so elapsed > 0
    await asyncio.sleep(0.01)

    events = []
    async for event in loop.run_turn(
        session_id="sess-3",
        user_prompt="Timeout test",
        conversation_history=[],
        budget=budget,
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.failed" in types
    failed_event = next(e for e in events if e["type"] == "turn.failed")
    assert "wall-clock timeout" in failed_event["payload"]["error"]
