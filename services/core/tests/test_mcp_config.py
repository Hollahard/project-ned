"""Unit tests for MCP server configuration models."""

import pytest
from pathlib import Path

from friday.mcp.config import MCPServerConfig, MCPConfig


def test_mcp_server_config_valid():
    conf = MCPServerConfig(
        name="test_server",
        command="python",
        args=["-m", "server"],
        env={"CUSTOM_VAR": "value"},
        cwd=".",
        risk_level=2,
        enabled=True,
        timeout_seconds=45,
    )
    assert conf.name == "test_server"
    assert conf.command == "python"
    assert conf.args == ["-m", "server"]
    assert conf.env["CUSTOM_VAR"] == "value"
    assert conf.risk_level == 2
    assert conf.timeout_seconds == 45


def test_mcp_server_config_invalid_name():
    with pytest.raises(ValueError):
        MCPServerConfig(
            name="Invalid Server Name!",
            command="python",
        )


def test_mcp_config_from_dict():
    data = {
        "servers": {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
                "risk_level": 1,
            },
            "fetch": {
                "command": "python",
                "args": ["-m", "fetch"],
                "enabled": False,
            },
        }
    }
    config = MCPConfig.from_dict(data)
    assert len(config.servers) == 2
    assert config.servers["sqlite"].name == "sqlite"
    assert config.servers["sqlite"].risk_level == 1
    assert config.servers["fetch"].enabled is False


def test_mcp_config_from_toml(tmp_path: Path):
    toml_file = tmp_path / "friday.toml"
    toml_content = """
[mcp.servers.local_math]
command = "python"
args = ["math_server.py"]
risk_level = 0
timeout_seconds = 15
"""
    toml_file.write_text(toml_content, encoding="utf-8")
    config = MCPConfig.from_toml(toml_file)
    assert "local_math" in config.servers
    server = config.servers["local_math"]
    assert server.command == "python"
    assert server.risk_level == 0
    assert server.timeout_seconds == 15
