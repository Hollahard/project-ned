"""MCP stdio client session manager running inside Windows Job Object."""

import asyncio
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import mcp.types as mcp_types

from friday.mcp.config import MCPServerConfig
from friday.security.paths import is_path_within_root
from friday.tools.terminal_exec import SAFE_ENV_WHITELIST

logger = logging.getLogger(__name__)


class MCPClientState(str, Enum):
    UNINITIALIZED = "uninitialized"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class MCPClientSession:
    """Manages an active stdio session with an external MCP server."""

    def __init__(
        self,
        config: MCPServerConfig,
        safe_roots: Optional[List[Path]] = None,
    ) -> None:
        self.config = config
        self.safe_roots = safe_roots or []
        self.state = MCPClientState.UNINITIALIZED
        self._error: Optional[str] = None

        self._queue: asyncio.Queue[
            Optional[Tuple[str, Any, asyncio.Future[Any]]]
        ] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._connected_event = asyncio.Event()
        self._session_active = False

    @property
    def is_connected(self) -> bool:
        return self.state == MCPClientState.CONNECTED and self._session_active

    def get_sanitized_env(self) -> Dict[str, str]:
        """Construct child environment with strictly whitelisted variables + explicit server config."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in SAFE_ENV_WHITELIST
        }
        # Merge explicit server environment variables
        env.update(self.config.env)
        return env

    def validate_working_dir(self) -> Optional[Path]:
        """Verify working directory containment within safe roots if configured."""
        if not self.config.cwd:
            return None

        cwd_path = Path(self.config.cwd).resolve()
        if self.safe_roots and not any(is_path_within_root(cwd_path, root) for root in self.safe_roots):
            raise ValueError(
                f"MCP server '{self.config.name}' working_dir is outside configured safe roots: {cwd_path}"
            )
        return cwd_path

    async def connect(self) -> None:
        """Spawn the MCP server process in Job Object and initialize the protocol handshake."""
        if self.is_connected:
            return

        self.state = MCPClientState.CONNECTING
        self._error = None
        self._connected_event.clear()

        # 1. Validate working directory
        cwd_path = self.validate_working_dir()

        # 2. Build sanitized environment
        env = self.get_sanitized_env()

        # 3. Formulate server parameters (argument vector only, no shell)
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=env,
            cwd=str(cwd_path) if cwd_path else None,
        )

        # 4. Launch session loop task
        self._worker_task = asyncio.create_task(
            self._session_worker(server_params),
            name=f"mcp-session-{self.config.name}",
        )

        # Wait for handshake completion or failure
        try:
            await asyncio.wait_for(
                self._connected_event.wait(),
                timeout=float(self.config.timeout_seconds),
            )
        except asyncio.TimeoutError:
            self.state = MCPClientState.ERROR
            self._error = f"Handshake timed out after {self.config.timeout_seconds}s"
            await self.disconnect()
            raise TimeoutError(self._error)

        if not self._session_active:
            self.state = MCPClientState.ERROR
            err = self._error or "Connection failed during handshake"
            raise ConnectionError(f"Failed to connect to MCP server '{self.config.name}': {err}")

        self.state = MCPClientState.CONNECTED
        logger.info("Successfully connected to MCP server '%s'", self.config.name)

    async def _session_worker(self, server_params: StdioServerParameters) -> None:
        """Internal worker task holding the anyio task group and ClientSession open."""
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self._session_active = True
                    self._connected_event.set()

                    while True:
                        request = await self._queue.get()
                        if request is None:
                            # Shutdown sentinel
                            self._queue.task_done()
                            break

                        action, payload, future = request
                        try:
                            if action == "list_tools":
                                res = await session.list_tools()
                                if not future.done():
                                    future.set_result(res.tools)
                            elif action == "call_tool":
                                tool_name, tool_args = payload
                                res = await session.call_tool(tool_name, tool_args)
                                if not future.done():
                                    future.set_result(res)
                            elif action == "ping":
                                await session.send_ping()
                                if not future.done():
                                    future.set_result(True)
                            else:
                                if not future.done():
                                    future.set_exception(ValueError(f"Unknown action: {action}"))
                        except Exception as req_exc:
                            logger.error(
                                "Error handling action '%s' for server '%s': %s",
                                action,
                                self.config.name,
                                req_exc,
                            )
                            if not future.done():
                                future.set_exception(req_exc)
                        finally:
                            self._queue.task_done()

        except Exception as exc:
            logger.error("MCP session worker error for server '%s': %s", self.config.name, exc)
            self._error = str(exc)
            self.state = MCPClientState.ERROR
        finally:
            self._session_active = False
            self._connected_event.set()
            # Drain any pending requests
            while not self._queue.empty():
                try:
                    req = self._queue.get_nowait()
                    if req and req[2] and not req[2].done():
                        req[2].set_exception(
                            ConnectionError(f"MCP server '{self.config.name}' disconnected: {self._error}")
                        )
                    self._queue.task_done()
                except (asyncio.QueueEmpty, ValueError):
                    break

    async def list_tools(self) -> List[mcp_types.Tool]:
        """Query available tools from the MCP server."""
        if not self.is_connected:
            raise ConnectionError(f"MCP server '{self.config.name}' is not connected")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[List[mcp_types.Tool]] = loop.create_future()
        await self._queue.put(("list_tools", None, future))

        try:
            return await asyncio.wait_for(future, timeout=float(self.config.timeout_seconds))
        except asyncio.TimeoutError:
            raise TimeoutError(f"list_tools timed out for server '{self.config.name}'")

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> mcp_types.CallToolResult:
        """Invoke a tool on the MCP server."""
        if not self.is_connected:
            raise ConnectionError(f"MCP server '{self.config.name}' is not connected")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[mcp_types.CallToolResult] = loop.create_future()
        await self._queue.put(("call_tool", (tool_name, arguments), future))

        try:
            return await asyncio.wait_for(future, timeout=float(self.config.timeout_seconds))
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"call_tool '{tool_name}' timed out after {self.config.timeout_seconds}s for server '{self.config.name}'"
            )

    async def disconnect(self) -> None:
        """Gracefully disconnect and terminate the MCP server process."""
        if self._worker_task and not self._worker_task.done():
            # Send shutdown sentinel
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("MCP server '%s' did not stop in time; cancelling worker", self.config.name)
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except Exception:
                    pass

        self._session_active = False
        self._worker_task = None
        self.state = MCPClientState.DISCONNECTED
        logger.info("Disconnected MCP server '%s'", self.config.name)
