"""MCP Server wrapper for OCI Database Observatory.

Exposes the LangGraph Coordinator as MCP tools for integration with
Claude Code, Cline, and other MCP clients.

Run with: python -m src.mcp_server
"""

import asyncio
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP(name="oci-database-observatory")


@mcp.tool()
async def query_database(
    query: str,
    database: str = "default",
) -> dict[str, Any]:
    """Execute a natural language query against Oracle databases.

    This tool uses the LangGraph Coordinator to interpret natural language
    queries and execute appropriate SQL or analysis operations.

    Args:
        query: Natural language query (e.g., "What tables are in the HR schema?")
        database: Target database connection name (default: use configured default)

    Returns:
        Query results with response text and metadata
    """
    try:
        from src.agents.coordinator.graph import LangGraphCoordinator
        from src.mcp.registry.catalog import ToolCatalog

        # Create coordinator with tool catalog
        coordinator = LangGraphCoordinator(max_iterations=10)

        # Execute query
        result = await coordinator.invoke(query)

        return {
            "success": result.get("success", False),
            "response": result.get("response", "No response"),
            "iterations": result.get("iterations", 0),
            "database": database,
        }
    except ImportError as e:
        return {
            "success": False,
            "error": f"Missing dependencies: {e}",
            "hint": "Ensure LangChain and coordinator dependencies are installed",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@mcp.tool()
async def list_mcp_tools() -> dict[str, Any]:
    """List all available MCP tools from connected servers.

    Returns aggregated tool information from all configured MCP servers
    including SQLcl, OCI OPSI, Logan, and unified OCI MCP.

    Returns:
        Dictionary with tool names, descriptions, and server info
    """
    try:
        from src.mcp.registry.catalog import ToolCatalog
        from src.mcp.registry.registry import ServerRegistry

        registry = ServerRegistry()
        catalog = ToolCatalog(registry)

        tools = catalog.list_tools()

        return {
            "success": True,
            "tool_count": len(tools),
            "tools": [
                {
                    "name": t.name,
                    "server": t.server_id,
                    "description": t.description[:100] if t.description else "",
                }
                for t in tools
            ],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@mcp.tool()
async def execute_sql(
    sql: str,
    connection: str = "default",
) -> dict[str, Any]:
    """Execute SQL directly on an Oracle database via SQLcl MCP.

    Args:
        sql: SQL statement to execute
        connection: Database connection name

    Returns:
        Query results or execution status
    """
    try:
        from src.mcp.client.stdio import StdioTransport
        from src.mcp.client.client import MCPClient

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")

        transport = StdioTransport(
            command=sqlcl_path,
            args=["-mcp"],
            env={},
        )
        client = MCPClient("sqlcl", transport)

        try:
            await client.connect()

            # Connect to specified database if not default
            if connection != "default":
                await client.call_tool("connect", {"connection": connection})

            # Execute SQL
            result = await client.call_tool("run-sql", {"sql": sql})

            return {
                "success": True,
                "result": result,
                "connection": connection,
            }
        finally:
            await client.disconnect()

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@mcp.tool()
async def get_schema_info(
    schema: str,
    connection: str = "default",
) -> dict[str, Any]:
    """Get schema information including tables, views, and objects.

    Args:
        schema: Schema name to inspect (e.g., "HR", "USERS")
        connection: Database connection name

    Returns:
        Schema metadata including tables, views, procedures
    """
    try:
        from src.mcp.client.stdio import StdioTransport
        from src.mcp.client.client import MCPClient

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")

        transport = StdioTransport(
            command=sqlcl_path,
            args=["-mcp"],
            env={},
        )
        client = MCPClient("sqlcl", transport)

        try:
            await client.connect()

            if connection != "default":
                await client.call_tool("connect", {"connection": connection})

            result = await client.call_tool("schema-information", {"schema": schema})

            return {
                "success": True,
                "schema": schema,
                "result": result,
            }
        finally:
            await client.disconnect()

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@mcp.tool()
async def list_connections() -> dict[str, Any]:
    """List available database connections configured in SQLcl.

    Returns:
        List of connection names and their status
    """
    try:
        from src.mcp.client.stdio import StdioTransport
        from src.mcp.client.client import MCPClient

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")

        transport = StdioTransport(
            command=sqlcl_path,
            args=["-mcp"],
            env={},
        )
        client = MCPClient("sqlcl", transport)

        try:
            await client.connect()
            result = await client.call_tool("list-connections", {})

            return {
                "success": True,
                "connections": result,
            }
        finally:
            await client.disconnect()

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@mcp.tool()
async def health_check() -> dict[str, Any]:
    """Check health of OCI Database Observatory and connected services.

    Returns:
        Health status of coordinator and MCP servers
    """
    status = {
        "coordinator": "unknown",
        "sqlcl": "unknown",
        "oci_opsi": "unknown",
        "oci_logan": "unknown",
    }

    # Check coordinator
    try:
        from src.agents.coordinator.graph import LangGraphCoordinator

        coordinator = LangGraphCoordinator()
        status["coordinator"] = "healthy"
    except Exception as e:
        status["coordinator"] = f"error: {str(e)[:50]}"

    # Check SQLcl
    try:
        from src.mcp.client.stdio import StdioTransport
        from src.mcp.client.client import MCPClient

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")
        if os.path.exists(sqlcl_path):
            status["sqlcl"] = "available"
        else:
            status["sqlcl"] = "not_found"
    except Exception as e:
        status["sqlcl"] = f"error: {str(e)[:50]}"

    return {
        "success": True,
        "status": status,
    }


if __name__ == "__main__":
    mcp.run()
