"""Generic MCP client with transport abstraction."""

from abc import ABC, abstractmethod
from typing import Any

from src.core import get_logger
from src.observability import create_span

logger = get_logger("mcp.client")


class Transport(ABC):
    """Abstract base class for MCP transports."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to MCP server."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to MCP server."""
        ...

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> Any:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            params: Tool parameters

        Returns:
            Tool execution result
        """
        ...

    @abstractmethod
    async def list_tools(self) -> list[dict]:
        """List available tools.

        Returns:
            List of tool definitions
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        ...


class MCPClient:
    """Generic MCP client supporting multiple transports."""

    def __init__(
        self,
        server_id: str,
        transport: Transport,
    ) -> None:
        """Initialize MCP client.

        Args:
            server_id: Unique server identifier
            transport: Transport implementation
        """
        self.server_id = server_id
        self.transport = transport
        self._tools: list[dict] = []

    async def connect(self) -> None:
        """Connect to the MCP server."""
        with create_span(
            "mcp.connect",
            component="mcp_executor",
            attributes={"server_id": self.server_id},
        ):
            await self.transport.connect()
            self._tools = await self.transport.list_tools()
            logger.info(
                "MCP client connected",
                server_id=self.server_id,
                tools=len(self._tools),
            )

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        await self.transport.disconnect()
        logger.info("MCP client disconnected", server_id=self.server_id)

    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> Any:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool
            params: Tool parameters

        Returns:
            Tool result
        """
        with create_span(
            "mcp.tool.call",
            component="mcp_executor",
            attributes={
                "server_id": self.server_id,
                "tool_name": tool_name,
            },
        ):
            if not self.transport.is_connected:
                await self.connect()

            result = await self.transport.call_tool(tool_name, params)
            logger.debug(
                "Tool called",
                server_id=self.server_id,
                tool=tool_name,
            )
            return result

    def get_tools(self) -> list[dict]:
        """Get cached tool definitions."""
        return self._tools

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self.transport.is_connected
