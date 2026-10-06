"""Central MCP Host coordinating server lifecycles and tool registry synchronization."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.mcp.adapter import MCPToolAdapter
from friday.mcp.client import MCPClientSession, MCPClientState
from friday.mcp.config import MCPConfig, MCPServerConfig
from friday.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPHost:
    """Manages active MCP server child processes and bridges discovered tools into Friday."""

    def __init__(self, safe_roots: Optional[List[Path]] = None) -> None:
        self.safe_roots = safe_roots or []
        self._configs: Dict[str, MCPServerConfig] = {}
        self._sessions: Dict[str, MCPClientSession] = {}
        self._adapters: Dict[str, List[MCPToolAdapter]] = {}

    def load_config(self, config: MCPConfig | Dict[str, Any]) -> None:
        """Load server configurations from MCPConfig or dict."""
        if isinstance(config, dict):
            config = MCPConfig.from_dict(config)
        for name, s_conf in config.servers.items():
            self.register_server(s_conf)

    def register_server(self, server_config: MCPServerConfig) -> None:
        """Register or update a server configuration."""
        self._configs[server_config.name] = server_config
        logger.info("Registered MCP server configuration: %s", server_config.name)

    async def start_server(self, name: str) -> List[MCPToolAdapter]:
        """Spawn and connect to a single configured MCP server, discovering its tools."""
        conf = self._configs.get(name)
        if not conf:
            raise KeyError(f"MCP server '{name}' is not configured")
        if not conf.enabled:
            logger.info("MCP server '%s' is disabled; skipping start", name)
            return []

        # If already connected, disconnect first to re-initialize
        if name in self._sessions and self._sessions[name].is_connected:
            await self.stop_server(name)

        session = MCPClientSession(conf, safe_roots=self.safe_roots)
        await session.connect()
        self._sessions[name] = session

        # Discover tools from server
        try:
            mcp_tools = await session.list_tools()
        except Exception as exc:
            logger.error("Failed to discover tools from MCP server '%s': %s", name, exc)
            await session.disconnect()
            raise

        adapters = []
        for mcp_tool in mcp_tools:
            risk = conf.tool_risk_overrides.get(mcp_tool.name, conf.risk_level)
            adapter = MCPToolAdapter(
                server_name=name,
                mcp_tool=mcp_tool,
                client_session=session,
                risk_level=risk,
            )
            adapters.append(adapter)

        self._adapters[name] = adapters
        logger.info(
            "MCP server '%s' discovered %d tools: %s",
            name,
            len(adapters),
            [a.name for a in adapters],
        )
        return adapters

    async def stop_server(self, name: str) -> None:
        """Disconnect and stop a running MCP server."""
        session = self._sessions.pop(name, None)
        if session:
            await session.disconnect()
        self._adapters.pop(name, None)
        logger.info("Stopped MCP server '%s'", name)

    async def start_all(self) -> List[MCPToolAdapter]:
        """Boot all enabled MCP servers concurrently and collect their tool adapters."""
        tasks = [
            self.start_server(name)
            for name, conf in self._configs.items()
            if conf.enabled
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_adapters: List[MCPToolAdapter] = []
        for name, res in zip([n for n, c in self._configs.items() if c.enabled], results):
            if isinstance(res, Exception):
                logger.error("Failed to start MCP server '%s': %s", name, res)
            elif isinstance(res, list):
                all_adapters.extend(res)

        return all_adapters

    async def stop_all(self) -> None:
        """Gracefully disconnect all active MCP servers."""
        stop_tasks = [self.stop_server(name) for name in list(self._sessions.keys())]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        self._sessions.clear()
        self._adapters.clear()
        logger.info("All MCP servers stopped.")

    def sync_to_registry(self, registry: ToolRegistry) -> List[MCPToolAdapter]:
        """Register all discovered MCP tool adapters into the Friday ToolRegistry."""
        synced: List[MCPToolAdapter] = []
        for server_name, adapters in self._adapters.items():
            for adapter in adapters:
                registry.register(adapter)
                synced.append(adapter)
        logger.info("Synced %d MCP tools into Friday ToolRegistry", len(synced))
        return synced

    def get_status(self) -> Dict[str, Any]:
        """Telemetry and status dictionary for active MCP servers."""
        status = {}
        for name, conf in self._configs.items():
            session = self._sessions.get(name)
            state = session.state if session else MCPClientState.UNINITIALIZED
            tools = [a.name for a in self._adapters.get(name, [])]
            status[name] = {
                "enabled": conf.enabled,
                "command": conf.command,
                "state": state.value if isinstance(state, MCPClientState) else str(state),
                "is_connected": session.is_connected if session else False,
                "tool_count": len(tools),
                "tools": tools,
            }
        return status
