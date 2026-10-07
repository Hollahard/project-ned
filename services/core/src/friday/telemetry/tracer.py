"""Core telemetry and local JSONL observability engine for Project Friday (Phase 13).

Invariants:
1. Sovereign Offline-First: Friday must function 100% offline with zero cloud dependency.
   All traces are durably recorded to local append-only JSONL files.
2. Security & Redaction: High-entropy secrets, API keys, and one-shot capability tokens
   are strictly redacted before ingestion or disk serialization.
3. Payload Boundedness: Serialized observation input/output payloads are capped at 64 KiB.
4. Rich Observation Types: Supports trace, span, generation, tool, and agent types.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 65536  # 64 KiB hard cap

# Secret and token patterns to redact
REDACTION_PATTERNS = [
    # Friday HMAC capability tokens: uuid.sha256
    re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.[0-9a-fA-F]{64}"),
    # Langfuse and OpenAI/AIza keys
    re.compile(r"(?:sk-lf-|pk-lf-|sk-|AIza)[a-zA-Z0-9_\-]{16,}"),
    # Bearer authorization headers
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-_.~+/]{16,}"),
]


def redact_sensitive_text(text: str) -> str:
    """Scrub capability tokens, API keys, and authorization secrets from text."""
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern in REDACTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)

    # Enforce 64 KiB payload ceiling
    encoded = sanitized.encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        truncated = encoded[: MAX_PAYLOAD_BYTES - 64].decode("utf-8", errors="ignore")
        return truncated + "\n... [TRUNCATED 64 KiB]"

    return sanitized


def sanitize_payload(obj: Any) -> Any:
    """Recursively scrub sensitive patterns and enforce bounds on data payloads."""
    if isinstance(obj, str):
        return redact_sensitive_text(obj)
    elif isinstance(obj, dict):
        return {
            k: sanitize_payload(v)
            for k, v in obj.items()
            if not k.lower().endswith("token")
            and not k.lower().endswith("secret")
            and not k.lower() in ("api_key", "password", "authorization")
        }
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_payload(item) for item in obj)
    return obj


class ObservationType(str, Enum):
    """Langfuse-compatible semantic observation types."""
    TRACE = "trace"
    SPAN = "span"
    GENERATION = "generation"
    TOOL = "tool"
    AGENT = "agent"
    EVENT = "event"


class ObservationRecord(BaseModel):
    """Structured record of an individual observation within a trace."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    parent_id: Optional[str] = None
    observation_type: ObservationType
    name: str
    start_time_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    end_time_utc: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    model: Optional[str] = None
    model_parameters: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, int]] = None  # prompt_tokens, completion_tokens, total_tokens
    thinking: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    level: str = "DEFAULT"  # DEBUG, DEFAULT, WARNING, ERROR
    status_message: Optional[str] = None


class TraceRecord(BaseModel):
    """Root trace record for a self-contained unit of work (e.g. agent turn or job)."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    user_id: str = "default_user"
    name: str = "agent-turn"
    start_time_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    end_time_utc: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    observations: List[ObservationRecord] = Field(default_factory=list)


class LocalJsonlSink:
    """Durably appends sanitized trace records to local daily-partitioned JSONL logs."""

    def __init__(self, logs_dir: Path | str = "logs/traces") -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _get_current_log_path(self) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.logs_dir / f"trace_{date_str}.jsonl"

    async def write_trace(self, trace: TraceRecord) -> None:
        """Sanitize and write completed trace record as atomic JSON line."""
        target_path = self._get_current_log_path()
        sanitized_dict = sanitize_payload(trace.model_dump())
        line = json.dumps(sanitized_dict, separators=(",", ":")) + "\n"

        async with self._lock:
            # Run blocking write in executor to preserve event loop latency
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._append_sync, target_path, line)

    @staticmethod
    def _append_sync(file_path: Path, data: str) -> None:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(data)
