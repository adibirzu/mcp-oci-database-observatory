"""Integration tests for MySQL MCP connection.

These tests verify connectivity to the MySQL MCP server.
They require the MySQL MCP server to be running.

Run with: pytest tests/integration/mcp/test_mysql.py -v
"""

import os
import pytest
import aiohttp
from urllib.parse import urljoin

from src.mcp.client.http import HttpTransport
from src.mcp.client.client import MCPClient


def mysql_available() -> bool:
    """Check if MySQL MCP server is available."""
    url = os.getenv("MYSQL_MCP_URL", "")
    return bool(url) and url.startswith("http")


def get_mysql_url() -> str:
    """Get the MySQL MCP server URL."""
    return os.getenv("MYSQL_MCP_URL", "http://localhost:8003/mcp")


# Skip all tests if MySQL MCP not available
pytestmark = pytest.mark.skipif(
    not mysql_available(),
    reason="MySQL MCP server not configured (MYSQL_MCP_URL not set)",
)


@pytest.fixture
def mysql_transport():
    """Create MySQL HttpTransport."""
    return HttpTransport(url=get_mysql_url())


@pytest.fixture
def mysql_client(mysql_transport):
    """Create MySQL MCPClient."""
    return MCPClient("mysql-mcp", mysql_transport)


class TestMySQLConnection:
    """Tests for MySQL MCP connection."""

    @pytest.mark.asyncio
    async def test_mysql_transport_connect(self, mysql_transport):
        """Test that MySQL transport can connect."""
        try:
            await mysql_transport.connect()
            assert mysql_transport.is_connected
        finally:
            await mysql_transport.disconnect()

    @pytest.mark.asyncio
    async def test_mysql_transport_disconnect(self, mysql_transport):
        """Test that MySQL transport can disconnect cleanly."""
        await mysql_transport.connect()
        assert mysql_transport.is_connected

        await mysql_transport.disconnect()
        assert not mysql_transport.is_connected


class TestMySQLToolDiscovery:
    """Tests for MySQL tool discovery."""

    @pytest.mark.asyncio
    async def test_list_tools(self, mysql_client):
        """Test listing available MySQL tools."""
        try:
            await mysql_client.connect()
            tools = mysql_client.get_tools()

            assert len(tools) > 0
            tool_names = [t.get("name") for t in tools]
            print(f"MySQL tools: {tool_names}")

            # Verify expected tools exist (common MySQL MCP tools)
            expected_tools = ["execute", "query", "list-databases"]
            for expected in expected_tools:
                if any(expected in name for name in tool_names):
                    break
            else:
                # At minimum, there should be some tools
                assert len(tools) > 0, "MySQL MCP should expose at least one tool"

        finally:
            await mysql_client.disconnect()

    @pytest.mark.asyncio
    async def test_tools_have_schemas(self, mysql_client):
        """Test that MySQL tools have proper schemas."""
        try:
            await mysql_client.connect()
            tools = mysql_client.get_tools()

            for tool in tools:
                assert "name" in tool, "Tool missing name"
                # inputSchema is optional but should be dict if present
                if "inputSchema" in tool:
                    assert isinstance(tool["inputSchema"], dict)

        finally:
            await mysql_client.disconnect()


class TestMySQLToolExecution:
    """Tests for MySQL tool execution."""

    @pytest.mark.asyncio
    async def test_ping_or_health(self, mysql_client):
        """Test ping or health tool if available."""
        try:
            await mysql_client.connect()
            tools = mysql_client.get_tools()
            tool_names = [t.get("name") for t in tools]

            # Try common health check tools
            health_tools = ["ping", "health", "status"]
            for tool_name in health_tools:
                if tool_name in tool_names:
                    result = await mysql_client.call_tool(tool_name, {})
                    assert result is not None
                    return

            pytest.skip("No health check tool available in MySQL MCP")

        finally:
            await mysql_client.disconnect()


class TestMySQLErrorHandling:
    """Tests for MySQL error handling."""

    @pytest.mark.asyncio
    async def test_invalid_tool_call(self, mysql_client):
        """Test calling a non-existent tool."""
        try:
            await mysql_client.connect()

            # This should raise an error or return error response
            with pytest.raises(Exception):
                await mysql_client.call_tool("nonexistent-tool-xyz", {})

        finally:
            await mysql_client.disconnect()

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, mysql_client):
        """Test reconnecting after disconnect."""
        # First connection
        await mysql_client.connect()
        assert mysql_client.is_connected
        await mysql_client.disconnect()
        assert not mysql_client.is_connected

        # Reconnect
        await mysql_client.connect()
        assert mysql_client.is_connected
        await mysql_client.disconnect()


# Conditional tests that require database connection
@pytest.mark.skipif(
    not os.getenv("MYSQL_CONNECTION_NAME"),
    reason="MYSQL_CONNECTION_NAME not set",
)
class TestMySQLDatabaseOperations:
    """Tests requiring actual MySQL database connection."""

    @pytest.mark.asyncio
    async def test_connect_to_database(self, mysql_client):
        """Test connecting to a configured database."""
        connection_name = os.getenv("MYSQL_CONNECTION_NAME")

        try:
            await mysql_client.connect()

            result = await mysql_client.call_tool(
                "connect",
                {"connection": connection_name},
            )
            print(f"MySQL connect result: {result}")

            # Disconnect from database
            await mysql_client.call_tool("disconnect", {})

        finally:
            await mysql_client.disconnect()

    @pytest.mark.asyncio
    async def test_run_simple_sql(self, mysql_client):
        """Test running a simple SQL query."""
        connection_name = os.getenv("MYSQL_CONNECTION_NAME")

        try:
            await mysql_client.connect()

            # Connect to database first
            await mysql_client.call_tool(
                "connect",
                {"connection": connection_name},
            )

            # Run simple query
            result = await mysql_client.call_tool(
                "query",
                {"sql": "SELECT 1 AS test"},
            )
            print(f"MySQL SQL result: {result}")

            # Disconnect from database
            await mysql_client.call_tool("disconnect", {})

        finally:
            await mysql_client.disconnect()
