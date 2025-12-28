"""MCP server registry for managing multiple servers."""

import json
from pathlib import Path
from typing import Any

from src.core import get_logger, settings
from src.mcp.client.client import MCPClient
from src.mcp.client.http import HttpTransport
from src.mcp.client.stdio import StdioTransport

logger = get_logger("mcp.registry")


class ServerRegistry:
    """Registry for managing MCP server connections."""

    def __init__(self) -> None:
        """Initialize empty server registry."""
        self._servers: dict[str, MCPClient] = {}
        self._configs: dict[str, dict] = {}

    async def initialize(
        self,
        config_path: str | Path | None = None,
    ) -> None:
        """Initialize servers from configuration.

        Args:
            config_path: Path to mcp-servers.json config file
        """
        if config_path is None:
            config_path = Path("config/mcp-servers.json")

        if isinstance(config_path, str):
            config_path = Path(config_path)

        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
                for server_config in config.get("servers", []):
                    await self.register_server(server_config)
        else:
            logger.warning(
                "MCP config not found, using defaults",
                path=str(config_path),
            )
            await self._register_defaults()

    async def _register_defaults(self) -> None:
        """Register default server configurations."""
        defaults = [
            {
                "id": "oci-opsi",
                "name": "OCI Operations Insights",
                "transport": "http",
                "url": settings.opsi_http_url,
            },
            {
                "id": "oci-logan",
                "name": "OCI Logging Analytics",
                "transport": "http",
                "url": settings.logan_http_url,
            },
            {
                "id": "oci-mcp",
                "name": "OCI Unified MCP",
                "transport": "http",
                "url": settings.oci_mcp_http_url,
            },
            {
                "id": "sqlcl",
                "name": "Oracle SQLcl",
                "transport": "stdio",
                "command": settings.sqlcl_path,
                "args": ["-mcp"],
            },
        ]

        for config in defaults:
            await self.register_server(config)

    async def register_server(self, config: dict[str, Any]) -> None:
        """Register an MCP server.

        Args:
            config: Server configuration dictionary
        """
        server_id = config["id"]
        transport_type = config.get("transport", "http")

        # Create appropriate transport
        if transport_type == "http":
            transport = HttpTransport(
                url=config["url"],
                headers=config.get("headers", {}),
            )
        elif transport_type == "stdio":
            transport = StdioTransport(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env", {}),
            )
        else:
            raise ValueError(f"Unknown transport type: {transport_type}")

        # Create client
        client = MCPClient(server_id, transport)

        self._servers[server_id] = client
        self._configs[server_id] = config

        logger.info(
            "Server registered",
            server_id=server_id,
            transport=transport_type,
        )

    async def connect_all(self) -> None:
        """Connect to all registered servers."""
        for server_id, client in self._servers.items():
            try:
                await client.connect()
            except Exception as e:
                logger.error(
                    "Failed to connect to server",
                    server_id=server_id,
                    error=str(e),
                )

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for server_id, client in self._servers.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning(
                    "Error disconnecting",
                    server_id=server_id,
                    error=str(e),
                )

    def get_client(self, server_id: str) -> MCPClient | None:
        """Get an MCP client by server ID.

        Args:
            server_id: Server identifier

        Returns:
            MCP client or None
        """
        return self._servers.get(server_id)

    def list_servers(self) -> list[dict]:
        """List all registered servers.

        Returns:
            List of server info dictionaries
        """
        servers = []
        for server_id, client in self._servers.items():
            config = self._configs.get(server_id, {})
            servers.append({
                "id": server_id,
                "name": config.get("name", server_id),
                "transport": config.get("transport", "unknown"),
                "connected": client.is_connected,
                "tools_count": len(client.get_tools()),
            })
        return servers
