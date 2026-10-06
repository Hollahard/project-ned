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
from friday.inference.protocol import InferenceBackend
from friday.inference.mock import MockInferenceBackend
from friday.agent.loop import AgentLoop

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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing Friday Core storage and components...")
        await db_manager.initialize()
        yield
        logger.info("Shutting down Friday Core storage...")
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

    # Security middleware: Reject non-loopback Host / Origin headers
    @app.middleware("http")
    async def loopback_security_middleware(request: Request, call_next) -> Response:
        if config.security.validate_host_origin:
            host_header = request.headers.get("host", "")
            # Check loopback host
            if not (host_header.startswith("127.0.0.1") or host_header.startswith("localhost")):
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
    app.include_router(router)

    return app
