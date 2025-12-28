"""Direct MCP tool execution with caching."""

import time
from typing import TYPE_CHECKING, Any

from src.core import MCPError, get_logger
from src.core.types import ToolResult
from src.observability import create_span, record_tool_execution

if TYPE_CHECKING:
    from src.agents.base.context import AgentContext
    from src.cache.tool_cache import ToolResultCache
    from src.mcp.registry.catalog import ToolCatalog
    from src.mcp.registry.registry import ServerRegistry

logger = get_logger("mcp.executor")


class ToolExecutor:
    """Executes MCP tools directly with caching."""

    def __init__(
        self,
        registry: "ServerRegistry",
        catalog: "ToolCatalog",
        cache: "ToolResultCache | None" = None,
    ) -> None:
        """Initialize executor with dependencies.

        Args:
            registry: MCP server registry
            catalog: Tool catalog
            cache: Optional tool result cache
        """
        self.registry = registry
        self.catalog = catalog
        self.cache = cache

    async def execute_direct(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: "AgentContext",
    ) -> ToolResult:
        """Execute a tool directly.

        Args:
            tool_name: Namespaced tool name (server__tool)
            params: Tool parameters
            context: Agent context

        Returns:
            Tool execution result
        """
        start_time = int(time.time() * 1000)

        with create_span(
            "mcp.tool.execute",
            component="mcp_executor",
            attributes={
                "tool.name": tool_name,
                "session.id": context.session_id,
            },
        ):
            # Get tool definition
            tool = self.catalog.get_tool(tool_name)
            if not tool:
                raise MCPError(f"Tool not found: {tool_name}")

            # Check cache first
            if self.cache and tool.ttl_seconds > 0:
                cache_key = self._build_cache_key(tool_name, params)
                cached = await self.cache.get(cache_key)
                if cached:
                    duration_ms = int(time.time() * 1000) - start_time
                    record_tool_execution(
                        tool_name=tool_name,
                        server_id=tool.server_id,
                        duration_ms=duration_ms,
                        success=True,
                        cached=True,
                    )
                    logger.debug(
                        "Cache hit",
                        tool=tool_name,
                        duration_ms=duration_ms,
                    )
                    return ToolResult(
                        success=True,
                        data=cached,
                        execution_time_ms=duration_ms,
                        cached=True,
                    )

            # Get client for server
            client = self.registry.get_client(tool.server_id)
            if not client:
                raise MCPError(
                    f"Server not found: {tool.server_id}",
                    server_id=tool.server_id,
                )

            # Execute tool
            try:
                result = await client.call_tool(tool.original_name, params)

                # Cache result if applicable
                if self.cache and tool.ttl_seconds > 0:
                    cache_key = self._build_cache_key(tool_name, params)
                    await self.cache.set(cache_key, result, tool.ttl_seconds)

                duration_ms = int(time.time() * 1000) - start_time
                record_tool_execution(
                    tool_name=tool_name,
                    server_id=tool.server_id,
                    duration_ms=duration_ms,
                    success=True,
                    cached=False,
                )

                logger.debug(
                    "Tool executed",
                    tool=tool_name,
                    duration_ms=duration_ms,
                )

                return ToolResult(
                    success=True,
                    data=result,
                    execution_time_ms=duration_ms,
                    cached=False,
                )

            except Exception as e:
                duration_ms = int(time.time() * 1000) - start_time
                record_tool_execution(
                    tool_name=tool_name,
                    server_id=tool.server_id,
                    duration_ms=duration_ms,
                    success=False,
                    cached=False,
                )

                logger.error(
                    "Tool execution failed",
                    tool=tool_name,
                    error=str(e),
                )

                return ToolResult(
                    success=False,
                    error=str(e),
                    execution_time_ms=duration_ms,
                    cached=False,
                )

    def _build_cache_key(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> str:
        """Build cache key from tool name and params."""
        import hashlib
        import json

        param_str = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
        return f"tool:{tool_name}:{param_hash}"
