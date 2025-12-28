"""MCP server management routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import (
    get_agent_context,
    get_server_registry,
    get_tool_catalog,
    get_tool_executor,
)
from src.agents.base.context import AgentContext
from src.mcp.executor import ToolExecutor
from src.mcp.registry import ServerRegistry, ToolCatalog
from src.observability import create_span

router = APIRouter(prefix="/mcp", tags=["mcp"])


class ToolExecuteRequest(BaseModel):
    """Tool execution request."""

    name: str
    params: dict[str, Any] = {}


class ToolExecuteResponse(BaseModel):
    """Tool execution response."""

    success: bool
    data: Any = None
    error: str | None = None
    execution_time_ms: int = 0
    cached: bool = False


@router.get("/servers")
async def list_servers(
    registry: Annotated[ServerRegistry, Depends(get_server_registry)],
) -> dict[str, Any]:
    """List all MCP servers."""
    return {"servers": registry.list_servers()}


@router.get("/servers/{server_id}/tools")
async def list_server_tools(
    server_id: str,
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
) -> dict[str, Any]:
    """List tools for a specific server."""
    tools = catalog.list_tools(server_id=server_id)
    return {
        "server_id": server_id,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "ttl_seconds": t.ttl_seconds,
            }
            for t in tools
        ],
    }


@router.get("/tools")
async def list_all_tools(
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
) -> dict[str, Any]:
    """List all available tools."""
    tools = catalog.list_tools()
    return {
        "total": len(tools),
        "tools": [
            {
                "name": t.name,
                "server_id": t.server_id,
                "description": t.description,
                "ttl_seconds": t.ttl_seconds,
            }
            for t in tools
        ],
    }


@router.get("/tools/search")
async def search_tools(
    q: str,
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
) -> dict[str, Any]:
    """Search tools by name or description."""
    tools = catalog.search_tools(q)
    return {
        "query": q,
        "results": [
            {
                "name": t.name,
                "server_id": t.server_id,
                "description": t.description,
            }
            for t in tools
        ],
    }


@router.post("/tools/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    context: Annotated[AgentContext, Depends(get_agent_context)],
) -> ToolExecuteResponse:
    """Execute an MCP tool."""
    with create_span(
        "api.mcp.execute_tool",
        component="api",
        attributes={"tool": request.name},
    ):
        try:
            result = await executor.execute_direct(
                request.name,
                request.params,
                context,
            )

            return ToolExecuteResponse(
                success=result.success,
                data=result.data,
                error=result.error,
                execution_time_ms=result.execution_time_ms,
                cached=result.cached,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/refresh")
async def refresh_catalog(
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
) -> dict[str, Any]:
    """Refresh the tool catalog from all servers."""
    await catalog.refresh()
    tools = catalog.list_tools()
    return {
        "success": True,
        "total_tools": len(tools),
    }


@router.post("/servers/connect-all")
async def connect_all_servers(
    registry: Annotated[ServerRegistry, Depends(get_server_registry)],
) -> dict[str, Any]:
    """Connect to all registered servers."""
    await registry.connect_all()
    servers = registry.list_servers()
    connected = [s for s in servers if s.get("connected")]
    return {
        "success": True,
        "total": len(servers),
        "connected": len(connected),
        "servers": servers,
    }
