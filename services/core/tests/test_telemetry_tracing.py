"""Comprehensive unit and integration test suite for Telemetry, Tracing, and Observability (Phase 13).

Invariants verified:
1. Dual-Sink Architecture: local JSONL is sovereign and durable; Langfuse mirrors when active.
2. Security & Redaction: capability tokens, API keys, and Bearer secrets scrubbed; 64 KiB cap.
3. Multi-Agent Agent Graph: subagents traced as as_type='agent' nesting child generations and tools.
4. Chain-of-Thought / Reasoning: thinking deltas and token usage details captured on generations.
5. Offline Resilience: gracefully operates with zero exceptions when Langfuse is offline or disabled.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import MagicMock, patch
import pytest

from friday.agent.loop import AgentLoop
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
from friday.scheduler.models import (
    JobPermissionSnapshot,
    JobRun,
    RunState,
    ScheduleType,
    ScheduledJob,
)
from friday.scheduler.worker import ScheduledExecutionGuard, SchedulerWorker
from friday.subagents.models import ParentCapabilities, SubagentSpec
from friday.subagents.runner import SubagentTurnRunner
from friday.telemetry.langfuse import LangfuseSink, LangfuseTracer
from friday.telemetry.manager import ActiveTurnTrace, TelemetryManager
from friday.telemetry.tracer import (
    LocalJsonlSink,
    MAX_PAYLOAD_BYTES,
    ObservationRecord,
    ObservationType,
    TraceRecord,
    redact_sensitive_text,
    sanitize_payload,
)
from friday.tools.base import Tool, ToolResult
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry


class DummyTokenManager:
    def verify_token(self, token: str, action: str, canonical_args: str) -> bool:
        return True


class DummyTool(Tool):
    def __init__(self, name: str = "test.tool", output: str = "ok", risk_level: int = 0) -> None:
        self.name = name
        self.description = f"Dummy tool {name}"
        self.risk_level = risk_level
        self.requires_approval = False
        self.parameters_schema = {"type": "object", "properties": {}}
        self._output = output

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.name, call_id=call_id, success=True, output=self._output)


class StreamingInferenceMock(InferenceBackend):
    def __init__(self, reasoning: str = "", deltas: List[str] = None, prompt_tokens: int = 15, completion_tokens: int = 25) -> None:
        self.reasoning = reasoning
        self.deltas = deltas or ["Here is ", "the response."]
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, state=ModelState.READY)

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def load_model(self, profile: ModelProfile) -> None:
        pass

    async def unload_model(self) -> None:
        pass

    async def generate(self, request: ChatRequest) -> AsyncIterator[InferenceEvent]:
        if self.reasoning:
            yield InferenceEvent(type=InferenceEventType.REASONING_DELTA, content=self.reasoning)
        for chunk in self.deltas:
            yield InferenceEvent(type=InferenceEventType.TOKEN_DELTA, content=chunk)
        yield InferenceEvent(
            type=InferenceEventType.USAGE,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


def test_redaction_and_sanitization():
    """Verify secrets, tokens, authorization headers, and large payloads are scrubbed."""
    # 1. Capability token scrubbing
    raw_token = "12345678-1234-1234-1234-123456789abc.abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    text = f"Using capability token {raw_token} to authorize"
    redacted = redact_sensitive_text(text)
    assert raw_token not in redacted
    assert "[REDACTED_SECRET]" in redacted

    # 2. API key scrubbing
    raw_key = "sk-lf-ce66bbc3-bc87-4be6-a2e9-824ec5d1af9c"
    text_key = f"Connecting with key {raw_key} to Langfuse"
    redacted_key = redact_sensitive_text(text_key)
    assert raw_key not in redacted_key
    assert "[REDACTED_SECRET]" in redacted_key

    # 3. Bearer header scrubbing
    raw_bearer = "Authorization: Bearer mySecretToken1234567890abcdef"
    redacted_bearer = redact_sensitive_text(raw_bearer)
    assert "mySecretToken" not in redacted_bearer
    assert "[REDACTED_SECRET]" in redacted_bearer

    # 4. 64 KiB ceiling truncation
    massive_text = "A" * (MAX_PAYLOAD_BYTES + 5000)
    capped = redact_sensitive_text(massive_text)
    assert len(capped.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert "... [TRUNCATED 64 KiB]" in capped

    # 5. Dict sanitization removes keys ending with secret/token and api_key
    payload = {
        "normal_key": "safe data",
        "nested_dict": {
            "api_key": "sk-lf-1234567890abcdef123",
            "approval_token": "secret_token_value",
            "client_secret": "sensitive_value",
        },
        "items": ["safe item", raw_key],
    }
    sanitized = sanitize_payload(payload)
    assert "approval_token" not in sanitized["nested_dict"]
    assert "client_secret" not in sanitized["nested_dict"]
    assert "api_key" not in sanitized["nested_dict"]
    assert sanitized["items"][1] == "[REDACTED_SECRET]"


@pytest.mark.asyncio
async def test_local_jsonl_sink(tmp_path: Path):
    """Verify LocalJsonlSink durably appends atomic JSON lines partitioned by date."""
    sink = LocalJsonlSink(logs_dir=tmp_path)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expected_file = tmp_path / f"trace_{date_str}.jsonl"

    obs = ObservationRecord(
        trace_id="trace-123",
        observation_type=ObservationType.GENERATION,
        name="test-generation",
        model="exl3-test",
        thinking="Step 1: analyze problem",
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        input={"prompt": "Hello"},
        output="World",
    )

    trace = TraceRecord(
        id="trace-123",
        session_id="session-abc",
        user_id="local_user",
        name="chat-turn",
        input={"user_message": "Hello"},
        output="World",
        tags=["unit-test"],
        observations=[obs],
    )

    await sink.write_trace(trace)
    assert expected_file.exists()

    content = expected_file.read_text(encoding="utf-8").strip()
    data = json.loads(content)
    assert data["id"] == "trace-123"
    assert data["session_id"] == "session-abc"
    assert len(data["observations"]) == 1
    assert data["observations"][0]["thinking"] == "Step 1: analyze problem"
    assert data["observations"][0]["usage"]["total_tokens"] == 30


@pytest.mark.asyncio
async def test_telemetry_manager_dual_sink_lifecycle(tmp_path: Path):
    """Verify TelemetryManager coordinates LocalJsonlSink and LangfuseSink without errors."""
    mock_langfuse = MagicMock(spec=LangfuseSink)
    mock_langfuse.is_active.return_value = True
    mock_span = MagicMock()
    mock_langfuse.trace_turn.return_value.__enter__.return_value = mock_span
    mock_langfuse.trace_turn.return_value.__exit__.return_value = None

    telemetry = TelemetryManager(logs_dir=tmp_path, langfuse_sink=mock_langfuse)
    assert telemetry.is_langfuse_enabled()

    async with telemetry.start_turn_trace(
        session_id="session-dual",
        user_prompt="Run dual check",
        tags=["friday-desktop", "test"],
    ) as active_trace:
        active_trace.record_generation(
            model="local-exl3",
            input_messages=[{"role": "user", "content": "hi"}],
            output_text="greetings",
            prompt_tokens=12,
            completion_tokens=8,
            thinking="internal CoT reasoning",
        )
        active_trace.record_tool_call(
            tool_name="filesystem.read",
            arguments={"path": "test.txt"},
            output="file content",
        )
        active_trace.record_subagent_run(
            role="Explorer",
            task_prompt="find files",
            summary="found 3 files",
            tokens_consumed=150,
            tool_calls_count=2,
        )
        await active_trace.complete(final_answer="All tasks done.")

    # Check local JSONL log
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = tmp_path / f"trace_{date_str}.jsonl"
    assert log_file.exists()
    trace_data = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert trace_data["session_id"] == "session-dual"
    assert len(trace_data["observations"]) == 3
    assert trace_data["observations"][0]["observation_type"] == "generation"
    assert trace_data["observations"][1]["observation_type"] == "tool"
    assert trace_data["observations"][2]["observation_type"] == "agent"

    # Check Langfuse flush was invoked
    assert mock_langfuse.flush.called


@pytest.mark.asyncio
async def test_agent_loop_thinking_and_usage_capture(tmp_path: Path):
    """Verify AgentLoop captures REASONING_DELTA and USAGE into Langfuse generation and local trace."""
    mock_client = MagicMock()
    mock_turn_obs = MagicMock()
    mock_gen_obs = MagicMock()

    def mock_start_obs(*args, **kwargs):
        as_type = kwargs.get("as_type")
        cm = MagicMock()
        if as_type == "generation":
            cm.__enter__.return_value = mock_gen_obs
        else:
            cm.__enter__.return_value = mock_turn_obs
        cm.__exit__.return_value = None
        return cm

    mock_client.start_as_current_observation.side_effect = mock_start_obs

    inference = StreamingInferenceMock(
        reasoning="I need to inspect the system first.",
        deltas=["All systems ", "operational."],
        prompt_tokens=42,
        completion_tokens=18,
    )
    tools = ToolRegistry()
    tools.register(DummyTool(name="test.tool"))
    policy = PolicyEngine(token_manager=DummyTokenManager(), safe_roots=["."], approval_level="standard")

    with patch("friday.telemetry.langfuse._CLIENT_AVAILABLE", True), \
         patch("friday.telemetry.langfuse.get_client", return_value=mock_client), \
         patch("friday.telemetry.langfuse.propagate_attributes") as mock_propagate:

        mock_propagate.return_value.__enter__.return_value = None
        mock_propagate.return_value.__exit__.return_value = None

        tracer = LangfuseTracer(enabled=True)
        telemetry = TelemetryManager(logs_dir=tmp_path, langfuse_sink=tracer)
        loop = AgentLoop(inference=inference, tools=tools, policy=policy, tracer=tracer, telemetry=telemetry)

        events = []
        async for event in loop.run_turn(
            session_id="sess-reasoning",
            user_prompt="Run status check",
            conversation_history=[],
        ):
            events.append(event)

        # Verify reasoning.delta event was emitted to client
        reasoning_events = [e for e in events if e["type"] == "reasoning.delta"]
        assert len(reasoning_events) == 1
        assert reasoning_events[0]["payload"]["reasoning"] == "I need to inspect the system first."

        # Verify gen_obs.update received thinking metadata and usage_details
        assert mock_gen_obs.update.called
        update_call = mock_gen_obs.update.call_args.kwargs
        assert update_call.get("metadata", {}).get("thinking") == "I need to inspect the system first."
        assert update_call.get("usage_details", {}).get("prompt_tokens") == 42
        assert update_call.get("usage_details", {}).get("completion_tokens") == 18
        assert update_call.get("usage_details", {}).get("total_tokens") == 60

        # Verify local sink recorded generation with thinking
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = tmp_path / f"trace_{date_str}.jsonl"
        assert log_file.exists()
        trace_data = json.loads(log_file.read_text(encoding="utf-8").strip())
        gen_obs = trace_data["observations"][0]
        assert gen_obs["thinking"] == "I need to inspect the system first."
        assert gen_obs["usage"]["total_tokens"] == 60


@pytest.mark.asyncio
async def test_subagent_agent_graph_nesting():
    """Verify subagent runner traces with as_type='agent' and nests child generation & tools."""
    mock_tracer = MagicMock(spec=LangfuseTracer)
    mock_tracer.is_active.return_value = True

    mock_agent_obs = MagicMock()
    mock_gen_obs = MagicMock()
    mock_tool_obs = MagicMock()

    mock_tracer.trace_subagent.return_value.__enter__.return_value = mock_agent_obs
    mock_tracer.trace_subagent.return_value.__exit__.return_value = None
    mock_tracer.trace_generation.return_value.__enter__.return_value = mock_gen_obs
    mock_tracer.trace_generation.return_value.__exit__.return_value = None
    mock_tracer.trace_tool_execution.return_value.__enter__.return_value = mock_tool_obs
    mock_tracer.trace_tool_execution.return_value.__exit__.return_value = None

    inference = StreamingInferenceMock(deltas=["Subagent task completed."])
    tools = ToolRegistry()
    tools.register(DummyTool(name="read_file"))

    mock_db = MagicMock()
    mock_db.reserve_subagent_run = MagicMock()
    async def _mock_reserve(spec, run_id=None):
        return run_id or "run-sub-1"
    mock_db.reserve_subagent_run.side_effect = _mock_reserve

    mock_db.complete_subagent_run = MagicMock()
    async def _mock_complete(*args, **kwargs):
        pass
    mock_db.complete_subagent_run.side_effect = _mock_complete

    runner = SubagentTurnRunner(
        inference=inference,
        tools=tools,
        db=mock_db,
        tracer=mock_tracer,
    )

    spec = SubagentSpec(
        parent_session_id="parent-session-1",
        parent_turn_id="turn-parent-1",
        role="Researcher",
        task_prompt="Gather documentation",
        allowed_tool_ids=["read_file"],
        workspace_root=".",
    )

    result = await runner.execute_subagent(
        spec=spec,
        parent_live_tools_provider=lambda: {"read_file"},
    )

    assert result.role == "Researcher"
    # Verify trace_subagent was called with role and task_prompt
    assert mock_tracer.trace_subagent.called
    subagent_call = mock_tracer.trace_subagent.call_args.kwargs
    assert subagent_call["role"] == "Researcher"
    assert subagent_call["task_prompt"] == "Gather documentation"

    # Verify trace_generation was called for child model generation
    assert mock_tracer.trace_generation.called

    # Verify agent observation update was called with final summary
    assert mock_agent_obs.update.called
    assert mock_agent_obs.update.call_args.kwargs["output"]["summary"] == "Subagent task completed."


@pytest.mark.asyncio
async def test_offline_resilience_zero_exceptions():
    """Verify sink operations safely no-op without raising any exceptions when Langfuse is offline."""
    # Instantiating with invalid/empty credentials or offline flag
    offline_sink = LangfuseSink(
        public_key="pk-lf-offline",
        secret_key="sk-lf-offline",
        base_url="http://127.0.0.1:9999",  # unreachable endpoint
        enabled=False,
    )
    assert not offline_sink.is_active()

    # All context managers must run cleanly and yield None
    with offline_sink.trace_turn(name="test-turn") as turn_obs:
        assert turn_obs is None

    with offline_sink.trace_generation(name="test-gen") as gen_obs:
        assert gen_obs is None

    with offline_sink.trace_tool(tool_name="test-tool") as tool_obs:
        assert tool_obs is None

    with offline_sink.trace_subagent(role="Worker", task_prompt="do task") as sub_obs:
        assert sub_obs is None

    # Flush and shutdown must be safe
    offline_sink.flush()
    offline_sink.shutdown()
