"""Tests for Subagent delegation tools (Phase 12 Milestone 4)."""

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
    ParentCapabilities,
    SubagentRunState,
)
from friday.subagents.runner import SubagentTurnRunner
from friday.tools.base import Tool, ToolResult
from friday.tools.registry import ToolRegistry
from friday.tools.subagent import SubagentCancelTool, SubagentListTool, SubagentRunTool


class SimpleTool(Tool):
    def __init__(self, name: str, risk: int = 0) -> None:
        self.name = name
        self.description = f"Simple tool {name}"
        self.risk_level = risk
        self.requires_approval = (risk >= 2)
        self.parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.name, call_id=call_id, success=True, output="ok")


class SimpleInference(InferenceBackend):
    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, state=ModelState.READY)

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def load_model(self, profile: ModelProfile) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        yield InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content="Subagent finished task.")
        yield InferenceEvent(type=InferenceEventType.USAGE, prompt_tokens=50, completion_tokens=10)


@pytest.fixture
async def setup_subagent_tools(tmp_path):
    db_path = tmp_path / "tools_test.db"
    db_mgr = SubagentDatabaseManager(db_path)
    await db_mgr.initialize()

    registry = ToolRegistry()
    read_tool = SimpleTool("fs.read", risk=0)
    write_tool = SimpleTool("fs.write", risk=1)
    exec_tool = SimpleTool("term.exec", risk=2)
    registry.register(read_tool)
    registry.register(write_tool)
    registry.register(exec_tool)

    inference = SimpleInference()
    runner = SubagentTurnRunner(inference=inference, tools=registry, db=db_mgr)

    workspace = str(tmp_path)
    parent_caps = ParentCapabilities(
        session_id="parent-s1",
        depth=0,
        allowed_tool_ids=["fs.read", "fs.write", "term.exec"],
        max_risk_level=2,
        workspace_root=workspace,
        token_budget=16000,
        iteration_budget=15,
        duration_seconds_budget=300,
    )

    run_tool = SubagentRunTool(
        runner=runner,
        parent_capabilities_provider=lambda: parent_caps,
        parent_live_tools_provider=lambda: {"fs.read", "fs.write", "term.exec"},
        tool_registry=registry,
        is_depth_0_caller=lambda: True,
    )

    list_tool = SubagentListTool(db=db_mgr)
    cancel_tool = SubagentCancelTool(db=db_mgr)

    yield run_tool, list_tool, cancel_tool, db_mgr, parent_caps
    await db_mgr.close()


@pytest.mark.asyncio
async def test_subagent_run_tool_risk_classification(setup_subagent_tools):
    """Verify dynamic risk classification based on requested tools and risk ceilings."""
    run_tool, _, _, _, _ = setup_subagent_tools

    # Risk 0: read-only tools
    assert run_tool.classify_risk({"allowed_tool_ids": ["fs.read"], "max_risk_level": 0}) == 0

    # Risk 1: write tool
    assert run_tool.classify_risk({"allowed_tool_ids": ["fs.write"], "max_risk_level": 0}) == 1
    assert run_tool.classify_risk({"allowed_tool_ids": ["fs.read"], "max_risk_level": 1}) == 1

    # Risk 2: exec tool or explicit risk 2
    assert run_tool.classify_risk({"allowed_tool_ids": ["term.exec"], "max_risk_level": 0}) == 2
    assert run_tool.classify_risk({"allowed_tool_ids": ["fs.read"], "max_risk_level": 2}) == 2


@pytest.mark.asyncio
async def test_subagent_run_tool_caller_depth_rejection(setup_subagent_tools):
    """Verify non-depth-0 callers are strictly denied delegation."""
    run_tool, _, _, _, _ = setup_subagent_tools

    # Simulate subagent caller (depth 1)
    run_tool.is_depth_0_caller = lambda: False

    res = await run_tool.execute(
        call_id="c-1",
        arguments={
            "role": "RecursiveAgent",
            "task_prompt": "Try recursive delegation",
        },
    )
    assert res.success is False
    assert "PolicyDeniedError" in res.error
    assert "depth-1 invariant" in res.error


@pytest.mark.asyncio
async def test_subagent_run_tool_execution(setup_subagent_tools):
    """Verify successful execution, fenced output formatting, and metadata."""
    run_tool, list_tool, _, db_mgr, parent_caps = setup_subagent_tools

    res = await run_tool.execute(
        call_id="call-valid",
        arguments={
            "role": "FileAuditor",
            "task_prompt": "Audit temporary files",
            "allowed_tool_ids": ["fs.read"],
            "max_risk_level": 0,
            "token_budget": 2000,
        },
    )

    assert res.success is True
    assert "=== SUBAGENT EXECUTION RESULT (UNTRUSTED CHILD OUTPUT) ===" in res.output
    assert "Subagent finished task." in res.output
    assert res.metadata["role"] == "FileAuditor"
    assert res.metadata["state"] == "completed"
    assert res.metadata["tokens_consumed"] == 60

    # Verify run is visible via subagent.list
    list_res = await list_tool.execute("list-call", {"session_id": parent_caps.session_id})
    assert list_res.success is True
    assert "FileAuditor" in list_res.output
    assert "completed" in list_res.output


@pytest.mark.asyncio
async def test_subagent_cancel_tool(setup_subagent_tools, tmp_path):
    """Verify subagent.cancel tool requests cancellation."""
    _, _, cancel_tool, db_mgr, parent_caps = setup_subagent_tools
    workspace = str(tmp_path)

    from friday.subagents.models import SubagentSpec
    spec = SubagentSpec(
        role="Target",
        task_prompt="To be cancelled",
        parent_session_id=parent_caps.session_id,
        parent_turn_id="turn-cancel",
        workspace_root=workspace,
    )
    run_id = await db_mgr.reserve_subagent_run(spec)

    # Cancel via tool
    res = await cancel_tool.execute("cancel-call", {"run_id": run_id})
    assert res.success is True
    assert "Cancellation requested" in res.output

    run = await db_mgr.get_run(run_id)
    assert run["state"] == SubagentRunState.STOPPING
