"""Adapter bridging official MCP tools into Project Friday's Tool contracts."""

import logging
from typing import Any, Dict, Optional
import mcp.types as mcp_types

from friday.mcp.client import MCPClientSession
from friday.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MCP_OUTPUT_TRUNCATION_LIMIT = 4000


class MCPToolAdapter(Tool):
    """Bridges an MCP Tool into the Project Friday Tool interface with security gating."""

    def __init__(
        self,
        server_name: str,
        mcp_tool: mcp_types.Tool,
        client_session: MCPClientSession,
        risk_level: int = 2,
        output_limit: int = DEFAULT_MCP_OUTPUT_TRUNCATION_LIMIT,
    ) -> None:
        self.server_name = server_name
        self.original_name = mcp_tool.name
        self.client_session = client_session
        self.output_limit = output_limit

        # Formulate Friday namespaced name: mcp_<server>.<tool> conforming to ^[a-z0-9_]+\.[a-z0-9_]+$
        clean_server = server_name.lower().replace("-", "_")
        clean_tool = mcp_tool.name.lower().replace("-", "_")
        self.name = f"mcp_{clean_server}.{clean_tool}"

        self.description = (
            f"[MCP Plugin: {server_name}] {mcp_tool.description or 'No description provided.'}"
        )
        self.risk_level = risk_level
        self.requires_approval = risk_level >= 2
        self.source = "mcp"

        # Sanitize parameters JSON schema
        raw_schema = getattr(mcp_tool, "input_schema", getattr(mcp_tool, "inputSchema", {}))
        if isinstance(raw_schema, dict):
            schema = dict(raw_schema)
            if "type" not in schema:
                schema["type"] = "object"
            if "properties" not in schema:
                schema["properties"] = {}
        else:
            schema = {"type": "object", "properties": {}}
        self.parameters_schema = schema

    def _extract_content(self, result: mcp_types.CallToolResult) -> str:
        """Extract and format textual content from MCP CallToolResult."""
        text_parts = []
        for item in result.content:
            if isinstance(item, mcp_types.TextContent):
                text_parts.append(item.text)
            elif isinstance(item, mcp_types.ImageContent):
                text_parts.append(f"[Binary image: {item.mimeType}, {len(item.data)} bytes]")
            elif isinstance(item, mcp_types.EmbeddedResource):
                text_parts.append(f"[Embedded resource: {item.resource.uri}]")
            else:
                text_parts.append(str(item))

        raw_output = "\n".join(text_parts).strip()
        if not raw_output:
            return "(no output)"

        # Enforce Context Budget truncation on untrusted MCP outputs
        if len(raw_output) > self.output_limit:
            retained = raw_output[: self.output_limit]
            raw_output = (
                f"{retained}\n\n"
                f"[Output truncated: {len(raw_output)} total characters exceeded limit of {self.output_limit}]"
            )

        return raw_output

    async def execute(self, call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute the MCP tool via the stdio client session with error boundary."""
        if not self.client_session.is_connected:
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"MCP server '{self.server_name}' is not connected.",
            )

        try:
            result = await self.client_session.call_tool(self.original_name, arguments)
            output_str = self._extract_content(result)

            is_error = getattr(result, "is_error", getattr(result, "isError", False))
            if is_error:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call_id,
                    success=False,
                    output="",
                    error=output_str,
                    metadata={"server": self.server_name, "tool": self.original_name},
                )

            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=True,
                output=output_str,
                metadata={"server": self.server_name, "tool": self.original_name},
            )

        except Exception as exc:
            logger.error("MCP tool '%s' execution failed: %s", self.name, exc)
            return ToolResult(
                tool_name=self.name,
                call_id=call_id,
                success=False,
                output="",
                error=f"MCP execution error: {exc}",
                metadata={"server": self.server_name, "tool": self.original_name},
            )
