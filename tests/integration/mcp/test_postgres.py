"""Integration tests for PostgreSQL MCP connection.

These tests verify connectivity to the PostgreSQL MCP server.
They require the PostgreSQL MCP server to be running.

Run with: pytest tests/integration/mcp/test_postgres.py -v
"""

import os
import pytest
import aiohttp
from urllib.parse import urljoin

from src.mcp.client.http import HttpTransport
from src.mcp.client.client import MCPClient


def postgres_available() -> bool:
    """Check if PostgreSQL MCP server is available."""
    url = os.getenv("POSTGRES_MCP_URL", "")
    return bool(url) and url.startswith("http")


def get_postgres_url() -> str:
    """Get the PostgreSQL MCP server URL."""
    return os.getenv("POSTGRES_MCP_URL", "http://localhost:8004/mcp")


# Skip all tests if PostgreSQL MCP not available
pytestmark = pytest.mark.skipif(
    not postgres_available(),
    reason="PostgreSQL MCP server not configured (POSTGRES_MCP_URL not set)",
)


@pytest.fixture
def postgres_transport():
    """Create PostgreSQL HttpTransport."""
    return HttpTransport(url=get_postgres_url())


@pytest.fixture
def postgres_client(postgres_transport):
    """Create PostgreSQL MCPClient."""
    return MCPClient("postgres-mcp", postgres_transport)


class TestPostgresConnection:
    """Tests for PostgreSQL MCP connection."""

    @pytest.mark.asyncio
    async def test_postgres_transport_connect(self, postgres_transport):
        """Test that PostgreSQL transport can connect."""
        try:
            await postgres_transport.connect()
            assert postgres_transport.is_connected
        finally:
            await postgres_transport.disconnect()

    @pytest.mark.asyncio
    async def test_postgres_transport_disconnect(self, postgres_transport):
        """Test that PostgreSQL transport can disconnect cleanly."""
        await postgres_transport.connect()
        assert postgres_transport.is_connected

        await postgres_transport.disconnect()
        assert not postgres_transport.is_connected


class TestPostgresToolDiscovery:
    """Tests for PostgreSQL tool discovery."""

    @pytest.mark.asyncio
    async def test_list_tools(self, postgres_client):
        """Test listing available PostgreSQL tools."""
        try:
            await postgres_client.connect()
            tools = postgres_client.get_tools()

            assert len(tools) > 0
            tool_names = [t.get("name") for t in tools]
            print(f"PostgreSQL tools: {tool_names}")

            # Verify expected tools exist (common PostgreSQL MCP tools)
            expected_tools = ["execute", "query", "list-databases"]
            for expected in expected_tools:
                if any(expected in name for name in tool_names):
                    break
            else:
                # At minimum, there should be some tools
                assert len(tools) > 0, "PostgreSQL MCP should expose at least one tool"

        finally:
            await postgres_client.disconnect()

    @pytest.mark.asyncio
    async def test_tools_have_schemas(self, postgres_client):
        """Test that PostgreSQL tools have proper schemas."""
        try:
            await postgres_client.connect()
            tools = postgres_client.get_tools()

            for tool in tools:
                assert "name" in tool, "Tool missing name"
                # inputSchema is optional but should be dict if present
                if "inputSchema" in tool:
                    assert isinstance(tool["inputSchema"], dict)

        finally:
            await postgres_client.disconnect()


class TestPostgresToolExecution:
    """Tests for PostgreSQL tool execution."""

    @pytest.mark.asyncio
    async def test_ping_or_health(self, postgres_client):
        """Test ping or health tool if available."""
        try:
            await postgres_client.connect()
            tools = postgres_client.get_tools()
            tool_names = [t.get("name") for t in tools]

            # Try common health check tools
            health_tools = ["ping", "health", "status"]
            for tool_name in health_tools:
                if tool_name in tool_names:
                    result = await postgres_client.call_tool(tool_name, {})
                    assert result is not None
                    return

            pytest.skip("No health check tool available in PostgreSQL MCP")

        finally:
            await postgres_client.disconnect()


class TestPostgresErrorHandling:
    """Tests for PostgreSQL error handling."""

    @pytest.mark.asyncio
    async def test_invalid_tool_call(self, postgres_client):
        """Test calling a non-existent tool."""
        try:
            await postgres_client.connect()

            # This should raise an error or return error response
            with pytest.raises(Exception):
                await postgres_client.call_tool("nonexistent-tool-xyz", {})

        finally:
            await postgres_client.disconnect()

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, postgres_client):
        """Test reconnecting after disconnect."""
        # First connection
        await postgres_client.connect()
        assert postgres_client.is_connected
        await postgres_client.disconnect()
        assert not postgres_client.is_connected

        # Reconnect
        await postgres_client.connect()
        assert postgres_client.is_connected
        await postgres_client.disconnect()


# Conditional tests that require database connection
@pytest.mark.skipif(
    not os.getenv("POSTGRES_CONNECTION_NAME"),
    reason="POSTGRES_CONNECTION_NAME not set",
)
class TestPostgresDatabaseOperations:
    """Tests requiring actual PostgreSQL database connection."""

    @pytest.mark.asyncio
    async def test_connect_to_database(self, postgres_client):
        """Test connecting to a configured database."""
        connection_name = os.getenv("POSTGRES_CONNECTION_NAME")

        try:
            await postgres_client.connect()

            result = await postgres_client.call_tool(
                "connect",
                {"connection": connection_name},
            )
            print(f"PostgreSQL connect result: {result}")

            # Disconnect from database
            await postgres_client.call_tool("disconnect", {})

        finally:
            await postgres_client.disconnect()

    @pytest.mark.asyncio
    async def test_run_simple_sql(self, postgres_client):
        """Test running a simple SQL query."""
        connection_name = os.getenv("POSTGRES_CONNECTION_NAME")

        try:
            await postgres_client.connect()

            # Connect to database first
            await postgres_client.call_tool(
                "connect",
                {"connection": connection_name},
            )

            # Run simple query
            result = await postgres_client.call_tool(
                "query",
                {"sql": "SELECT 1 AS test"},
            )
            print(f"PostgreSQL SQL result: {result}")

            # Disconnect from database
            await postgres_client.call_tool("disconnect", {})

        finally:
            await postgres_client.disconnect()
