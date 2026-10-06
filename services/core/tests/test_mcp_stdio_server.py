"""Integration tests for MCP stdio server execution, discovery, and policy gating."""

import asyncio
import os
import sys
from pathlib import Path
import pytest

from friday.mcp.config import MCPServerConfig
from friday.mcp.host import MCPHost
from friday.security.tokens import CapabilityTokenManager
from friday.tools.policy import PolicyEngine
from friday.tools.registry import ToolRegistry


SERVER_SCRIPT = """
import asyncio
import os
from mcp.server.mcpserver import MCPServer

server = MCPServer("calc_server")

@server.tool()
def add_numbers(a: int, b: int) -> int:
    \"\"\"Add two integers together.\"\"\"
    return a + b

@server.tool()
def get_secret_env(name: str) -> str:
    \"\"\"Get environment variable or fallback.\"\"\"
    return os.environ.get(name, "NOT_PRESENT")

if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
"""


@pytest.fixture
def mcp_server_script(tmp_path: Path) -> Path:
    script_path = tmp_path / "test_calc_server.py"
    script_path.write_text(SERVER_SCRIPT, encoding="utf-8")
    return script_path


@pytest.mark.asyncio
async def test_mcp_stdio_server_lifecycle_and_tools(tmp_path: Path, mcp_server_script: Path):
    safe_root = tmp_path
    host = MCPHost(safe_roots=[safe_root])

    conf = MCPServerConfig(
        name="calc",
        command=sys.executable,
        args=[str(mcp_server_script)],
        risk_level=2,
        cwd=str(safe_root),
        timeout_seconds=15,
    )
    host.register_server(conf)

    # 1. Start server and discover tools
    adapters = await host.start_server("calc")
    assert len(adapters) == 2

    tool_names = {a.name for a in adapters}
    assert "mcp_calc.add_numbers" in tool_names
    assert "mcp_calc.get_secret_env" in tool_names

    # 2. Execute discovered tool
    add_tool = next(a for a in adapters if a.name == "mcp_calc.add_numbers")
    res = await add_tool.execute("call-1", {"a": 15, "b": 25})
    assert res.success is True
    assert "40" in res.output

    # 3. Synchronize to Friday ToolRegistry
    registry = ToolRegistry()
    host.sync_to_registry(registry)
    assert registry.get("mcp_calc.add_numbers") is not None

    # 4. Telemetry status check
    status = host.get_status()
    assert status["calc"]["is_connected"] is True
    assert status["calc"]["tool_count"] == 2

    # 5. Stop server
    await host.stop_all()
    status_stopped = host.get_status()
    assert status_stopped["calc"]["is_connected"] is False


@pytest.mark.asyncio
async def test_mcp_stdio_policy_and_token_gating(tmp_path: Path, mcp_server_script: Path):
    safe_root = tmp_path
    host = MCPHost(safe_roots=[safe_root])

    conf = MCPServerConfig(
        name="calc",
        command=sys.executable,
        args=[str(mcp_server_script)],
        risk_level=2,
        cwd=str(safe_root),
        timeout_seconds=15,
    )
    host.register_server(conf)
    adapters = await host.start_server("calc")
    add_tool = next(a for a in adapters if a.name == "mcp_calc.add_numbers")

    token_mgr = CapabilityTokenManager("mcp-policy-secret")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])

    args = {"a": 100, "b": 200}

    # 1. Gated by default: Risk 2 requires native OS approval
    dec1 = policy.evaluate(add_tool, args)
    assert dec1.allowed is False
    assert dec1.requires_approval is True

    # 2. Authorized via one-shot capability token
    token, _ = token_mgr.mint_token(add_tool.name, args)
    dec2 = policy.evaluate(add_tool, args, capability_token=token)
    assert dec2.allowed is True

    # 3. Execution succeeds
    res = await add_tool.execute("call-2", args)
    assert res.success is True
    assert "300" in res.output

    # 4. Token replay / reuse fails
    dec3 = policy.evaluate(add_tool, args, capability_token=token)
    assert dec3.allowed is False

    await host.stop_all()


@pytest.mark.asyncio
async def test_mcp_stdio_environment_sanitization(tmp_path: Path, mcp_server_script: Path, monkeypatch):
    safe_root = tmp_path
    host = MCPHost(safe_roots=[safe_root])

    # Inject secret into parent environment
    monkeypatch.setenv("FRIDAY_SECRET_KEY", "sensitive-master-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "confidential-aws-key")

    conf = MCPServerConfig(
        name="calc",
        command=sys.executable,
        args=[str(mcp_server_script)],
        risk_level=2,
        cwd=str(safe_root),
        timeout_seconds=15,
    )
    host.register_server(conf)
    adapters = await host.start_server("calc")
    env_tool = next(a for a in adapters if a.name == "mcp_calc.get_secret_env")

    # Query secret env var from child process
    res = await env_tool.execute("call-3", {"name": "FRIDAY_SECRET_KEY"})
    assert res.success is True
    assert "NOT_PRESENT" in res.output
    assert "sensitive-master-key" not in res.output

    await host.stop_all()


@pytest.mark.asyncio
async def test_mcp_stdio_working_dir_outside_safe_root(tmp_path: Path, mcp_server_script: Path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()

    host = MCPHost(safe_roots=[safe_root])

    conf = MCPServerConfig(
        name="calc",
        command=sys.executable,
        args=[str(mcp_server_script)],
        risk_level=2,
        cwd=str(outside_root),
        timeout_seconds=15,
    )
    host.register_server(conf)

    with pytest.raises(ValueError, match="outside configured safe roots"):
        await host.start_server("calc")
