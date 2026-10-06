"""Closed framing protocol and message schemas for the sandboxed skill host (Phase 10B).

Invariants:
1. Length-prefixed framing: 4-byte big-endian integer, strictly capped at 64 KB (65,536 bytes).
2. Closed schema: Child may send ONLY 'call', 'done', or 'fail'. Unknown types (like 'elevate') fail closed.
3. Extra fields forbidden on all models.
"""

import json
import struct
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

MAX_FRAME_SIZE = 64 * 1024  # 64 KB


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChildCallMessage(ClosedModel):
    type: Literal["call"]
    request_id: str
    tool_id: str
    args: Dict[str, Any] = Field(default_factory=dict)


class ChildDoneMessage(ClosedModel):
    type: Literal["done"]
    request_id: str
    result: str


class ChildFailMessage(ClosedModel):
    type: Literal["fail"]
    request_id: str
    error: str


class ParentInitMessage(ClosedModel):
    type: Literal["init"]
    skill_name: str
    body: str


class ParentResultMessage(ClosedModel):
    type: Literal["result"]
    request_id: str
    success: bool
    output: str = ""
    error: Optional[str] = None


def encode_frame(message: BaseModel | Dict[str, Any]) -> bytes:
    """Encode message as a 4-byte big-endian length-prefixed UTF-8 JSON frame."""
    if isinstance(message, BaseModel):
        data = message.model_dump_json().encode("utf-8")
    else:
        data = json.dumps(message, separators=(",", ":")).encode("utf-8")

    if len(data) > MAX_FRAME_SIZE:
        raise ValueError(f"Frame size {len(data)} exceeds maximum of {MAX_FRAME_SIZE} bytes.")

    prefix = struct.pack(">I", len(data))
    return prefix + data


def parse_child_message(raw_json: bytes | str) -> ChildCallMessage | ChildDoneMessage | ChildFailMessage:
    """Parse incoming child payload against the closed schema.
    
    Rejects unknown message types (e.g. 'elevate') and extra fields.
    """
    if isinstance(raw_json, bytes):
        payload_str = raw_json.decode("utf-8")
    else:
        payload_str = raw_json

    try:
        data = json.loads(payload_str)
    except Exception as e:
        raise ValueError(f"Malformed JSON frame from child: {e}")

    if not isinstance(data, dict):
        raise ValueError("Child frame must be a JSON object.")

    msg_type = data.get("type")
    if msg_type == "call":
        return ChildCallMessage.model_validate(data)
    elif msg_type == "done":
        return ChildDoneMessage.model_validate(data)
    elif msg_type == "fail":
        return ChildFailMessage.model_validate(data)
    else:
        raise ValueError(f"Elevate is not a message (unknown message type: '{msg_type}').")
