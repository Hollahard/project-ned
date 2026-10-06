"""Tool registry for registering and discovering tools."""

import logging
from typing import Dict, List, Any
from friday.tools.base import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry maintaining active tool instances and catalog schemas."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool registration: %s", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s (risk=%d)", tool.name, tool.risk_level)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        return list(self._tools.values())

    def get_schemas(self, allowed_names: List[str] | None = None) -> List[Dict[str, Any]]:
        """Return OpenAI-compatible function schemas for active tools."""
        schemas = []
        for name, tool in self._tools.items():
            if allowed_names is None or name in allowed_names:
                schemas.append(tool.to_schema())
        return schemas
