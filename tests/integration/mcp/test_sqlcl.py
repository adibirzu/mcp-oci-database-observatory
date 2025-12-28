"""Integration tests for Oracle SQLcl MCP connection.

These tests verify connectivity to the actual SQLcl MCP server.
They require SQLcl to be installed and configured.

Run with: pytest tests/integration/mcp/test_sqlcl.py -v
"""

import os
import pytest
import shutil
from pathlib import Path

from src.core import settings
from src.mcp.client.stdio import StdioTransport
from src.mcp.client.client import MCPClient


# Check if SQLcl is available
def sqlcl_available() -> bool:
    """Check if SQLcl is installed and accessible."""
    sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")
    return Path(sqlcl_path).exists() or shutil.which("sql") is not None


def get_sqlcl_path() -> str:
    """Get the SQLcl binary path."""
    custom_path = os.getenv("SQLCL_PATH")
    if custom_path and Path(custom_path).exists():
        return custom_path

    # Try common locations
    common_paths = [
        "/Applications/sqlcl/bin/sql",
        "/opt/sqlcl/bin/sql",
        "/usr/local/bin/sql",
    ]
    for path in common_paths:
        if Path(path).exists():
            return path

    # Try PATH
    sql_in_path = shutil.which("sql")
    if sql_in_path:
        return sql_in_path

    return ""


# Skip all tests if SQLcl not available
pytestmark = pytest.mark.skipif(
    not sqlcl_available(),
    reason="SQLcl not installed or not in PATH",
)


@pytest.fixture
def sqlcl_transport():
    """Create SQLcl StdioTransport."""
    sqlcl_path = get_sqlcl_path()
    return StdioTransport(
        command=sqlcl_path,
        args=["-mcp"],
        env={},
    )


@pytest.fixture
def sqlcl_client(sqlcl_transport):
    """Create SQLcl MCPClient."""
    return MCPClient("sqlcl", sqlcl_transport)


class TestSQLclConnection:
    """Tests for SQLcl MCP connection."""

    @pytest.mark.asyncio
    async def test_sqlcl_transport_connect(self, sqlcl_transport):
        """Test that SQLcl transport can connect."""
        try:
            await sqlcl_transport.connect()
            assert sqlcl_transport.is_connected
        finally:
            await sqlcl_transport.disconnect()

    @pytest.mark.asyncio
    async def test_sqlcl_transport_disconnect(self, sqlcl_transport):
        """Test that SQLcl transport can disconnect cleanly."""
        await sqlcl_transport.connect()
        assert sqlcl_transport.is_connected

        await sqlcl_transport.disconnect()
        assert not sqlcl_transport.is_connected


class TestSQLclToolDiscovery:
    """Tests for SQLcl tool discovery."""

    @pytest.mark.asyncio
    async def test_list_tools(self, sqlcl_client):
        """Test listing available SQLcl tools."""
        try:
            await sqlcl_client.connect()
            tools = sqlcl_client.get_tools()

            assert len(tools) > 0
            tool_names = [t.get("name") for t in tools]
            print(f"SQLcl tools: {tool_names}")

            # Verify expected tools exist
            expected_tools = ["list-connections", "connect", "run-sql"]
            for expected in expected_tools:
                assert any(
                    expected in name for name in tool_names
                ), f"Expected tool '{expected}' not found"

        finally:
            await sqlcl_client.disconnect()

    @pytest.mark.asyncio
    async def test_tools_have_schemas(self, sqlcl_client):
        """Test that SQLcl tools have proper schemas."""
        try:
            await sqlcl_client.connect()
            tools = sqlcl_client.get_tools()

            for tool in tools:
                assert "name" in tool, "Tool missing name"
                assert "description" in tool or tool.get("description") is None
                # inputSchema is optional but should be dict if present
                if "inputSchema" in tool:
                    assert isinstance(tool["inputSchema"], dict)

        finally:
            await sqlcl_client.disconnect()


class TestSQLclToolExecution:
    """Tests for SQLcl tool execution."""

    @pytest.mark.asyncio
    async def test_list_connections(self, sqlcl_client):
        """Test listing database connections."""
        try:
            await sqlcl_client.connect()

            result = await sqlcl_client.call_tool("list-connections", {})
            print(f"Connections result: {result}")

            # Result should be a valid response (may be empty list)
            assert result is not None

        finally:
            await sqlcl_client.disconnect()

    @pytest.mark.asyncio
    async def test_ping_tool(self, sqlcl_client):
        """Test ping tool if available."""
        try:
            await sqlcl_client.connect()
            tools = sqlcl_client.get_tools()
            tool_names = [t.get("name") for t in tools]

            if "ping" in tool_names:
                result = await sqlcl_client.call_tool("ping", {})
                assert result is not None
            else:
                pytest.skip("Ping tool not available in SQLcl")

        finally:
            await sqlcl_client.disconnect()


class TestSQLclErrorHandling:
    """Tests for SQLcl error handling."""

    @pytest.mark.asyncio
    async def test_invalid_tool_call(self, sqlcl_client):
        """Test calling a non-existent tool."""
        try:
            await sqlcl_client.connect()

            # This should raise an error or return error response
            with pytest.raises(Exception):
                await sqlcl_client.call_tool("nonexistent-tool-xyz", {})

        finally:
            await sqlcl_client.disconnect()

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, sqlcl_client):
        """Test reconnecting after disconnect."""
        # First connection
        await sqlcl_client.connect()
        assert sqlcl_client.is_connected
        await sqlcl_client.disconnect()
        assert not sqlcl_client.is_connected

        # Reconnect
        await sqlcl_client.connect()
        assert sqlcl_client.is_connected
        await sqlcl_client.disconnect()


# Conditional tests that require database connection
@pytest.mark.skipif(
    not os.getenv("DB_CONNECTION_NAME"),
    reason="DB_CONNECTION_NAME not set",
)
class TestSQLclDatabaseOperations:
    """Tests requiring actual database connection."""

    @pytest.mark.asyncio
    async def test_connect_to_database(self, sqlcl_client):
        """Test connecting to a configured database."""
        connection_name = os.getenv("DB_CONNECTION_NAME")

        try:
            await sqlcl_client.connect()

            result = await sqlcl_client.call_tool(
                "connect",
                {"connection": connection_name},
            )
            print(f"Database connect result: {result}")

            # Disconnect from database
            await sqlcl_client.call_tool("disconnect", {})

        finally:
            await sqlcl_client.disconnect()

    @pytest.mark.asyncio
    async def test_run_simple_sql(self, sqlcl_client):
        """Test running a simple SQL query."""
        connection_name = os.getenv("DB_CONNECTION_NAME")

        try:
            await sqlcl_client.connect()

            # Connect to database first
            await sqlcl_client.call_tool(
                "connect",
                {"connection": connection_name},
            )

            # Run simple query
            result = await sqlcl_client.call_tool(
                "run-sql",
                {"sql": "SELECT 1 FROM DUAL"},
            )
            print(f"SQL result: {result}")

            # Disconnect from database
            await sqlcl_client.call_tool("disconnect", {})

        finally:
            await sqlcl_client.disconnect()
