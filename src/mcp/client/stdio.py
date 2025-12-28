"""Stdio transport for MCP servers (subprocess-based)."""

import asyncio
import json
import os
from typing import Any

from src.core import get_logger

logger = get_logger("mcp.client.stdio")


class StdioTransport:
    """MCP transport over stdio (subprocess)."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize stdio transport.

        Args:
            command: Command to execute
            args: Command arguments
            env: Environment variables
        """
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected and self._process is not None

    async def connect(self) -> None:
        """Start the subprocess and establish connection."""
        if self._connected:
            return

        # Build environment
        process_env = os.environ.copy()
        process_env.update(self.env)

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )

            self._connected = True
            self._read_task = asyncio.create_task(self._read_loop())

            logger.info(
                "Stdio transport connected",
                command=self.command,
                pid=self._process.pid,
            )

            # Send initialize request
            await self._initialize()

        except Exception as e:
            logger.error("Failed to start subprocess", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Stop the subprocess."""
        self._connected = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception as e:
                logger.warning("Error terminating process", error=str(e))

        self._process = None
        logger.info("Stdio transport disconnected")

    async def _initialize(self) -> dict:
        """Send MCP initialize request."""
        response = await self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "clientInfo": {
                    "name": "oci-database-observatory",
                    "version": "0.1.0",
                },
            },
        )

        # Send initialized notification
        await self.send_notification("notifications/initialized", {})

        return response

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send JSON-RPC request and wait for response.

        Args:
            method: Method name
            params: Method parameters

        Returns:
            Response result
        """
        if not self._process or not self._process.stdin:
            raise RuntimeError("Not connected")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # Send request
        message = json.dumps(request) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

        logger.debug("Sent request", method=method, id=request_id)

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(future, timeout=60.0)
            return response
        except asyncio.TimeoutError:
            del self._pending[request_id]
            raise RuntimeError(f"Request timeout: {method}")

    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send JSON-RPC notification (no response expected).

        Args:
            method: Method name
            params: Method parameters
        """
        if not self._process or not self._process.stdin:
            raise RuntimeError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        message = json.dumps(notification) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read responses from subprocess stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            while self._connected:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    message = json.loads(line.decode())
                    await self._handle_message(message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON", data=line.decode()[:100])

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Read loop error", error=str(e))

    async def _handle_message(self, message: dict) -> None:
        """Handle incoming JSON-RPC message.

        Args:
            message: Parsed JSON-RPC message
        """
        # Check if it's a response
        if "id" in message and message["id"] in self._pending:
            future = self._pending.pop(message["id"])

            if "error" in message:
                future.set_exception(
                    RuntimeError(message["error"].get("message", "Unknown error"))
                )
            else:
                future.set_result(message.get("result", {}))

        # Check if it's a notification
        elif "method" in message and "id" not in message:
            logger.debug("Received notification", method=message["method"])

    async def list_tools(self) -> list[dict]:
        """List available tools.

        Returns:
            List of tool definitions
        """
        response = await self.send_request("tools/list", {})
        return response.get("tools", [])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call a tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        response = await self.send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

        # Extract content from response
        content = response.get("content", [])
        if content and isinstance(content, list):
            # Return first text content
            for item in content:
                if item.get("type") == "text":
                    return item.get("text")
            return content

        return response
