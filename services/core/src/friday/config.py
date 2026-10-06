"""Configuration management for Friday Core."""

import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8200
    ipv6_enabled: bool = False


class TabbySettings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 5000
    admin_key: str = Field(default="", description="Admin key for TabbyAPI, managed by supervisor")


class SecuritySettings(BaseSettings):
    validate_host_origin: bool = True
    allowed_origins: list[str] = ["tauri://localhost", "http://tauri.localhost"]
    approval_secret: str = Field(default="dev-insecure-secret-change-in-prod", description="HMAC secret for one-shot tokens")
    powershell_constrained_language: bool = True
    approval_level: int = 1
    bearer_token: str = Field(default="", description="Per-launch bearer token for Core API")


class StorageSettings(BaseSettings):
    database_path: str = "state.db"
    wal_mode: bool = True


class AgentSettings(BaseSettings):
    max_iterations: int = 20
    max_wall_clock_seconds: int = 900
    max_consecutive_tool_failures: int = 5
    default_context_budget: int = 32768


class FridayConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRIDAY_", extra="ignore")

    server: ServerSettings = Field(default_factory=ServerSettings)
    tabby: TabbySettings = Field(default_factory=TabbySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    workspace_root: Path = Field(default_factory=lambda: Path.cwd())


def load_config() -> FridayConfig:
    """Load configuration from environment and defaults."""
    config = FridayConfig()
    logger.info("Loaded Friday configuration bound to %s:%s", config.server.host, config.server.port)
    return config
