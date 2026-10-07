"""Unified telemetry and observability coordinator for Friday (Phase 13).

Invariants:
1. Dual-Sink: Durably writes local sovereign JSONL traces and mirrors to Langfuse if configured.
2. Zero Crashes: Tracing errors never fail or disrupt agent turns or scheduled jobs.
3. Hardware Integration: Snapshots RTX 5090 GPU metrics (VRAM, wattage, utilization).
4. Sanitization: All payloads are scrubbed of secrets, tokens, and bounded to 64 KiB.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
import uuid

from friday.inference.telemetry import GpuTelemetry, TelemetryProvider
from friday.telemetry.langfuse import LangfuseSink
from friday.telemetry.tracer import (
    LocalJsonlSink,
    ObservationRecord,
    ObservationType,
    TraceRecord,
    sanitize_payload,
)

logger = logging.getLogger(__name__)


class ActiveTurnTrace:
    """Manages observation collection and dual-sink emission for an in-flight turn."""

    def __init__(
        self,
        trace_id: str,
        session_id: Optional[str],
        user_prompt: str,
        local_sink: LocalJsonlSink,
        langfuse_sink: LangfuseSink,
        gpu_provider: Optional[TelemetryProvider] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.trace_id = trace_id
        self.session_id = session_id
        self.user_prompt = user_prompt
        self.local_sink = local_sink
        self.langfuse_sink = langfuse_sink
        self.gpu_provider = gpu_provider
        self.tags = list(tags) if tags else ["friday-desktop"]
        self.metadata = dict(metadata or {})
        self.observations: List[ObservationRecord] = []
        self.start_time = datetime.now(timezone.utc).isoformat()
        self._initial_gpu: Optional[GpuTelemetry] = None

        if self.gpu_provider:
            try:
                self._initial_gpu = self.gpu_provider.get_gpu_telemetry()
                if self._initial_gpu.available:
                    self.metadata["initial_gpu_telemetry"] = self._initial_gpu.model_dump()
            except Exception as exc:
                logger.debug("Could not snapshot initial GPU telemetry: %s", exc)

    def record_generation(
        self,
        model: str,
        input_messages: Any,
        output_text: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        thinking: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObservationRecord:
        """Record an LLM generation observation with tokens and chain-of-thought."""
        meta = dict(metadata or {})
        if thinking:
            meta["thinking"] = thinking

        obs = ObservationRecord(
            trace_id=self.trace_id,
            observation_type=ObservationType.GENERATION,
            name="model-generation",
            input=sanitize_payload(input_messages),
            output=sanitize_payload(output_text),
            model=model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            thinking=thinking,
            metadata=sanitize_payload(meta),
            end_time_utc=datetime.now(timezone.utc).isoformat(),
        )
        self.observations.append(obs)
        return obs

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        output: str,
        error: Optional[str] = None,
        risk_level: int = 0,
        call_id: Optional[str] = None,
    ) -> ObservationRecord:
        """Record a tool invocation observation with canonical inputs and results."""
        obs = ObservationRecord(
            id=call_id or str(uuid.uuid4()),
            trace_id=self.trace_id,
            observation_type=ObservationType.TOOL,
            name=f"tool:{tool_name}",
            input=sanitize_payload(arguments),
            output=sanitize_payload(output if not error else f"Error: {error}"),
            level="ERROR" if error else "DEFAULT",
            status_message=error,
            metadata={
                "risk_level": risk_level,
                "tool_name": tool_name,
            },
            end_time_utc=datetime.now(timezone.utc).isoformat(),
        )
        self.observations.append(obs)
        return obs

    def record_subagent_run(
        self,
        role: str,
        task_prompt: str,
        summary: str,
        tokens_consumed: int,
        tool_calls_count: int,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObservationRecord:
        """Record a subagent delegation observation (as_type='agent')."""
        meta = dict(metadata or {})
        meta.update(
            {
                "tokens_consumed": tokens_consumed,
                "tool_calls_count": tool_calls_count,
            }
        )
        obs = ObservationRecord(
            trace_id=self.trace_id,
            observation_type=ObservationType.AGENT,
            name=f"subagent:{role}",
            input={"role": role, "task_prompt": sanitize_payload(task_prompt)},
            output=sanitize_payload(summary),
            level="ERROR" if error else "DEFAULT",
            status_message=error,
            metadata=sanitize_payload(meta),
            end_time_utc=datetime.now(timezone.utc).isoformat(),
        )
        self.observations.append(obs)
        return obs

    async def complete(self, final_answer: str, error: Optional[str] = None) -> None:
        """Finalize trace and write to dual sinks."""
        end_time = datetime.now(timezone.utc).isoformat()
        if self.gpu_provider:
            try:
                final_gpu = self.gpu_provider.get_gpu_telemetry()
                if final_gpu.available:
                    self.metadata["final_gpu_telemetry"] = final_gpu.model_dump()
            except Exception as exc:
                logger.debug("Could not snapshot final GPU telemetry: %s", exc)

        record = TraceRecord(
            id=self.trace_id,
            session_id=self.session_id,
            user_id="default_user",
            name="chat-turn",
            start_time_utc=self.start_time,
            end_time_utc=end_time,
            input={"user_message": sanitize_payload(self.user_prompt)},
            output=sanitize_payload(final_answer if not error else f"Error: {error}"),
            tags=self.tags,
            metadata=self.metadata,
            observations=self.observations,
        )

        # 1. Write local JSONL log
        try:
            await self.local_sink.write_trace(record)
        except Exception as exc:
            logger.error("Failed writing trace to local JSONL: %s", exc)

        # 2. Flush Langfuse sink if active
        if self.langfuse_sink.is_active():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.langfuse_sink.flush)


class TelemetryManager:
    """Singleton / coordinating service for Friday observability and tracing."""

    def __init__(
        self,
        logs_dir: Path | str = "logs/traces",
        langfuse_sink: Optional[LangfuseSink] = None,
        gpu_provider: Optional[TelemetryProvider] = None,
    ) -> None:
        self.local_sink = LocalJsonlSink(logs_dir=logs_dir)
        self.langfuse_sink = langfuse_sink or LangfuseSink()
        self.gpu_provider = gpu_provider or TelemetryProvider()

    def is_langfuse_enabled(self) -> bool:
        return self.langfuse_sink.is_active()

    @asynccontextmanager
    async def start_turn_trace(
        self,
        session_id: Optional[str],
        user_prompt: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
    ) -> AsyncIterator[ActiveTurnTrace]:
        """Establish an active dual-sink trace for an agent turn."""
        trace_id = turn_id or str(uuid.uuid4())
        active_trace = ActiveTurnTrace(
            trace_id=trace_id,
            session_id=session_id,
            user_prompt=user_prompt,
            local_sink=self.local_sink,
            langfuse_sink=self.langfuse_sink,
            gpu_provider=self.gpu_provider,
            tags=tags,
            metadata=metadata,
        )

        # Connect with Langfuse turn context if active
        with self.langfuse_sink.trace_turn(
            name="chat-turn",
            session_id=session_id,
            user_id="default_user",
            user_message=user_prompt,
            tags=active_trace.tags,
            metadata=active_trace.metadata,
        ):
            yield active_trace
