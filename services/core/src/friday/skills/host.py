"""friday-skill-host: Sandboxed executor process (Phase 10B).

Invariants:
1. Executor only, not a second model or reasoner.
2. Gets a one-shot read of the skill body from parent over length-prefixed pipe.
3. Communicates strictly via closed schema over stdin/stdout.
4. No parent memory, no env secrets, no db handle, no HMAC key.
5. Child does not browse drives; only works in isolated temp dir.
"""

import json
import struct
import sys
from typing import Any, Dict, Optional

from friday.skills.protocol import (
    ChildCallMessage,
    ChildDoneMessage,
    ChildFailMessage,
    MAX_FRAME_SIZE,
    encode_frame,
)


def read_frame() -> Dict[str, Any]:
    """Read a length-prefixed frame from parent on stdin.buffer."""
    header = sys.stdin.buffer.read(4)
    if not header or len(header) < 4:
        raise EOFError("Parent closed pipe.")

    (length,) = struct.unpack(">I", header)
    if length > MAX_FRAME_SIZE:
        raise ValueError(f"Frame length {length} exceeds maximum {MAX_FRAME_SIZE}")

    data = sys.stdin.buffer.read(length)
    if len(data) < length:
        raise EOFError("Incomplete frame received from parent.")

    return json.loads(data.decode("utf-8"))


def send_frame(msg: Dict[str, Any]) -> None:
    """Send length-prefixed frame to parent on stdout.buffer."""
    payload = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError(f"Payload size {len(payload)} exceeds {MAX_FRAME_SIZE}")
    header = struct.pack(">I", len(payload))
    sys.stdout.buffer.write(header + payload)
    sys.stdout.buffer.flush()


def run_host_loop() -> None:
    """Main execution loop of the caged skill host."""
    # 1. Read one-shot init frame from parent
    try:
        init_msg = read_frame()
        if init_msg.get("type") != "init":
            send_frame({"type": "fail", "request_id": "0", "error": "First message must be 'init'"})
            return
        skill_name = init_msg["skill_name"]
        skill_body = init_msg["body"]
    except Exception as e:
        try:
            send_frame({"type": "fail", "request_id": "0", "error": f"Init failed: {e}"})
        except Exception:
            pass
        return

    # 2. Host execution loop: process incoming instructions or commands
    while True:
        try:
            msg = read_frame()
        except EOFError:
            break
        except Exception as e:
            send_frame({"type": "fail", "request_id": "0", "error": f"Frame read error: {e}"})
            break

        msg_type = msg.get("type")
        req_id = msg.get("request_id", "0")

        if msg_type == "execute_step":
            # Example executor action requesting a tool call
            tool_id = msg.get("tool_id", "")
            args = msg.get("args", {})
            send_frame({"type": "call", "request_id": req_id, "tool_id": tool_id, "args": args})

        elif msg_type == "result":
            # Parent returned result of tool call
            send_frame({"type": "done", "request_id": req_id, "result": msg.get("output", "")})
            break

        elif msg_type == "elevate":
            # Malicious or confused payload attempting to send unapproved message
            send_frame({"type": "elevate", "request_id": req_id, "action": "bypass"})

        elif msg_type == "terminate":
            break

        else:
            send_frame({"type": "fail", "request_id": req_id, "error": f"Unknown message: {msg_type}"})


if __name__ == "__main__":
    run_host_loop()
