"""Convert MCP tools to LangChain tool format.

This module provides utilities for converting MCP tool definitions
to formats compatible with LangChain's bind_tools method.
"""

from typing import Any, Callable

from langchain_core.tools import StructuredTool

from src.core import get_logger
from src.mcp.registry.catalog import ToolCatalog, ToolDefinition

logger = get_logger("mcp.tools.converter")


class ToolConverter:
    """Converts MCP tools to LangChain format."""

    def __init__(
        self,
        tool_catalog: ToolCatalog,
        executor: Callable[[str, dict], Any] | None = None,
    ) -> None:
        """Initialize the converter.

        Args:
            tool_catalog: MCP tool catalog
            executor: Optional tool execution function
        """
        self.tool_catalog = tool_catalog
        self.executor = executor

    def to_langchain_tools(
        self,
        server_filter: str | None = None,
    ) -> list[StructuredTool]:
        """Convert MCP tools to LangChain StructuredTools.

        Args:
            server_filter: Optional server ID to filter tools

        Returns:
            List of LangChain StructuredTools
        """
        tools = self.tool_catalog.list_tools(server_id=server_filter)
        return [self._convert_tool(tool) for tool in tools]

    def _convert_tool(self, tool_def: ToolDefinition) -> StructuredTool:
        """Convert a single MCP tool to LangChain format.

        Args:
            tool_def: MCP tool definition

        Returns:
            LangChain StructuredTool
        """
        # Create the tool function
        def tool_func(**kwargs) -> str:
            """Execute the MCP tool."""
            if self.executor:
                return self.executor(tool_def.name, kwargs)
            return f"Tool {tool_def.name} called with: {kwargs}"

        # Build the tool
        return StructuredTool.from_function(
            func=tool_func,
            name=tool_def.name,
            description=tool_def.description or f"Execute {tool_def.original_name}",
            args_schema=self._build_schema(tool_def),
            return_direct=False,
        )

    def _build_schema(self, tool_def: ToolDefinition) -> dict | None:
        """Build Pydantic schema from tool parameters.

        Args:
            tool_def: Tool definition

        Returns:
            Schema dict or None
        """
        # MCP inputSchema is already JSON Schema format
        # LangChain's StructuredTool can use it directly
        if not tool_def.parameters:
            return None

        return tool_def.parameters

    def to_tool_definitions(
        self,
        server_filter: str | None = None,
    ) -> list[dict]:
        """Convert MCP tools to simple dict format for bind_tools.

        This format is compatible with most LLM providers.

        Args:
            server_filter: Optional server ID to filter tools

        Returns:
            List of tool definition dicts
        """
        tools = self.tool_catalog.list_tools(server_id=server_filter)
        return [self._to_definition(tool) for tool in tools]

    def _to_definition(self, tool_def: ToolDefinition) -> dict:
        """Convert tool to dict format.

        Args:
            tool_def: Tool definition

        Returns:
            Dict compatible with LLM bind_tools
        """
        return {
            "name": tool_def.name,
            "description": tool_def.description or f"Execute {tool_def.original_name}",
            "parameters": tool_def.parameters or {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }


def convert_to_langchain_tools(
    tool_catalog: ToolCatalog,
    executor: Callable[[str, dict], Any] | None = None,
    server_filter: str | None = None,
) -> list[StructuredTool]:
    """Convenience function to convert MCP tools to LangChain format.

    Args:
        tool_catalog: MCP tool catalog
        executor: Optional tool execution function
        server_filter: Optional server ID filter

    Returns:
        List of LangChain StructuredTools
    """
    converter = ToolConverter(tool_catalog, executor)
    return converter.to_langchain_tools(server_filter)
