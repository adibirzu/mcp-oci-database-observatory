"""Tests for MCP Client.

Tests verify transport abstraction, tool discovery, and execution.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.client.client import MCPClient, Transport


class MockTransport(Transport):
    """Mock transport for testing."""

    def __init__(self):
        self._connected = False
        self._tools = []

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def call_tool(self, tool_name: str, params: dict):
        return {"result": f"Called {tool_name}"}

    async def list_tools(self):
        return self._tools

    @property
    def is_connected(self):
        return self._connected


class TestMCPClientInit:
    """Tests for MCPClient initialization."""

    def test_init(self):
        """Test basic initialization."""
        transport = MockTransport()
        client = MCPClient("test-server", transport)

        assert client.server_id == "test-server"
        assert client.transport is transport
        assert client._tools == []

    def test_is_connected_initially_false(self):
        """Test client is not connected initially."""
        transport = MockTransport()
        client = MCPClient("test", transport)

        assert client.is_connected is False


class TestMCPClientConnect:
    """Tests for MCPClient connection."""

    @pytest.mark.asyncio
    async def test_connect_fetches_tools(self):
        """Test that connect fetches tools from server."""
        transport = MockTransport()
        transport._tools = [
            {"name": "run-sql", "description": "Execute SQL"},
            {"name": "connect", "description": "Connect to DB"},
        ]
        client = MCPClient("test", transport)

        await client.connect()

        assert client.is_connected
        assert len(client._tools) == 2
        assert client._tools[0]["name"] == "run-sql"

    @pytest.mark.asyncio
    async def test_get_tools_returns_cached_tools(self):
        """Test that get_tools returns cached tools."""
        transport = MockTransport()
        transport._tools = [{"name": "tool1"}, {"name": "tool2"}]
        client = MCPClient("test", transport)

        await client.connect()
        tools = client.get_tools()

        assert tools == transport._tools


class TestMCPClientDisconnect:
    """Tests for MCPClient disconnection."""

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        transport = MockTransport()
        client = MCPClient("test", transport)

        await client.connect()
        assert client.is_connected

        await client.disconnect()
        assert not client.is_connected


class TestMCPClientCallTool:
    """Tests for MCPClient tool calling."""

    @pytest.mark.asyncio
    async def test_call_tool(self):
        """Test calling a tool."""
        transport = MockTransport()
        client = MCPClient("test", transport)
        await client.connect()

        result = await client.call_tool("run-sql", {"sql": "SELECT 1"})

        assert result["result"] == "Called run-sql"

    @pytest.mark.asyncio
    async def test_call_tool_auto_connects(self):
        """Test that call_tool auto-connects if not connected."""
        transport = MockTransport()
        client = MCPClient("test", transport)

        assert not client.is_connected

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            # Need to set connected after connect is called
            async def side_effect():
                transport._connected = True
            mock_connect.side_effect = side_effect

            await client.call_tool("tool", {})

            mock_connect.assert_called_once()


class TestMCPClientToolDiscovery:
    """Tests for tool discovery functionality."""

    @pytest.mark.asyncio
    async def test_tools_cached_after_connect(self):
        """Test that tools are cached after connection."""
        transport = MockTransport()
        transport._tools = [
            {"name": "tool1", "description": "Desc 1", "inputSchema": {}},
            {"name": "tool2", "description": "Desc 2", "inputSchema": {}},
        ]
        client = MCPClient("test", transport)

        await client.connect()

        # Modify transport tools - should not affect cached version
        transport._tools = []

        tools = client.get_tools()
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_get_tools_before_connect(self):
        """Test get_tools returns empty list before connect."""
        transport = MockTransport()
        transport._tools = [{"name": "tool1"}]
        client = MCPClient("test", transport)

        tools = client.get_tools()

        assert tools == []

    @pytest.mark.asyncio
    async def test_tool_schema_preserved(self):
        """Test that tool schema is preserved correctly."""
        transport = MockTransport()
        transport._tools = [
            {
                "name": "complex-tool",
                "description": "A complex tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "required_param": {"type": "string"},
                        "optional_param": {"type": "integer", "default": 10},
                    },
                    "required": ["required_param"],
                },
            }
        ]
        client = MCPClient("test", transport)

        await client.connect()
        tools = client.get_tools()

        assert len(tools) == 1
        assert tools[0]["inputSchema"]["type"] == "object"
        assert "required_param" in tools[0]["inputSchema"]["properties"]
        assert tools[0]["inputSchema"]["required"] == ["required_param"]
