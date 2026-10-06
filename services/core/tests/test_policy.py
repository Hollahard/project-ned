"""Tests for the security policy engine."""

from pathlib import Path
import pytest
from friday.security.tokens import CapabilityTokenManager
from friday.tools.native_read import FilesystemReadTool
from friday.tools.base import Tool, ToolResult
from friday.tools.policy import PolicyEngine


class DummyExecTool(Tool):
    name = "terminal.exec"
    description = "Execute shell command"
    risk_level = 2
    requires_approval = True
    parameters_schema = {"type": "object", "properties": {"cmd": {"type": "string"}}}

    async def execute(self, call_id: str, arguments: dict) -> ToolResult:
        return ToolResult(tool_name=self.name, call_id=call_id, success=True, output="executed")


def test_read_tool_allowed_in_root(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    target_file = safe_root / "test.txt"
    target_file.write_text("sample")

    token_mgr = CapabilityTokenManager(secret_key="test-key")
    engine = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])
    tool = FilesystemReadTool()

    decision = engine.evaluate(tool, {"path": str(target_file)})
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_exec_tool_requires_approval():
    token_mgr = CapabilityTokenManager(secret_key="test-key")
    engine = PolicyEngine(token_manager=token_mgr)
    tool = DummyExecTool()

    decision = engine.evaluate(tool, {"cmd": "whoami"})
    assert decision.allowed is False
    assert decision.requires_approval is True


def test_exec_tool_with_valid_token():
    token_mgr = CapabilityTokenManager(secret_key="test-key")
    engine = PolicyEngine(token_manager=token_mgr)
    tool = DummyExecTool()
    args = {"cmd": "whoami"}

    token, _ = token_mgr.mint_token(tool.name, args)
    decision = engine.evaluate(tool, args, capability_token=token)
    assert decision.allowed is True
