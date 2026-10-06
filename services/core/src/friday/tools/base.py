"""Base tool definitions for Friday."""

from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    call_id: str
    success: bool
    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Tool(ABC):
    """Abstract base class for all native and MCP tools."""

    name: str
    description: str
    risk_level: int = 0  # 0: read, 1: write, 2: exec, 3: critical
    requires_approval: bool = False
    parameters_schema: Dict[str, Any]

    @abstractmethod
    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute the tool with validated arguments."""
        ...

    def to_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI / Hermes tool call format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
