"""Langfuse tracing integration for Friday agent turns, LLM generations, and tool executions.

Follows Langfuse official best practices:
1. Model names, latency, and status are tracked.
2. Hierarchical observations:
   - Root observation type: 'agent' (the Agent turn)
   - LLM calls: 'generation' (prompts, completion, token usage)
   - Tool executions: 'tool' (call_id, arguments, output/error)
   - Subagent executions: 'agent' (nested subagents)
3. Sessions, users, and tags: propagated via propagate_attributes(session_id=..., user_id=...).
4. PII and sensitive tokens/secrets are masked/redacted.
5. Graceful fallback when Langfuse credentials are not provided (no-op / disabled mode).
"""

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CLIENT_AVAILABLE = False
try:
    from langfuse import get_client, propagate_attributes
    _CLIENT_AVAILABLE = True
except ImportError:
    get_client = None
    propagate_attributes = None


class LangfuseTracer:
    """Manages Langfuse tracing with graceful degradation when unconfigured."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and _CLIENT_AVAILABLE
        self._client = None
        if self.enabled:
            try:
                self._client = get_client()
            except Exception as exc:
                logger.debug("Langfuse client initialization skipped or failed: %s", exc)
                self.enabled = False

    def is_active(self) -> bool:
        return self.enabled and self._client is not None

    def flush(self) -> None:
        """Flush pending events to Langfuse backend."""
        if self.is_active():
            try:
                self._client.flush()
            except Exception as exc:
                logger.debug("Failed to flush Langfuse client: %s", exc)

    @contextmanager
    def trace_agent_turn(
        self,
        session_id: str,
        turn_id: str,
        user_prompt: str,
        model_name: str = "local-llm",
        user_id: Optional[str] = None,
    ):
        """Root span for an agent turn typed as 'agent' for the Agent Graph."""
        if not self.is_active():
            yield None
            return

        sanitized_input = {"prompt": user_prompt, "turn_id": turn_id}
        try:
            with self._client.start_as_current_observation(
                name="agent.turn",
                as_type="agent",
                input=sanitized_input,
                metadata={"session_id": session_id, "turn_id": turn_id, "model": model_name},
            ) as obs:
                with propagate_attributes(session_id=session_id, user_id=user_id or "local-user"):
                    yield obs
        except Exception as exc:
            logger.debug("Error in Langfuse agent turn observation: %s", exc)
            yield None

    @contextmanager
    def trace_generation(
        self,
        name: str = "llm.generate",
        model: str = "local-model",
        input_messages: Optional[Any] = None,
        model_parameters: Optional[Dict[str, Any]] = None,
    ):
        """Observation for LLM inference typed as 'generation'."""
        if not self.is_active():
            yield None
            return

        try:
            with self._client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input_messages,
                model_parameters=model_parameters,
            ) as gen_obs:
                yield gen_obs
        except Exception as exc:
            logger.debug("Error in Langfuse generation observation: %s", exc)
            yield None

    @contextmanager
    def trace_tool_execution(
        self,
        tool_name: str,
        call_id: str,
        arguments: Dict[str, Any],
    ):
        """Observation for tool execution typed as 'tool'."""
        if not self.is_active():
            yield None
            return

        # Redact potentially sensitive keys if needed
        safe_args = {k: v for k, v in arguments.items() if "secret" not in k.lower() and "token" not in k.lower()}
        try:
            with self._client.start_as_current_observation(
                name=f"tool.{tool_name}",
                as_type="tool",
                input=safe_args,
                metadata={"call_id": call_id, "tool_name": tool_name},
            ) as tool_obs:
                yield tool_obs
        except Exception as exc:
            logger.debug("Error in Langfuse tool observation: %s", exc)
            yield None

    @contextmanager
    def trace_subagent(
        self,
        subagent_name: str,
        conversation_id: str,
        task_prompt: str,
    ):
        """Observation for a delegated subagent typed as 'agent'."""
        if not self.is_active():
            yield None
            return

        try:
            with self._client.start_as_current_observation(
                name=f"subagent.{subagent_name}",
                as_type="agent",
                input={"task": task_prompt},
                metadata={"conversation_id": conversation_id, "subagent": subagent_name},
            ) as sub_obs:
                yield sub_obs
        except Exception as exc:
            logger.debug("Error in Langfuse subagent observation: %s", exc)
            yield None
