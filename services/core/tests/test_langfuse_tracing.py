"""Unit and integration tests for Langfuse tracing in Project Friday."""

import pytest
from unittest.mock import MagicMock, patch

from friday.agent.loop import AgentLoop
from friday.inference.mock import MockInferenceBackend
from friday.inference.protocol import ChatMessage, ModelState
from friday.telemetry.langfuse import LangfuseTracer
from friday.tools.native_read import SystemInfoTool
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry


class DummyTokenManager:
    def verify_token(self, token: str, action: str, canonical_args: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_langfuse_tracer_disabled_safe_execution():
    """Verify tracer runs safely as no-op when disabled."""
    tracer = LangfuseTracer(enabled=False)
    assert not tracer.is_active()

    # Context managers should yield None and execute without error
    with tracer.trace_agent_turn(session_id="s1", turn_id="t1", user_prompt="test") as obs:
        assert obs is None

    with tracer.trace_generation(name="test.gen", model="mock") as gen_obs:
        assert gen_obs is None

    with tracer.trace_tool_execution(tool_name="test.tool", call_id="c1", arguments={"a": 1}) as tool_obs:
        assert tool_obs is None

    with tracer.trace_subagent(subagent_name="researcher", conversation_id="conv-1", task_prompt="look up") as sub_obs:
        assert sub_obs is None

    tracer.flush()


@pytest.mark.asyncio
async def test_agent_loop_with_disabled_tracer():
    """Verify AgentLoop runs smoothly with disabled LangfuseTracer."""
    inference = MockInferenceBackend()
    inference.state = ModelState.READY
    inference.mock_responses = ["Hello from Friday!"]
    tools = ToolRegistry()
    tools.register(SystemInfoTool())
    policy = PolicyEngine(token_manager=DummyTokenManager(), safe_roots=["."], approval_level="standard")
    tracer = LangfuseTracer(enabled=False)

    loop = AgentLoop(inference=inference, tools=tools, policy=policy, tracer=tracer)

    events = []
    async for event in loop.run_turn(
        session_id="sess-123",
        user_prompt="Hello",
        conversation_history=[],
    ):
        events.append(event)

    types = [e["type"] for e in events]
    assert "turn.started" in types
    assert "assistant.delta" in types
    assert "turn.completed" in types


@pytest.mark.asyncio
async def test_agent_loop_with_mocked_active_tracer():
    """Verify observations are created and updated when Langfuse tracer is active."""
    mock_client = MagicMock()
    mock_obs = MagicMock()
    mock_client.start_as_current_observation.return_value.__enter__.return_value = mock_obs
    mock_client.start_as_current_observation.return_value.__exit__.return_value = None

    with patch("friday.telemetry.langfuse._CLIENT_AVAILABLE", True), \
         patch("friday.telemetry.langfuse.get_client", return_value=mock_client), \
         patch("friday.telemetry.langfuse.propagate_attributes") as mock_propagate:

        mock_propagate.return_value.__enter__.return_value = None
        mock_propagate.return_value.__exit__.return_value = None

        tracer = LangfuseTracer(enabled=True)
        assert tracer.is_active()

        inference = MockInferenceBackend()
        inference.state = ModelState.READY
        inference.mock_responses = ["Done tracing test"]
        tools = ToolRegistry()
        tools.register(SystemInfoTool())
        policy = PolicyEngine(token_manager=DummyTokenManager(), safe_roots=["."], approval_level="standard")

        loop = AgentLoop(inference=inference, tools=tools, policy=policy, tracer=tracer)

        events = []
        async for event in loop.run_turn(
            session_id="sess-456",
            user_prompt="System check",
            conversation_history=[],
        ):
            events.append(event)

        assert any(e["type"] == "turn.completed" for e in events)

        # Verify start_as_current_observation was called for turn and generation
        call_types = [call.kwargs.get("as_type") for call in mock_client.start_as_current_observation.call_args_list]
        assert "agent" in call_types
        assert "generation" in call_types

        # Verify turn observation update was called with final answer
        assert mock_obs.update.called
