"""Unit tests for MCPToolAdapter schema bridging and output handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import mcp.types as mcp_types

from friday.mcp.adapter import MCPToolAdapter
from friday.mcp.client import MCPClientSession, MCPClientState
from friday.mcp.config import MCPServerConfig


@pytest.fixture
def mock_client_session():
    conf = MCPServerConfig(name="test_srv", command="python")
    session = MagicMock(spec=MCPClientSession)
    session.config = conf
    session.is_connected = True
    session.state = MCPClientState.CONNECTED
    return session


def test_mcp_tool_adapter_naming_and_schema(mock_client_session):
    mcp_tool = mcp_types.Tool(
        name="read_query",
        description="Execute a read-only SQL query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL statement"}
            },
            "required": ["query"],
        },
    )

    adapter = MCPToolAdapter(
        server_name="sqlite",
        mcp_tool=mcp_tool,
        client_session=mock_client_session,
        risk_level=2,
    )

    assert adapter.name == "mcp_sqlite.read_query"
    assert "read-only SQL query" in adapter.description
    assert adapter.risk_level == 2
    assert adapter.requires_approval is True
    assert adapter.parameters_schema["properties"]["query"]["type"] == "string"

    # Hermes / OpenAI format schema
    schema = adapter.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp_sqlite.read_query"


@pytest.mark.asyncio
async def test_mcp_tool_adapter_execute_success(mock_client_session):
    mcp_tool = mcp_types.Tool(
        name="fetch_url",
        description="Fetch web page",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    )
    adapter = MCPToolAdapter(
        server_name="network",
        mcp_tool=mcp_tool,
        client_session=mock_client_session,
    )

    mock_client_session.call_tool = AsyncMock(
        return_value=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="<html>Example content</html>")],
            is_error=False,
        )
    )

    result = await adapter.execute("call-1", {"url": "https://example.com"})
    assert result.success is True
    assert "<html>Example content</html>" in result.output
    assert result.error is None


@pytest.mark.asyncio
async def test_mcp_tool_adapter_output_truncation(mock_client_session):
    mcp_tool = mcp_types.Tool(
        name="dump_data",
        description="Dump large data",
        input_schema={"type": "object", "properties": {}},
    )
    # Output limit 100 characters for test
    adapter = MCPToolAdapter(
        server_name="data",
        mcp_tool=mcp_tool,
        client_session=mock_client_session,
        output_limit=100,
    )

    large_text = "A" * 500
    mock_client_session.call_tool = AsyncMock(
        return_value=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=large_text)],
            is_error=False,
        )
    )

    result = await adapter.execute("call-2", {})
    assert result.success is True
    assert "[Output truncated: 500 total characters exceeded limit of 100]" in result.output
    assert len(result.output) < 500


@pytest.mark.asyncio
async def test_mcp_tool_adapter_handles_server_error(mock_client_session):
    mcp_tool = mcp_types.Tool(
        name="failing_tool",
        description="Fails",
        input_schema={"type": "object", "properties": {}},
    )
    adapter = MCPToolAdapter(
        server_name="buggy",
        mcp_tool=mcp_tool,
        client_session=mock_client_session,
    )

    mock_client_session.call_tool = AsyncMock(
        return_value=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Syntax error in query")],
            is_error=True,
        )
    )

    result = await adapter.execute("call-3", {})
    assert result.success is False
    assert "Syntax error in query" in result.error


@pytest.mark.asyncio
async def test_mcp_tool_adapter_disconnected_session(mock_client_session):
    mock_client_session.is_connected = False
    mcp_tool = mcp_types.Tool(
        name="any_tool",
        description="Any",
        input_schema={"type": "object", "properties": {}},
    )
    adapter = MCPToolAdapter(
        server_name="offline",
        mcp_tool=mcp_tool,
        client_session=mock_client_session,
    )

    result = await adapter.execute("call-4", {})
    assert result.success is False
    assert "is not connected" in result.error
