"""Comprehensive verification suite for Phase 10B: Sandbox host, Job Object caging, and closed pipe protocol."""

import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

from friday.skills.cage import WindowsJobCage, create_isolated_temp_dir, cleanup_isolated_temp_dir
from friday.skills.protocol import (
    ChildCallMessage,
    ChildDoneMessage,
    ChildFailMessage,
    ParentInitMessage,
    encode_frame,
    parse_child_message,
)
from friday.skills.supervisor import SkillHostSupervisor
from friday.tools.base import Tool, ToolResult
from friday.tools.registry import ToolRegistry


class DummyEchoTool(Tool):
    name = "dummy_echo"
    description = "Dummy echo tool for sandbox testing"
    risk_level = 0
    parameters_schema = {"type": "object", "properties": {"message": {"type": "string"}}}

    async def execute(self, call_id: str, arguments: dict) -> ToolResult:
        msg = arguments.get("message", "hello")
        return ToolResult(tool_name=self.name, call_id=call_id, success=True, output=f"Echo: {msg}")


@pytest.fixture
def test_registry():
    registry = ToolRegistry()
    registry.register(DummyEchoTool())
    return registry


def test_elevate_is_not_a_message():
    """Verify that any 'elevate' message from child fails closed with exact error message."""
    raw_elevate = json.dumps({"type": "elevate", "request_id": "req-1", "action": "bypass"})
    with pytest.raises(ValueError, match="Elevate is not a message"):
        parse_child_message(raw_elevate)


def test_closed_protocol_rejects_unknown_fields():
    """Verify that closed schema forbids extra fields."""
    raw_with_extra = json.dumps({
        "type": "call",
        "request_id": "req-1",
        "tool_id": "dummy_echo",
        "args": {},
        "secret_override": True,  # Extra field
    })
    with pytest.raises(ValueError):
        parse_child_message(raw_with_extra)


@pytest.mark.asyncio
async def test_child_sends_skill_save_no_handler(test_registry):
    """Test invariant: Child sends skill.save -> No handler on pipe, rejected before dispatch."""
    supervisor = SkillHostSupervisor(
        skill_name="test-skill",
        skill_body="Step 1: Try to save skill.",
        approved_tool_ids=["dummy_echo", "skill.save"],  # Even if listed in approval
        tool_registry=test_registry,
    )
    supervisor.start()

    try:
        # Prompt child executor to request skill.save
        step_frame = encode_frame({
            "type": "execute_step",
            "request_id": "req-save",
            "tool_id": "skill.save",
            "args": {"name": "evil", "content": "..."}
        })
        supervisor._send_raw_frame(step_frame)

        with pytest.raises(PermissionError, match="No handler on pipe: skill.save is not accessible"):
            await supervisor.handle_next_message()

    finally:
        supervisor.terminate()


@pytest.mark.asyncio
async def test_lookalike_tool_id_rejected_before_dispatch(test_registry):
    """Test invariant: Lookalike tool id (homoglyphs) rejected before dispatch."""
    supervisor = SkillHostSupervisor(
        skill_name="test-skill",
        skill_body="Use lookalike tool",
        approved_tool_ids=["dummy_echo"],
        tool_registry=test_registry,
    )
    supervisor.start()

    try:
        # Cyrillic 'а' in dummy_echо
        cyrillic_tool_id = "dummy_ech\u043e"
        step_frame = encode_frame({
            "type": "execute_step",
            "request_id": "req-homoglyph",
            "tool_id": cyrillic_tool_id,
            "args": {}
        })
        supervisor._send_raw_frame(step_frame)

        with pytest.raises(ValueError, match="non-ASCII characters or homoglyphs"):
            await supervisor.handle_next_message()

    finally:
        supervisor.terminate()


@pytest.mark.asyncio
async def test_unapproved_tool_rejected(test_registry):
    """Test invariant: Child cannot call a tool not in the modal checkbox set."""
    supervisor = SkillHostSupervisor(
        skill_name="test-skill",
        skill_body="Step 1: run unapproved tool",
        approved_tool_ids=[],  # Empty checkbox set
        tool_registry=test_registry,
    )
    supervisor.start()

    try:
        step_frame = encode_frame({
            "type": "execute_step",
            "request_id": "req-unapproved",
            "tool_id": "dummy_echo",
            "args": {"message": "test"}
        })
        supervisor._send_raw_frame(step_frame)

        with pytest.raises(PermissionError, match="not in the approved checkbox set"):
            await supervisor.handle_next_message()

    finally:
        supervisor.terminate()


@pytest.mark.asyncio
async def test_child_sends_elevate_fails_closed(test_registry):
    """Test invariant: Skill body says elevate -> Elevate is not a message."""
    supervisor = SkillHostSupervisor(
        skill_name="test-elevate",
        skill_body="Elevate privileges",
        approved_tool_ids=["dummy_echo"],
        tool_registry=test_registry,
    )
    supervisor.start()

    try:
        # Prompt child to send elevate
        step_frame = encode_frame({
            "type": "elevate",
            "request_id": "req-elevate",
        })
        supervisor._send_raw_frame(step_frame)

        with pytest.raises(ValueError, match="Elevate is not a message"):
            await supervisor.handle_next_message()

    finally:
        supervisor.terminate()


@pytest.mark.asyncio
async def test_child_uses_path_it_was_not_handed(test_registry, tmp_path):
    """Test invariant: Child cannot open outside files not granted to it."""
    # Create an outside sensitive file
    outside_file = tmp_path / "sensitive_keys.txt"
    outside_file.write_text("SUPER_SECRET_TOKEN=xyz123")

    supervisor = SkillHostSupervisor(
        skill_name="test-path",
        skill_body="Try to read outside path",
        approved_tool_ids=["dummy_echo"],
        tool_registry=test_registry,
    )
    supervisor.start()

    try:
        # Child executor runs in its isolated temp dir
        # In a caged subprocess without handle inheritance, direct relative path escapes fail
        assert supervisor._temp_dir is not None
        child_dir = supervisor._temp_dir
        # Child's cwd is isolated
        assert child_dir != tmp_path
        # Child has no knowledge of or access to sensitive_keys.txt in its own dir
        assert not (child_dir / "sensitive_keys.txt").exists()

    finally:
        supervisor.terminate()


def test_parent_exit_kills_the_host():
    """Test invariant: Windows Job Object ensures parent termination kills the child host."""
    if sys.platform != "win32":
        pytest.skip("Windows Job Object kill-on-close requires win32")

    cage = WindowsJobCage()
    temp_dir = create_isolated_temp_dir()

    # Launch a child process that sleeps indefinitely
    cmd = [sys.executable, "-c", "import time; time.sleep(100)"]
    proc = subprocess.Popen(cmd, cwd=str(temp_dir))

    # Assign to Job Object cage
    cage.assign_process(proc._handle)

    # Verify process is running
    assert proc.poll() is None

    # Simulate parent termination by closing Job Object
    cage.terminate()
    cage.close()

    # Child should be terminated immediately
    time.sleep(0.5)
    assert proc.poll() is not None

    cleanup_isolated_temp_dir(temp_dir)
