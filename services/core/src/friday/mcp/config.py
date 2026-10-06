"""Configuration models for MCP servers in Project Friday."""

import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server process."""

    name: str = Field(..., description="Server identifier, e.g. 'sqlite' or 'fetch'")
    command: str = Field(..., description="Executable path or command name to spawn")
    args: List[str] = Field(default_factory=list, description="Argument vector passed to command")
    env: Dict[str, str] = Field(default_factory=dict, description="Explicit environment variables for server")
    cwd: Optional[str] = Field(default=None, description="Working directory for the server process")
    risk_level: int = Field(default=2, ge=0, le=3, description="Default risk level for tools from this server")
    tool_risk_overrides: Dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool risk level overrides: {'tool_name': 0}",
    )
    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    timeout_seconds: int = Field(default=30, ge=1, le=300, description="Invocation timeout in seconds")

    @field_validator("name")
    @classmethod
    def validate_server_name(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[a-z0-9_]+$", clean):
            raise ValueError(f"Server name '{v}' must be alphanumeric lowercase and underscores only")
        return clean


class MCPConfig(BaseModel):
    """Aggregate MCP configuration."""

    servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        servers_data = data.get("servers", {})
        servers = {}
        for s_name, s_conf in servers_data.items():
            if isinstance(s_conf, dict):
                conf_dict = dict(s_conf)
                if "name" not in conf_dict:
                    conf_dict["name"] = s_name
                servers[s_name] = MCPServerConfig(**conf_dict)
            elif isinstance(s_conf, MCPServerConfig):
                servers[s_name] = s_conf
        return cls(servers=servers)

    @classmethod
    def from_toml(cls, toml_path: Path) -> "MCPConfig":
        if not toml_path.exists():
            return cls(servers={})
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        mcp_section = data.get("mcp", data)
        return cls.from_dict(mcp_section)
