"""FastAPI application factory for Friday Core."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from friday.config import FridayConfig, load_config
from friday.storage.db import DatabaseManager
from friday.sessions.manager import SessionManager
from friday.security.tokens import CapabilityTokenManager
from friday.tools.registry import ToolRegistry
from friday.tools.policy import PolicyEngine
from friday.tools.native_read import (
    FilesystemReadTool,
    FilesystemListTool,
    GitStatusTool,
    GitDiffTool,
    SystemInfoTool,
)
from friday.tools.filesystem_write import FilesystemWriteTool, FilesystemRollbackTool
from friday.tools.terminal_exec import TerminalExecTool
from friday.inference.protocol import InferenceBackend
from friday.inference.mock import MockInferenceBackend
from friday.inference.telemetry import TelemetryProvider
from friday.inference.gaming_mode import GamingModeController
from friday.agent.loop import AgentLoop
from friday.mcp import MCPHost

logger = logging.getLogger(__name__)


def create_app(
    config: FridayConfig | None = None,
    inference: InferenceBackend | None = None,
) -> FastAPI:
    """Create and configure the Friday Core FastAPI application."""
    config = config or load_config()
    db_manager = DatabaseManager(config.storage.database_path)
    session_manager = SessionManager(db_manager)
    token_manager = CapabilityTokenManager(config.security.approval_secret)

    # Initialize tools & policy
    tool_registry = ToolRegistry()
    tool_registry.register(FilesystemReadTool())
    tool_registry.register(FilesystemListTool())
    tool_registry.register(GitStatusTool())
    tool_registry.register(GitDiffTool())
    tool_registry.register(SystemInfoTool())
    tool_registry.register(FilesystemWriteTool(safe_roots=[config.workspace_root]))
    tool_registry.register(FilesystemRollbackTool())
    tool_registry.register(TerminalExecTool(safe_roots=[config.workspace_root]))


    policy_engine = PolicyEngine(
        token_manager=token_manager,
        safe_roots=[config.workspace_root],
        approval_level=config.security.approval_level,
    )

    inference_backend = inference or MockInferenceBackend()
    agent_loop = AgentLoop(
        inference=inference_backend,
        tools=tool_registry,
        policy=policy_engine,
    )
    from friday.api.websocket import manager as ws_manager
    telemetry_provider = TelemetryProvider()
    gaming_mode_controller = GamingModeController(
        telemetry_provider=telemetry_provider,
        connection_manager=ws_manager,
    )

    mcp_host = MCPHost(safe_roots=[config.workspace_root])

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing Friday Core storage and components...")
        await db_manager.initialize()
        if getattr(config, "mcp", None) and config.mcp.servers:
            mcp_host.load_config(config.mcp)
            await mcp_host.start_all()
            mcp_host.sync_to_registry(tool_registry)
        yield
        logger.info("Shutting down Friday Core storage and MCP host...")
        await mcp_host.stop_all()
        await db_manager.close()

    app = FastAPI(
        title="Friday Core API",
        version="0.1.0",
        description="Local agent operating system backend for Project Friday",
        lifespan=lifespan,
    )

    # Attach shared state
    app.state.config = config
    app.state.db_manager = db_manager
    app.state.session_manager = session_manager
    app.state.token_manager = token_manager
    app.state.tool_registry = tool_registry
    app.state.policy_engine = policy_engine
    app.state.inference_backend = inference_backend
    app.state.agent_loop = agent_loop
    app.state.telemetry_provider = telemetry_provider
    app.state.gaming_mode_controller = gaming_mode_controller
    app.state.mcp_host = mcp_host

    # Security middleware: Reject non-loopback Host / Origin headers
    @app.middleware("http")
    async def loopback_security_middleware(request: Request, call_next) -> Response:
        if config.security.validate_host_origin:
            host_header = request.headers.get("host", "")
            # Check loopback host (and testserver for internal test harness)
            if not (host_header.startswith("127.0.0.1") or host_header.startswith("localhost") or host_header.startswith("testserver")):
                logger.warning("Rejected non-loopback host: %s", host_header)
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Forbidden: Non-loopback Host header"},
                )

            origin = request.headers.get("origin")
            if origin and origin not in config.security.allowed_origins:
                # Disallow arbitrary browser origins
                if not (origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")):
                    logger.warning("Rejected unauthorized origin: %s", origin)
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "Forbidden: Unauthorized Origin"},
                    )

        # Bearer token validation if configured
        if config.security.bearer_token and request.url.path != "/health":
            auth_header = request.headers.get("authorization", "")
            expected_auth = f"Bearer {config.security.bearer_token}"
            if auth_header != expected_auth:
                logger.warning("Rejected request with invalid or missing Bearer token")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Unauthorized: Invalid or missing Bearer token"},
                )

        return await call_next(request)

    # Health check
    @app.get("/health")
    async def health_check() -> dict:
        backend_health = await app.state.inference_backend.health()
        return {
            "status": "ok",
            "version": "0.1.0",
            "inference": {
                "healthy": backend_health.healthy,
                "state": backend_health.state,
                "model_id": backend_health.model_id,
            },
        }

    from friday.api.routes import router
    from friday.api.websocket import ws_router
    app.include_router(router)
    app.include_router(ws_router)

    @app.get("/api/v1/mcp/status")
    async def get_mcp_status() -> dict:
        return app.state.mcp_host.get_status()

    return app
