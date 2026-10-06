"""SkillHostSupervisor managing sandboxed child process and closed pipe communication (Phase 10B).

Invariants:
1. Child is caged in Windows Job Object with KILL_ON_JOB_CLOSE and active process limit = 1.
2. Working directory is isolated empty temp dir, wiped on termination.
3. Pipe frames capped at 64 KB with closed schema (call, done, fail).
4. Tool authorization: tool_id must pass ASCII validator, match modal checkbox set, and exist in live registry.
5. skill.save, skill.delete, and policy tools have NO handler on the pipe.
6. Unknown types (e.g. elevate) fail closed immediately.
"""

import asyncio
import json
import logging
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from friday.skills.cage import (
    WindowsJobCage,
    cleanup_isolated_temp_dir,
    create_isolated_temp_dir,
    get_sanitized_cage_env,
)
from friday.skills.parser import validate_tool_identifier
from friday.skills.protocol import (
    ChildCallMessage,
    ChildDoneMessage,
    ChildFailMessage,
    MAX_FRAME_SIZE,
    ParentInitMessage,
    ParentResultMessage,
    encode_frame,
    parse_child_message,
)
from friday.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

FORBIDDEN_PIPE_TOOLS = {"skill.save", "skill.delete", "policy.evaluate", "policy.update"}


class SkillHostSupervisor:
    """Parent supervisor managing the caged execution of a skill host."""

    def __init__(
        self,
        skill_name: str,
        skill_body: str,
        approved_tool_ids: List[str],
        tool_registry: ToolRegistry,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.skill_name = skill_name
        self.skill_body = skill_body
        self.approved_tool_ids = set(approved_tool_ids)
        self.tool_registry = tool_registry
        self.timeout_seconds = timeout_seconds

        self._temp_dir: Optional[Path] = None
        self._job_cage: Optional[WindowsJobCage] = None
        self._process: Optional[subprocess.Popen] = None
        self._in_flight_call = False

    def start(self) -> None:
        """Create isolated temp directory, Job Object cage, and spawn child process."""
        self._temp_dir = create_isolated_temp_dir()
        sanitized_env = get_sanitized_cage_env(self._temp_dir)
        self._job_cage = WindowsJobCage()

        # Command to launch host executor module using base python interpreter
        python_bin = getattr(sys, "_base_executable", sys.executable)
        cmd = [python_bin, "-m", "friday.skills.host"]

        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._temp_dir),
            env=sanitized_env,
        )

        # Assign process to Job Object cage immediately
        if sys.platform == "win32" and hasattr(self._process, "_handle"):
            self._job_cage.assign_process(self._process._handle)

        # Send one-shot initialization frame containing the skill body
        init_frame = encode_frame(
            ParentInitMessage(type="init", skill_name=self.skill_name, body=self.skill_body)
        )
        self._send_raw_frame(init_frame)
        logger.info("Spawned and initialized caged skill host for %s (PID %d)", self.skill_name, self._process.pid)

    def _send_raw_frame(self, frame_bytes: bytes) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Skill host process is not running.")
        self._process.stdin.write(frame_bytes)
        self._process.stdin.flush()

    def _read_raw_frame(self) -> bytes:
        if not self._process or not self._process.stdout:
            raise RuntimeError("Skill host process is not running.")

        header = self._process.stdout.read(4)
        if not header or len(header) < 4:
            stderr_out = ""
            if self._process.stderr:
                try:
                    stderr_out = self._process.stderr.read().decode("utf-8")
                except Exception:
                    pass
            raise EOFError(f"Skill host closed pipe unexpectedly. Exit code: {self._process.poll()}, Stderr: {stderr_out}")

        (length,) = struct.unpack(">I", header)
        if length > MAX_FRAME_SIZE:
            raise ValueError(f"Frame length {length} exceeds maximum cap of {MAX_FRAME_SIZE} bytes.")

        data = self._process.stdout.read(length)
        if len(data) < length:
            raise EOFError("Incomplete frame from skill host.")

        return data

    async def handle_next_message(self) -> Dict[str, Any]:
        """Read and dispatch one incoming message from the child host over the closed protocol."""
        if not self._process:
            raise RuntimeError("Skill host is not running.")

        # Read length-prefixed raw frame in executor thread to prevent event loop blocking
        raw_data = await asyncio.to_thread(self._read_raw_frame)

        # Parse message strictly according to closed schema
        parsed_msg = parse_child_message(raw_data)

        if isinstance(parsed_msg, ChildDoneMessage):
            return {"status": "done", "request_id": parsed_msg.request_id, "result": parsed_msg.result}

        elif isinstance(parsed_msg, ChildFailMessage):
            return {"status": "fail", "request_id": parsed_msg.request_id, "error": parsed_msg.error}

        elif isinstance(parsed_msg, ChildCallMessage):
            if self._in_flight_call:
                raise RuntimeError("Violation: Only one in-flight call is permitted.")
            self._in_flight_call = True

            try:
                # 1. Authorize tool identity: check ASCII & homoglyphs
                clean_tool_id = validate_tool_identifier(parsed_msg.tool_id)

                # 2. Block forbidden tools (skill.save, skill.delete, policy.*)
                if clean_tool_id in FORBIDDEN_PIPE_TOOLS or clean_tool_id.startswith("policy."):
                    raise PermissionError(f"No handler on pipe: {clean_tool_id} is not accessible to skill host.")

                # 3. Intersect with modal checkbox set (approved_tool_ids)
                if clean_tool_id not in self.approved_tool_ids:
                    raise PermissionError(
                        f"Tool '{clean_tool_id}' is not in the approved checkbox set for skill '{self.skill_name}'."
                    )

                # 4. Intersect with live ToolRegistry
                tool = self.tool_registry.get(clean_tool_id)
                if not tool:
                    raise KeyError(f"Tool '{clean_tool_id}' not found in active ToolRegistry.")

                # 5. Execute tool in parent context
                tool_res = await tool.execute(call_id=parsed_msg.request_id, arguments=parsed_msg.args)

                # 6. Size-cap and scrub result
                out_str = tool_res.output or ""
                if len(out_str.encode("utf-8")) > MAX_FRAME_SIZE:
                    out_str = out_str[: MAX_FRAME_SIZE // 2] + "\n[OUTPUT TRUNCATED BY SANDBOX GATE]"

                # 7. Send framed result back to child
                res_frame = encode_frame(
                    ParentResultMessage(
                        type="result",
                        request_id=parsed_msg.request_id,
                        success=tool_res.success,
                        output=out_str,
                        error=tool_res.error,
                    )
                )
                self._send_raw_frame(res_frame)
                return {"status": "call_dispatched", "tool_id": clean_tool_id, "success": tool_res.success}

            finally:
                self._in_flight_call = False

        else:
            raise ValueError("Unknown message structure received from child.")

    def terminate(self) -> None:
        """Kill child host, close Job Object cage, and clean up temporary directory."""
        if self._process:
            try:
                self._process.kill()
                self._process.wait(timeout=2.0)
            except Exception:
                pass
            self._process = None

        if self._job_cage:
            try:
                self._job_cage.terminate()
                self._job_cage.close()
            except Exception:
                pass
            self._job_cage = None

        if self._temp_dir:
            cleanup_isolated_temp_dir(self._temp_dir)
            self._temp_dir = None
        logger.info("Cleaned up skill host cage for %s", self.skill_name)

    def __del__(self) -> None:
        self.terminate()
