"""MCP Server wrapper for OCI Database Observatory.

Exposes the LangGraph Coordinator as MCP tools for integration with
Claude Code, Cline, and other MCP clients.

Run with: python -m src.mcp_server
"""

import asyncio
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP(name="oci-database-observatory")

# Shared SQLcl client for connection reuse
_sqlcl_client = None
_sqlcl_lock = asyncio.Lock()


async def get_sqlcl_client(timeout: float = 120.0):
    """Get or create a shared SQLcl client.

    Reuses the connection to avoid Java startup overhead on each call.

    Args:
        timeout: Timeout for connect operation

    Returns:
        Connected MCPClient for SQLcl
    """
    global _sqlcl_client

    async with _sqlcl_lock:
        if _sqlcl_client is not None and _sqlcl_client.is_connected:
            return _sqlcl_client

        from src.mcp.client.stdio import StdioTransport
        from src.mcp.client.client import MCPClient

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")

        # Java options for better startup
        env = {
            "_JAVA_OPTIONS": "--enable-native-access=ALL-UNNAMED",
            "SQLCL_MCP_MODE": "true",
        }

        java_home = os.getenv("JAVA_HOME")
        if java_home:
            env["JAVA_HOME"] = java_home

        transport = StdioTransport(
            command=sqlcl_path,
            args=["-mcp"],
            env=env,
        )
        client = MCPClient("sqlcl", transport)

        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            _sqlcl_client = client
            return client
        except asyncio.TimeoutError:
            raise RuntimeError(f"SQLcl startup timeout ({timeout}s) - Java may be slow to initialize")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to SQLcl: {e}")


async def safe_call_tool(client, tool_name: str, args: dict, timeout: float = 90.0) -> Any:
    """Safely call a tool with timeout and error handling.

    Args:
        client: MCPClient instance
        tool_name: Name of the tool to call
        args: Tool arguments
        timeout: Timeout in seconds

    Returns:
        Tool result or error dict
    """
    try:
        result = await asyncio.wait_for(
            client.call_tool(tool_name, args),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        return {"error": f"Tool '{tool_name}' timeout after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


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

        # Create coordinator
        coordinator = LangGraphCoordinator(max_iterations=10)

        # Check if LLM is available
        if coordinator.llm is None:
            return {
                "success": False,
                "error": "No LLM configured",
                "hint": "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or configure Oracle GenAI",
                "suggestion": "Use execute_sql tool for direct SQL queries instead",
            }

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
        client = await get_sqlcl_client()

        # Connect to specified database if not default
        if connection != "default":
            connect_result = await safe_call_tool(
                client, "connect", {"connection_name": connection}, timeout=60.0
            )
            if isinstance(connect_result, dict) and "error" in connect_result:
                return {
                    "success": False,
                    "error": f"Connection failed: {connect_result['error']}",
                    "connection": connection,
                }

        # Execute SQL
        result = await safe_call_tool(client, "run-sql", {"sql": sql}, timeout=120.0)

        if isinstance(result, dict) and "error" in result:
            return {
                "success": False,
                "error": result["error"],
                "connection": connection,
            }

        return {
            "success": True,
            "result": result,
            "connection": connection,
        }

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
        client = await get_sqlcl_client()

        if connection != "default":
            connect_result = await safe_call_tool(
                client, "connect", {"connection_name": connection}, timeout=60.0
            )
            if isinstance(connect_result, dict) and "error" in connect_result:
                return {
                    "success": False,
                    "error": f"Connection failed: {connect_result['error']}",
                }

        result = await safe_call_tool(
            client, "schema-information", {"schema": schema}, timeout=90.0
        )

        if isinstance(result, dict) and "error" in result:
            return {
                "success": False,
                "error": result["error"],
                "schema": schema,
            }

        return {
            "success": True,
            "schema": schema,
            "result": result,
        }

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
        client = await get_sqlcl_client()
        result = await safe_call_tool(client, "list-connections", {}, timeout=30.0)

        if isinstance(result, dict) and "error" in result:
            return {
                "success": False,
                "error": result["error"],
            }

        return {
            "success": True,
            "connections": result,
        }

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
        if coordinator.llm:
            status["coordinator"] = "healthy (LLM configured)"
        else:
            status["coordinator"] = "partial (no LLM)"
    except Exception as e:
        status["coordinator"] = f"error: {str(e)[:50]}"

    # Check SQLcl
    try:
        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")
        if os.path.exists(sqlcl_path):
            if _sqlcl_client and _sqlcl_client.is_connected:
                status["sqlcl"] = "connected"
            else:
                status["sqlcl"] = "available (not connected)"
        else:
            status["sqlcl"] = "not_found"
    except Exception as e:
        status["sqlcl"] = f"error: {str(e)[:50]}"

    return {
        "success": True,
        "status": status,
    }


@mcp.tool()
async def database_status(
    connection: str = "default",
) -> dict[str, Any]:
    """Get the status of a database connection.

    Checks if the database is connected and returns connection details
    including instance status, version, and session info.

    Args:
        connection: Database connection name (default: use configured default)

    Returns:
        Connection status and database information
    """
    try:
        client = await get_sqlcl_client()

        # Get list of connections first
        connections = await safe_call_tool(client, "list-connections", {}, timeout=30.0)

        # Try to connect to specified database
        connect_result = None
        if connection != "default":
            connect_result = await safe_call_tool(
                client, "connect", {"connection_name": connection}, timeout=60.0
            )

        # Get basic status query
        status_result = await safe_call_tool(
            client,
            "run-sql",
            {"sql": "SELECT INSTANCE_NAME, STATUS, DATABASE_STATUS FROM V$INSTANCE"},
            timeout=60.0,
        )

        return {
            "success": True,
            "connection": connection,
            "available_connections": connections,
            "connect_result": connect_result,
            "instance_status": status_result,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "connection": connection,
        }


@mcp.tool()
async def disconnect_sqlcl() -> dict[str, Any]:
    """Disconnect the shared SQLcl client.

    Use this to force a reconnection on the next call.

    Returns:
        Disconnection status
    """
    global _sqlcl_client

    async with _sqlcl_lock:
        if _sqlcl_client:
            try:
                await _sqlcl_client.disconnect()
                _sqlcl_client = None
                return {"success": True, "message": "SQLcl client disconnected"}
            except Exception as e:
                _sqlcl_client = None
                return {"success": True, "message": f"Disconnected with warning: {e}"}
        else:
            return {"success": True, "message": "No active SQLcl client"}


if __name__ == "__main__":
    mcp.run()
