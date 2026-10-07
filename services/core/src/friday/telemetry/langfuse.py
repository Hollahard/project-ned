"""Langfuse Cloud / Self-Hosted tracing integration for Project Friday (Phase 13).

Invariants:
1. Dual-Sink Architecture: Works alongside LocalJsonlSink without replacing it.
2. Graceful Fallback: If Langfuse credentials are not provided or network is down,
   tracing operations gracefully no-op without raising exceptions or blocking execution.
3. Multi-Agent Representation: Subagents are traced with as_type='agent', nesting
   child model generations and tools within the Agent Graph.
4. Security & Sanitization: Secret credentials, capability tokens, and sensitive keys
   are scrubbed via RedactionFilter before being dispatched to Langfuse.
5. Chain-of-Thought / Reasoning: Thinking and reasoning deltas are captured on generations.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
import os
from typing import Any, Dict, Iterator, List, Optional
from friday.telemetry.tracer import sanitize_payload

logger = logging.getLogger(__name__)

# Module-level hooks for Langfuse SDK availability and unit test patching
_CLIENT_AVAILABLE = False
try:
    from langfuse import Langfuse, get_client, propagate_attributes
    _CLIENT_AVAILABLE = True
except ImportError:
    Langfuse = None
    get_client = None
    propagate_attributes = None


class LangfuseSink:
    """Manages observation lifecycle with Langfuse SDK v4."""

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self.public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY", "")
        self.base_url = (
            base_url
            or os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST")
            or "https://us.cloud.langfuse.com"
        )
        self.enabled = enabled
        self._client: Optional[Any] = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.enabled:
            logger.info("Langfuse sink disabled; running offline only.")
            return

        if self.public_key and self.secret_key and Langfuse is not None:
            try:
                self._client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    base_url=self.base_url,
                )
                logger.info("Langfuse client initialized against endpoint %s", self.base_url)
                return
            except Exception as exc:
                logger.warning("Failed to initialize Langfuse client: %s; running offline.", exc)

        # Fall back to get_client() if available or mocked
        if _CLIENT_AVAILABLE and get_client is not None:
            try:
                self._client = get_client()
                if self._client:
                    return
            except Exception as exc:
                logger.debug("get_client fallback skipped: %s", exc)

        # If no credentials and no client found, disable
        if not (self.public_key and self.secret_key):
            self.enabled = False

    def _get_active_client(self) -> Optional[Any]:
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        if _CLIENT_AVAILABLE and get_client is not None:
            try:
                client = get_client()
                if client is not None:
                    return client
            except Exception:
                pass
        return None

    def is_active(self) -> bool:
        return self.enabled and self._get_active_client() is not None

    def flush(self) -> None:
        """Flush queued tracing events to Langfuse."""
        client = self._get_active_client()
        if client:
            try:
                client.flush()
            except Exception as exc:
                logger.debug("Langfuse flush warning: %s", exc)

    def shutdown(self) -> None:
        """Shutdown Langfuse client gracefully."""
        client = self._get_active_client()
        if client:
            try:
                client.shutdown()
            except Exception as exc:
                logger.debug("Langfuse shutdown warning: %s", exc)

    @contextmanager
    def trace_turn(
        self,
        name: str = "agent.turn",
        session_id: Optional[str] = None,
        user_id: str = "default_user",
        user_message: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        as_type: str = "agent",
    ) -> Iterator[Optional[Any]]:
        """Context manager establishing root trace for an agent turn."""
        client = self._get_active_client()
        if not client:
            yield None
            return

        clean_input = {"user_message": sanitize_payload(user_message)} if user_message else None
        clean_tags = list(tags) if tags else ["friday-desktop"]
        clean_meta = sanitize_payload(metadata or {})

        try:
            prop_fn = propagate_attributes if propagate_attributes is not None else None
            if prop_fn:
                with prop_fn(
                    session_id=session_id,
                    user_id=user_id,
                    tags=clean_tags,
                    metadata=clean_meta,
                ):
                    with client.start_as_current_observation(
                        name=name,
                        as_type=as_type,
                        input=clean_input,
                        metadata=clean_meta,
                    ) as trace_obs:
                        yield trace_obs
            else:
                with client.start_as_current_observation(
                    name=name,
                    as_type=as_type,
                    input=clean_input,
                    metadata=clean_meta,
                ) as trace_obs:
                    yield trace_obs
        except Exception as exc:
            logger.debug("Error during Langfuse turn trace: %s", exc)
            yield None

    @contextmanager
    def trace_agent_turn(
        self,
        session_id: str,
        turn_id: str,
        user_prompt: str,
        model_name: str = "default",
        user_id: Optional[str] = None,
    ) -> Iterator[Optional[Any]]:
        """Convenience wrapper for backward-compatible agent turn tracing."""
        meta = {"turn_id": turn_id, "model": model_name, "session_id": session_id}
        with self.trace_turn(
            name="agent.turn",
            session_id=session_id,
            user_id=user_id or "default_user",
            user_message=user_prompt,
            tags=["friday-desktop", model_name],
            metadata=meta,
            as_type="agent",
        ) as span:
            yield span

    @contextmanager
    def trace_generation(
        self,
        name: str = "inference.generate",
        model: Optional[str] = None,
        input_messages: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Optional[Any]]:
        """Context manager tracing an individual model generation within the turn."""
        client = self._get_active_client()
        if not client:
            yield None
            return

        clean_input = sanitize_payload(input_messages)
        clean_meta = sanitize_payload(metadata or {})

        try:
            with client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                input=clean_input,
                metadata=clean_meta,
            ) as gen_obs:
                yield gen_obs
        except Exception as exc:
            logger.debug("Error during Langfuse generation trace: %s", exc)
            yield None

    @contextmanager
    def trace_tool_execution(
        self,
        tool_name: str,
        call_id: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Optional[Any]]:
        """Convenience wrapper for backward-compatible tool execution tracing."""
        meta = dict(metadata or {})
        if call_id:
            meta["call_id"] = call_id
        with self.trace_tool(tool_name=tool_name, arguments=arguments, metadata=meta) as tool_obs:
            yield tool_obs

    @contextmanager
    def trace_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Optional[Any]]:
        """Context manager tracing a concrete tool execution."""
        client = self._get_active_client()
        if not client:
            yield None
            return

        clean_args = sanitize_payload(arguments or {})
        clean_meta = sanitize_payload(metadata or {})
        span_name = f"tool:{tool_name}"

        try:
            with client.start_as_current_observation(
                name=span_name,
                as_type="tool",
                input=clean_args,
                metadata=clean_meta,
            ) as tool_obs:
                yield tool_obs
        except Exception as exc:
            logger.debug("Error during Langfuse tool trace: %s", exc)
            yield None

    @contextmanager
    def trace_subagent(
        self,
        role: Optional[str] = None,
        task_prompt: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        subagent_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[Optional[Any]]:
        """Context manager tracing subagent delegation with as_type='agent' for Agent Graph."""
        client = self._get_active_client()
        if not client:
            yield None
            return

        effective_role = role or subagent_name or "subagent"
        clean_input = {"role": effective_role, "task_prompt": sanitize_payload(task_prompt)}
        clean_meta = dict(metadata or {})
        if conversation_id:
            clean_meta["conversation_id"] = conversation_id
        clean_meta = sanitize_payload(clean_meta)
        agent_name = f"subagent:{effective_role}"

        try:
            with client.start_as_current_observation(
                name=agent_name,
                as_type="agent",
                input=clean_input,
                metadata=clean_meta,
            ) as agent_obs:
                yield agent_obs
        except Exception as exc:
            logger.debug("Error during Langfuse subagent trace: %s", exc)
            yield None


# Backwards compatibility alias
LangfuseTracer = LangfuseSink
