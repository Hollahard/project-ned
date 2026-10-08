"""Bounded SSE parser for Tabby's load control stream, independent of framing chunks."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from .errors import ProtocolError, RemoteOperationError


@dataclass(frozen=True, slots=True)
class StreamLimits:
    max_event_bytes: int = 16384
    max_total_bytes: int = 4 * 1024 * 1024
    max_events: int = 20000

    def __post_init__(self) -> None:
        for value in (self.max_event_bytes, self.max_total_bytes, self.max_events):
            if type(value) is not int or value <= 0:
                raise ValueError("stream limits must be positive integers")


async def events(response: httpx.Response, limits: StreamLimits) -> AsyncIterator[dict]:
    buffer = b""
    data: list[str] = []
    event_bytes = total_bytes = event_count = 0
    event_type = "message"
    async for chunk in response.aiter_bytes():
        total_bytes += len(chunk)
        if total_bytes > limits.max_total_bytes:
            raise ProtocolError("load stream exceeds total byte limit")
        buffer += chunk
        while True:
            positions = [i for i in (buffer.find(b"\n"), buffer.find(b"\r")) if i >= 0]
            if not positions:
                break
            end = min(positions)
            if buffer[end : end + 1] == b"\r" and end + 1 == len(buffer):
                break
            separator = 2 if buffer[end : end + 2] == b"\r\n" else 1
            raw_line, buffer = buffer[:end], buffer[end + separator :]
            event_bytes += len(raw_line) + separator
            if event_bytes > limits.max_event_bytes:
                raise ProtocolError("load stream event exceeds byte limit")
            try:
                line = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise ProtocolError("load stream is not UTF-8") from None
            if not line:
                if data:
                    event_count += 1
                    if event_count > limits.max_events:
                        raise ProtocolError("load stream exceeds event limit")
                    try:
                        result = json.loads("\n".join(data))
                    except (ValueError, RecursionError):
                        raise ProtocolError("load stream contains malformed JSON") from None
                    if not isinstance(result, dict):
                        raise ProtocolError("load stream event must be an object")
                    if event_type == "error" or "error" in result:
                        raise RemoteOperationError("engine reported a load failure")
                    yield result
                elif event_type == "error":
                    raise RemoteOperationError("engine reported a load failure")
                data, event_bytes, event_type = [], 0, "message"
            elif not line.startswith(":"):
                field, _, value = line.partition(":")
                value = value.removeprefix(" ")
                if field == "data":
                    data.append(value)
                elif field == "event":
                    event_type = value
                elif field not in {"id", "retry"}:
                    raise ProtocolError("unexpected load stream field")
        if len(buffer) + event_bytes > limits.max_event_bytes:
            raise ProtocolError("load stream event exceeds byte limit")
    if buffer or data or event_type != "message":
        raise ProtocolError("load stream ended inside an event")


def validate_progress(value: dict) -> bool:
    """Return True for finished main-model phase; callers must still consume EOF."""
    if value.get("model_type") not in {"model", "draft", "vision", "warmup"}:
        raise ProtocolError("unknown load component")
    if value.get("status") not in {"processing", "finished"}:
        raise ProtocolError("unknown load status")
    module, modules = value.get("module"), value.get("modules")
    if type(module) is not int or type(modules) is not int or not 0 <= module <= modules:
        raise ProtocolError("invalid load progress counts")
    if value["status"] == "finished" and module != modules:
        raise ProtocolError("inconsistent finished load event")
    return value["model_type"] == "model" and value["status"] == "finished"
