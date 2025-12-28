"""Tests for MCP Stdio transport.

Tests verify JSON-RPC communication over subprocess stdio using mocks.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.client.stdio import StdioTransport


@pytest.fixture
def transport():
    """Create a StdioTransport instance for testing."""
    return StdioTransport(
        command="/usr/bin/test-server",
        args=["--mcp"],
        env={"TEST_VAR": "value"},
    )


class TestStdioTransportInit:
    """Tests for StdioTransport initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        transport = StdioTransport(command="/usr/bin/server")

        assert transport.command == "/usr/bin/server"
        assert transport.args == []
        assert transport.env == {}
        assert not transport.is_connected

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        transport = StdioTransport(
            command="/usr/bin/server",
            args=["--flag", "value"],
            env={"KEY": "VALUE"},
        )

        assert transport.command == "/usr/bin/server"
        assert transport.args == ["--flag", "value"]
        assert transport.env == {"KEY": "VALUE"}

    def test_is_connected_initially_false(self, transport):
        """Test that transport is not connected initially."""
        assert transport.is_connected is False


class TestStdioTransportConnect:
    """Tests for StdioTransport connection handling."""

    @pytest.mark.asyncio
    async def test_connect_handles_subprocess_failure(self, transport):
        """Test that connect handles subprocess startup failure."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("Command not found"),
        ):
            with pytest.raises(OSError, match="Command not found"):
                await transport.connect()

        assert transport.is_connected is False


class TestStdioTransportDisconnect:
    """Tests for StdioTransport disconnection."""

    @pytest.mark.asyncio
    async def test_disconnect_terminates_process(self, transport):
        """Test that disconnect terminates the subprocess."""
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        transport._connected = True
        transport._process = mock_process
        transport._read_task = None

        await transport.disconnect()

        assert transport.is_connected is False
        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_kills_on_timeout(self, transport):
        """Test that disconnect kills process if terminate times out."""
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())

        transport._connected = True
        transport._process = mock_process
        transport._read_task = None

        await transport.disconnect()

        mock_process.kill.assert_called_once()


class TestStdioTransportJsonRpc:
    """Tests for JSON-RPC message handling."""

    @pytest.mark.asyncio
    async def test_send_request_raises_when_not_connected(self, transport):
        """Test that send_request raises when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await transport.send_request("test/method")

    @pytest.mark.asyncio
    async def test_send_request_formats_message_correctly(self, transport):
        """Test that send_request formats JSON-RPC message correctly."""
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        transport._connected = True
        transport._process = mock_process
        transport._request_id = 0

        # Create a task that will complete when we call send_request
        # We won't await it fully, just start it to send the message
        async def send_and_cancel():
            try:
                await asyncio.wait_for(
                    transport.send_request("test/method", {"param": "value"}),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                pass  # Expected

        await send_and_cancel()

        # Verify the request was written correctly
        mock_process.stdin.write.assert_called()
        written_data = mock_process.stdin.write.call_args[0][0].decode()
        request = json.loads(written_data.strip())

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "test/method"
        assert request["params"] == {"param": "value"}
        assert request["id"] == 1  # First request ID

    @pytest.mark.asyncio
    async def test_send_notification_no_id(self, transport):
        """Test that notifications don't have an id field."""
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        transport._connected = True
        transport._process = mock_process

        await transport.send_notification("test/notify", {"data": "value"})

        written_data = mock_process.stdin.write.call_args[0][0].decode()
        notification = json.loads(written_data.strip())

        assert "id" not in notification
        assert notification["method"] == "test/notify"
        assert notification["params"] == {"data": "value"}


class TestStdioTransportHandleMessage:
    """Tests for message handling."""

    @pytest.mark.asyncio
    async def test_handle_response_resolves_pending_future(self, transport):
        """Test that responses resolve pending futures."""
        transport._connected = True

        # Create a pending future
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        transport._pending[1] = future

        # Handle response message
        await transport._handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"test": "data"},
        })

        assert future.done()
        assert future.result() == {"test": "data"}
        assert 1 not in transport._pending

    @pytest.mark.asyncio
    async def test_handle_error_response_sets_exception(self, transport):
        """Test that error responses set exception on futures."""
        transport._connected = True

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        transport._pending[1] = future

        await transport._handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -1, "message": "Test error"},
        })

        assert future.done()
        with pytest.raises(RuntimeError, match="Test error"):
            future.result()

    @pytest.mark.asyncio
    async def test_handle_notification(self, transport):
        """Test that notifications are handled without error."""
        transport._connected = True

        # Should not raise
        await transport._handle_message({
            "jsonrpc": "2.0",
            "method": "some/notification",
            "params": {"data": "value"},
        })


class TestStdioTransportTools:
    """Tests for MCP tool operations."""

    @pytest.mark.asyncio
    async def test_list_tools_sends_correct_request(self, transport):
        """Test that list_tools sends tools/list request."""
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        transport._connected = True
        transport._process = mock_process
        transport._request_id = 0

        async def list_and_cancel():
            try:
                await asyncio.wait_for(transport.list_tools(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

        await list_and_cancel()

        written_data = mock_process.stdin.write.call_args[0][0].decode()
        request = json.loads(written_data.strip())

        assert request["method"] == "tools/list"

    @pytest.mark.asyncio
    async def test_call_tool_sends_correct_request(self, transport):
        """Test that call_tool sends tools/call request with correct params."""
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        transport._connected = True
        transport._process = mock_process
        transport._request_id = 0

        async def call_and_cancel():
            try:
                await asyncio.wait_for(
                    transport.call_tool("run-sql", {"sql": "SELECT 1"}),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                pass

        await call_and_cancel()

        written_data = mock_process.stdin.write.call_args[0][0].decode()
        request = json.loads(written_data.strip())

        assert request["method"] == "tools/call"
        assert request["params"]["name"] == "run-sql"
        assert request["params"]["arguments"]["sql"] == "SELECT 1"


class TestStdioTransportReadLoop:
    """Tests for the read loop."""

    @pytest.mark.asyncio
    async def test_read_loop_processes_responses(self, transport):
        """Test that read loop processes incoming responses."""
        mock_process = MagicMock()
        mock_process.stdout = MagicMock()

        transport._connected = True
        transport._process = mock_process

        # Create pending future
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        transport._pending[1] = future

        # Mock readline to return response then empty
        response = {"jsonrpc": "2.0", "id": 1, "result": {"data": "test"}}
        mock_process.stdout.readline = AsyncMock(
            side_effect=[
                json.dumps(response).encode() + b"\n",
                b"",  # End of stream
            ]
        )

        # Run read loop (it will exit when readline returns empty)
        await transport._read_loop()

        assert future.done()
        assert future.result() == {"data": "test"}


class TestStdioTransportInitialize:
    """Tests for MCP initialize handshake."""

    @pytest.mark.asyncio
    async def test_initialize_sends_correct_protocol(self, transport):
        """Test that initialize sends correct MCP protocol version."""
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        transport._connected = True
        transport._process = mock_process
        transport._request_id = 0

        async def init_and_cancel():
            try:
                await asyncio.wait_for(transport._initialize(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

        await init_and_cancel()

        # Verify initialize request was sent (first call)
        calls = mock_process.stdin.write.call_args_list
        init_call = json.loads(calls[0][0][0].decode().strip())

        assert init_call["method"] == "initialize"
        assert init_call["params"]["protocolVersion"] == "2024-11-05"
        assert init_call["params"]["clientInfo"]["name"] == "oci-database-observatory"
