"""Tests for multi-step agent loop with mock inference."""

import pytest
from friday.agent.loop import AgentLoop, AgentTurnBudget
from friday.inference.mock import MockInferenceBackend
from friday.security.tokens import CapabilityTokenManager
from friday.tools.native_read import SystemInfoTool
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry
from friday.inference.protocol import ModelState, ModelProfile


@pytest.mark.asyncio
async def test_agent_loop_basic_turn():
    inference = MockInferenceBackend()
    await inference.load_model(ModelProfile(name="mock-model", model_dir=""))

    tools = ToolRegistry()
    tools.register(SystemInfoTool())

    token_mgr = CapabilityTokenManager("test-secret")
    policy = PolicyEngine(token_manager=token_mgr)

    loop = AgentLoop(inference=inference, tools=tools, policy=policy)

    events = []
    async for event in loop.run_turn(
        session_id="test-session",
        user_prompt="Hello agent!",
        conversation_history=[],
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.started" in types
    assert "assistant.delta" in types
    assert "turn.completed" in types


@pytest.mark.asyncio
async def test_agent_loop_with_tool_call():
    inference = MockInferenceBackend()
    await inference.load_model(ModelProfile(name="mock-model", model_dir=""))
    # Instruct mock backend to emit a system.info tool call
    inference.mock_tool_calls = [
        {
            "id": "call-1",
            "function": {
                "name": "system.info",
                "arguments": "{}",
            },
        }
    ]

    tools = ToolRegistry()
    tools.register(SystemInfoTool())

    token_mgr = CapabilityTokenManager("test-secret")
    policy = PolicyEngine(token_manager=token_mgr)

    loop = AgentLoop(inference=inference, tools=tools, policy=policy)

    events = []
    # After the tool executes, set mock_tool_calls to None for the next iteration to conclude
    async for event in loop.run_turn(
        session_id="test-session",
        user_prompt="What is my OS?",
        conversation_history=[],
    ):
        events.append(event)
        if event["type"] == "tool.completed":
            inference.mock_tool_calls = None

    types = [e["type"] for e in events]
    assert "tool.requested" in types
    assert "tool.started" in types
    assert "tool.completed" in types
