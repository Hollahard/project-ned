"""Tests for Subagent supervised runner, watchdog timeout, and cancellation (Phase 12 Milestone 3)."""

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict
import pytest

from friday.inference.protocol import (
    ChatMessage,
    ChatRequest,
    HealthStatus,
    InferenceBackend,
    InferenceEvent,
    InferenceEventType,
    ModelInfo,
    ModelProfile,
    ModelState,
)
from friday.subagents.db import SubagentDatabaseManager
from friday.subagents.models import (
    PolicyDeniedError,
    SubagentRunState,
    SubagentSpec,
)
from friday.subagents.runner import SubagentExecutionGuard, SubagentTurnRunner
from friday.tools.base import Tool, ToolResult
from friday.tools.registry import ToolRegistry


class DummyTool(Tool):
    name = "dummy.tool"
    description = "Dummy test tool"
    risk_level = 0
    requires_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            call_id=call_id,
            success=True,
            output=f"Executed with {arguments}",
        )


class DummyInferenceBackend(InferenceBackend):
    """Controllable backend for runner tests."""

    def __init__(self, responses: list[list[InferenceEvent]] | None = None) -> None:
        self.responses = responses or []
        self.call_index = 0

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, state=ModelState.READY)

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def load_model(self, profile: ModelProfile) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        if self.call_index < len(self.responses):
            events = self.responses[self.call_index]
            self.call_index += 1
            for event in events:
                yield event
        else:
            yield InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Default answer")


@pytest.fixture
async def setup_runner(tmp_path):
    db_file = tmp_path / "runner_test.db"
    db_mgr = SubagentDatabaseManager(db_file)
    await db_mgr.initialize()

    registry = ToolRegistry()
    dummy = DummyTool()
    registry.register(dummy)

    yield db_mgr, registry
    await db_mgr.close()


@pytest.mark.asyncio
async def test_subagent_runner_happy_path(setup_runner, tmp_path):
    """Verify clean execution when model completes without tool calls."""
    db_mgr, registry = setup_runner
    workspace = str(tmp_path)

    events = [
        [
            InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Task completed successfully."),
            InferenceEvent(type=InferenceEventType.USAGE, prompt_tokens=100, completion_tokens=20),
        ]
    ]
    inference = DummyInferenceBackend(responses=events)
    runner = SubagentTurnRunner(inference=inference, tools=registry, db=db_mgr)

    spec = SubagentSpec(
        role="Worker",
        task_prompt="Inspect files",
        parent_session_id="session-run-1",
        parent_turn_id="turn-1",
        workspace_root=workspace,
        allowed_tool_ids=["dummy.tool"],
    )

    result = await runner.execute_subagent(
        spec=spec,
        parent_live_tools_provider=lambda: {"dummy.tool"},
    )

    assert result.state == SubagentRunState.COMPLETED
    assert result.tokens_consumed == 120
    assert result.summary == "Task completed successfully."
    assert result.error is None

    # Check DB record
    db_run = await db_mgr.get_run(result.run_id)
    assert db_run["state"] == SubagentRunState.COMPLETED
    assert db_run["consumed_tokens"] == 120


@pytest.mark.asyncio
async def test_subagent_runner_dynamic_tool_revocation(setup_runner, tmp_path):
    """Verify tool call is blocked if live parent authority revokes it mid-turn."""
    db_mgr, registry = setup_runner
    workspace = str(tmp_path)

    # First turn proposes tool call, second turn finishes
    events = [
        [
            InferenceEvent(
                type=InferenceEventType.TOOL_CALL,
                tool_call={
                    "id": "c-1",
                    "function": {"name": "dummy.tool", "arguments": '{"path": "test.txt"}'},
                },
            ),
        ],
        [
            InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Understood tool rejection."),
        ],
    ]
    inference = DummyInferenceBackend(responses=events)
    runner = SubagentTurnRunner(inference=inference, tools=registry, db=db_mgr)

    spec = SubagentSpec(
        role="RevokedWorker",
        task_prompt="Try revoked tool",
        parent_session_id="session-revoked",
        parent_turn_id="turn-revoked",
        workspace_root=workspace,
        allowed_tool_ids=["dummy.tool"],
    )

    # Parent live authority returns empty set (tool was revoked!)
    result = await runner.execute_subagent(
        spec=spec,
        parent_live_tools_provider=lambda: set(),  # Parent has no permitted tools
    )

    # Runner finishes, and tool call was rejected with PolicyDeniedError
    assert result.state == SubagentRunState.COMPLETED
    assert result.summary == "Understood tool rejection."


@pytest.mark.asyncio
async def test_subagent_runner_watchdog_timeout(setup_runner, tmp_path):
    """Verify watchdog timeout halts long-running execution."""
    db_mgr, registry = setup_runner
    workspace = str(tmp_path)

    class HangingInference(InferenceBackend):
        async def health(self) -> HealthStatus:
            return HealthStatus(healthy=True, state=ModelState.READY)

        async def list_models(self) -> list[ModelInfo]:
            return []

        async def load_model(self, profile: ModelProfile) -> None:
            pass

        async def unload_model(self) -> None:
            pass

        async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
            # Simulate hung model call
            await asyncio.sleep(10.0)
            yield InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Never arrived")

    runner = SubagentTurnRunner(inference=HangingInference(), tools=registry, db=db_mgr)

    # Set duration budget to 5 seconds
    spec = SubagentSpec(
        role="Hanger",
        task_prompt="Sleep forever",
        parent_session_id="session-timeout",
        parent_turn_id="turn-timeout",
        workspace_root=workspace,
        duration_seconds_budget=5,  # Min allowed by spec is 5s
    )

    start = asyncio.get_event_loop().time()
    result = await runner.execute_subagent(
        spec=spec,
        parent_live_tools_provider=lambda: {"dummy.tool"},
    )
    elapsed = asyncio.get_event_loop().time() - start

    assert result.state == SubagentRunState.TIMEOUT
    assert "timeout" in result.error.lower()
    assert elapsed < 7.0  # Stopped around 5s watchdog mark


@pytest.mark.asyncio
async def test_subagent_runner_parent_cancellation(setup_runner, tmp_path):
    """Verify parent cancellation immediately aborts subagent."""
    db_mgr, registry = setup_runner
    workspace = str(tmp_path)

    parent_cancel = asyncio.Event()

    class CancellableInference(InferenceBackend):
        async def health(self) -> HealthStatus:
            return HealthStatus(healthy=True, state=ModelState.READY)

        async def list_models(self) -> list[ModelInfo]:
            return []

        async def load_model(self, profile: ModelProfile) -> None:
            pass

        async def unload_model(self) -> None:
            pass

        async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
            # Wait for cancellation
            while not parent_cancel.is_set():
                await asyncio.sleep(0.05)
            yield InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Cancelled mid-stream")

    runner = SubagentTurnRunner(inference=CancellableInference(), tools=registry, db=db_mgr)
    spec = SubagentSpec(
        role="CancelTarget",
        task_prompt="Cancel me",
        parent_session_id="session-cancel-prop",
        parent_turn_id="turn-cancel-prop",
        workspace_root=workspace,
    )

    # Trigger cancellation after 0.1s
    async def _cancel_soon():
        await asyncio.sleep(0.1)
        parent_cancel.set()

    cancel_task = asyncio.create_task(_cancel_soon())
    result = await runner.execute_subagent(
        spec=spec,
        parent_live_tools_provider=lambda: {"dummy.tool"},
        parent_cancel_event=parent_cancel,
    )
    await cancel_task

    assert result.state == SubagentRunState.CANCELLED
    assert "cancelled" in result.error.lower()
