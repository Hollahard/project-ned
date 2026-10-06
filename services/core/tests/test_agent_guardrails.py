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
    parameters_schema = {"type": "object", "properties": {}}

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


class MockCodingBackend(InferenceBackend):
    def __init__(self, target_path: str, token_manager: CapabilityTokenManager):
        self.step = 0
        self.target_path = target_path
        self.token_manager = token_manager

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        import json
        self.step += 1
        if self.step == 1:
            yield InferenceEvent(
                type=InferenceEventType.TOOL_CALL,
                tool_call={
                    "id": "call-write",
                    "type": "function",
                    "function": {
                        "name": "filesystem.write",
                        "arguments": json.dumps({"path": self.target_path, "content": "x = 1"}),
                    },
                },
            )
        elif self.step == 2:
            yield InferenceEvent(
                type=InferenceEventType.TOKEN_DELTA,
                content="I wrote the file and I am ready to stop.",
            )
        elif self.step == 3:
            cmd = "Write-Output 'pytest: 1 passed'"
            token, _ = self.token_manager.mint_token("terminal.exec", {"command": cmd})
            yield InferenceEvent(
                type=InferenceEventType.TOOL_CALL,
                tool_call={
                    "id": "call-test",
                    "type": "function",
                    "function": {
                        "name": "terminal.exec",
                        "arguments": json.dumps({"command": cmd, "capability_token": token}),
                    },
                },
            )
        else:
            yield InferenceEvent(
                type=InferenceEventType.TOKEN_DELTA,
                content="Tests passed and work verified.",
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
async def test_agent_verify_on_stop_rule(tmp_path: Path):
    from friday.tools.filesystem_write import FilesystemWriteTool
    from friday.tools.terminal_exec import TerminalExecTool

    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    target_file = str(safe_root / "code.py")

    token_mgr = CapabilityTokenManager("secret")
    backend = MockCodingBackend(target_file, token_manager=token_mgr)
    registry = ToolRegistry()
    registry.register(FilesystemWriteTool(safe_roots=[safe_root]))
    registry.register(TerminalExecTool(safe_roots=[safe_root]))


    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])

    loop = AgentLoop(inference=backend, tools=registry, policy=policy)

    events = []
    async for event in loop.run_turn(
        session_id="sess-verify",
        user_prompt="Write code and verify",
        conversation_history=[],
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.started" in types
    assert "turn.completed" in types

    # Completed event should record verified: True
    completed_event = next(e for e in events if e["type"] == "turn.completed")
    assert completed_event["payload"]["verified"] is True
    assert backend.step >= 4

