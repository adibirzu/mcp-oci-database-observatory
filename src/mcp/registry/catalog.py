"""Tool catalog for aggregating tools from multiple MCP servers."""

from dataclasses import dataclass, field
from typing import Any

from src.core import get_logger

from .registry import ServerRegistry

logger = get_logger("mcp.catalog")


@dataclass
class ToolDefinition:
    """Definition of an MCP tool."""

    name: str  # Namespaced: server__tool
    server_id: str
    original_name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    ttl_seconds: int = 120  # Default cache TTL


class ToolCatalog:
    """Catalog of all available tools across MCP servers."""

    def __init__(self, registry: ServerRegistry) -> None:
        """Initialize catalog with server registry.

        Args:
            registry: MCP server registry
        """
        self.registry = registry
        self._tools: dict[str, ToolDefinition] = {}

    async def refresh(self) -> None:
        """Refresh tool catalog from all servers."""
        self._tools.clear()

        for server_info in self.registry.list_servers():
            server_id = server_info["id"]
            client = self.registry.get_client(server_id)

            if not client or not client.is_connected:
                continue

            try:
                tools = client.get_tools()
                for tool in tools:
                    self._register_tool(server_id, tool)
            except Exception as e:
                logger.error(
                    "Failed to get tools from server",
                    server_id=server_id,
                    error=str(e),
                )

        logger.info("Tool catalog refreshed", total_tools=len(self._tools))

    def _register_tool(
        self,
        server_id: str,
        tool: dict[str, Any],
    ) -> None:
        """Register a tool from a server.

        Args:
            server_id: Source server ID
            tool: Tool definition from server
        """
        original_name = tool.get("name", "")
        namespaced_name = f"{server_id}__{original_name}"

        definition = ToolDefinition(
            name=namespaced_name,
            server_id=server_id,
            original_name=original_name,
            description=tool.get("description", ""),
            parameters=tool.get("inputSchema", {}),
            ttl_seconds=self._get_ttl(original_name),
        )

        self._tools[namespaced_name] = definition

    def _get_ttl(self, tool_name: str) -> int:
        """Get cache TTL for a tool based on its name."""
        # Static tools - 1 hour
        static_tools = ["list_oci_profiles", "list_parsers", "schema-information"]
        if any(s in tool_name.lower() for s in static_tools):
            return 3600

        # Stable tools - 30 minutes
        stable_tools = ["list_compartments", "list_log_sources", "get_fleet_summary"]
        if any(s in tool_name.lower() for s in stable_tools):
            return 1800

        # Infrastructure - 10 minutes
        infra_tools = ["list_autonomous", "list-connections", "list_databases"]
        if any(s in tool_name.lower() for s in infra_tools):
            return 600

        # Real-time - no cache
        realtime_tools = ["run-sql", "connect", "disconnect", "ping"]
        if any(s in tool_name.lower() for s in realtime_tools):
            return 0

        # Default - 2 minutes
        return 120

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by namespaced name.

        Args:
            name: Namespaced tool name (server__tool)

        Returns:
            Tool definition or None
        """
        return self._tools.get(name)

    def get_ttl(self, name: str) -> int:
        """Get cache TTL for a tool.

        Args:
            name: Namespaced tool name

        Returns:
            TTL in seconds
        """
        tool = self._tools.get(name)
        return tool.ttl_seconds if tool else 0

    def list_tools(
        self,
        server_id: str | None = None,
    ) -> list[ToolDefinition]:
        """List all tools, optionally filtered by server.

        Args:
            server_id: Optional server filter

        Returns:
            List of tool definitions
        """
        if server_id:
            return [t for t in self._tools.values() if t.server_id == server_id]
        return list(self._tools.values())

    def search_tools(self, query: str) -> list[ToolDefinition]:
        """Search tools by name or description.

        Args:
            query: Search query

        Returns:
            Matching tool definitions
        """
        query_lower = query.lower()
        return [
            t for t in self._tools.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]
