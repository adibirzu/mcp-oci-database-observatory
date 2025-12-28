"""Tests for MCP Server Registry.

Tests verify server registration, connection management, and tool aggregation.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.mcp.registry.registry import ServerRegistry


@pytest.fixture
def registry():
    """Create a ServerRegistry instance for testing."""
    return ServerRegistry()


class TestServerRegistryInit:
    """Tests for ServerRegistry initialization."""

    def test_init_empty(self):
        """Test registry starts empty."""
        registry = ServerRegistry()

        assert registry._servers == {}
        assert registry._configs == {}


class TestServerRegistration:
    """Tests for server registration."""

    @pytest.mark.asyncio
    async def test_register_http_server(self, registry):
        """Test registering an HTTP server."""
        config = {
            "id": "test-http",
            "name": "Test HTTP Server",
            "transport": "http",
            "url": "http://localhost:8000/mcp",
        }

        with patch("src.mcp.registry.registry.HttpTransport") as MockHttpTransport:
            MockHttpTransport.return_value = MagicMock()
            await registry.register_server(config)

        assert "test-http" in registry._servers
        assert registry._configs["test-http"] == config
        MockHttpTransport.assert_called_once_with(
            url="http://localhost:8000/mcp",
            headers={},
        )

    @pytest.mark.asyncio
    async def test_register_stdio_server(self, registry):
        """Test registering a stdio server."""
        config = {
            "id": "test-stdio",
            "name": "Test Stdio Server",
            "transport": "stdio",
            "command": "/usr/bin/server",
            "args": ["--mcp"],
            "env": {"KEY": "value"},
        }

        with patch("src.mcp.registry.registry.StdioTransport") as MockStdioTransport:
            MockStdioTransport.return_value = MagicMock()
            await registry.register_server(config)

        assert "test-stdio" in registry._servers
        MockStdioTransport.assert_called_once_with(
            command="/usr/bin/server",
            args=["--mcp"],
            env={"KEY": "value"},
        )

    @pytest.mark.asyncio
    async def test_register_unknown_transport_raises(self, registry):
        """Test that unknown transport type raises ValueError."""
        config = {
            "id": "bad",
            "transport": "websocket",
        }

        with pytest.raises(ValueError, match="Unknown transport type"):
            await registry.register_server(config)


class TestServerRegistryInitialize:
    """Tests for registry initialization from config file."""

    @pytest.mark.asyncio
    async def test_initialize_from_config(self, registry, tmp_path):
        """Test initializing from config file."""
        config_file = tmp_path / "mcp-servers.json"
        config_file.write_text(json.dumps({
            "servers": [
                {
                    "id": "server1",
                    "name": "Server 1",
                    "transport": "http",
                    "url": "http://localhost:8000",
                },
            ]
        }))

        with patch("src.mcp.registry.registry.HttpTransport") as MockTransport:
            MockTransport.return_value = MagicMock()
            await registry.initialize(config_file)

        assert "server1" in registry._servers

    @pytest.mark.asyncio
    async def test_initialize_missing_config_uses_defaults(self, registry):
        """Test that missing config uses defaults."""
        # Use a path that doesn't exist
        with patch("src.mcp.registry.registry.HttpTransport") as MockHttp, \
             patch("src.mcp.registry.registry.StdioTransport") as MockStdio:
            MockHttp.return_value = MagicMock()
            MockStdio.return_value = MagicMock()
            await registry.initialize(Path("/nonexistent/config.json"))

        # Should have registered default servers
        assert len(registry._servers) > 0


class TestServerConnection:
    """Tests for server connection management."""

    @pytest.mark.asyncio
    async def test_connect_all(self, registry):
        """Test connecting to all servers."""
        mock_client1 = MagicMock()
        mock_client1.connect = AsyncMock()
        mock_client2 = MagicMock()
        mock_client2.connect = AsyncMock()

        registry._servers = {"s1": mock_client1, "s2": mock_client2}

        await registry.connect_all()

        mock_client1.connect.assert_called_once()
        mock_client2.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_all_handles_errors(self, registry):
        """Test that connect_all handles connection errors gracefully."""
        mock_client1 = MagicMock()
        mock_client1.connect = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client2 = MagicMock()
        mock_client2.connect = AsyncMock()

        registry._servers = {"s1": mock_client1, "s2": mock_client2}

        # Should not raise, continues to next server
        await registry.connect_all()

        mock_client2.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all(self, registry):
        """Test disconnecting from all servers."""
        mock_client1 = MagicMock()
        mock_client1.disconnect = AsyncMock()
        mock_client2 = MagicMock()
        mock_client2.disconnect = AsyncMock()

        registry._servers = {"s1": mock_client1, "s2": mock_client2}

        await registry.disconnect_all()

        mock_client1.disconnect.assert_called_once()
        mock_client2.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all_handles_errors(self, registry):
        """Test that disconnect_all handles errors gracefully."""
        mock_client1 = MagicMock()
        mock_client1.disconnect = AsyncMock(side_effect=Exception("Error"))
        mock_client2 = MagicMock()
        mock_client2.disconnect = AsyncMock()

        registry._servers = {"s1": mock_client1, "s2": mock_client2}

        # Should not raise
        await registry.disconnect_all()

        mock_client2.disconnect.assert_called_once()


class TestServerLookup:
    """Tests for server lookup methods."""

    def test_get_client_found(self, registry):
        """Test getting an existing client."""
        mock_client = MagicMock()
        registry._servers["test"] = mock_client

        result = registry.get_client("test")

        assert result is mock_client

    def test_get_client_not_found(self, registry):
        """Test getting a non-existent client."""
        result = registry.get_client("nonexistent")

        assert result is None

    def test_list_servers(self, registry):
        """Test listing all servers."""
        mock_client1 = MagicMock()
        mock_client1.is_connected = True
        mock_client1.get_tools.return_value = [{"name": "tool1"}, {"name": "tool2"}]

        mock_client2 = MagicMock()
        mock_client2.is_connected = False
        mock_client2.get_tools.return_value = []

        registry._servers = {"s1": mock_client1, "s2": mock_client2}
        registry._configs = {
            "s1": {"name": "Server 1", "transport": "http"},
            "s2": {"name": "Server 2", "transport": "stdio"},
        }

        result = registry.list_servers()

        assert len(result) == 2
        assert result[0]["id"] == "s1"
        assert result[0]["name"] == "Server 1"
        assert result[0]["connected"] is True
        assert result[0]["tools_count"] == 2
        assert result[1]["connected"] is False
        assert result[1]["tools_count"] == 0
