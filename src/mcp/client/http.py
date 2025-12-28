"""HTTP/SSE transport for MCP servers."""

from typing import Any

import httpx

from src.core import get_logger

from .client import Transport

logger = get_logger("mcp.client.http")


class HttpTransport(Transport):
    """HTTP transport for remote MCP servers."""

    def __init__(
        self,
        url: str,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize HTTP transport.

        Args:
            url: MCP server URL (e.g., http://localhost:8000/mcp)
            timeout: Request timeout in seconds
            headers: Additional HTTP headers
        """
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    async def connect(self) -> None:
        """Create HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers=self.headers,
        )
        self._connected = True
        logger.debug("HTTP transport connected", url=self.url)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.debug("HTTP transport disconnected", url=self.url)

    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> Any:
        """Call a tool via HTTP POST.

        Args:
            tool_name: Tool name
            params: Tool parameters

        Returns:
            Tool result from server
        """
        if not self._client:
            await self.connect()

        # MCP HTTP format
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params,
            },
            "id": 1,
        }

        response = await self._client.post(  # type: ignore
            self.url,
            json=payload,
        )
        response.raise_for_status()

        result = response.json()

        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error']}")

        return result.get("result", {}).get("content", result.get("result"))

    async def list_tools(self) -> list[dict]:
        """List available tools via HTTP.

        Returns:
            List of tool definitions
        """
        if not self._client:
            await self.connect()

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 1,
        }

        response = await self._client.post(  # type: ignore
            self.url,
            json=payload,
        )
        response.raise_for_status()

        result = response.json()
        return result.get("result", {}).get("tools", [])

    @property
    def is_connected(self) -> bool:
        """Check if HTTP client is active."""
        return self._connected and self._client is not None
