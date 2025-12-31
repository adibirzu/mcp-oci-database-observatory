"""MCP tool modules for OCI Database Observatory.

Each module registers tools with the main FastMCP server.
Tools follow MCP best practices:
- Stateless (no internal LLM)
- Fast response times via caching
- Multi-tenancy via profile parameter

Observability:
- All tools are automatically traced via OpenTelemetry
- Traces are exported to OCI APM
"""

import functools
import time
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Import tracing utilities
try:
    from src.observability import create_span, get_trace_id, record_tool_execution
    _tracing_available = True
except ImportError:
    _tracing_available = False


def traced_tool(tool_name: str, server_id: str = "oci-database-observatory"):
    """Decorator to add tracing to MCP tools.

    Creates a span for each tool execution and records metrics.

    Args:
        tool_name: Name of the tool being traced
        server_id: MCP server identifier
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if not _tracing_available:
                return await func(*args, **kwargs)

            start_time = time.time()
            success = False
            cached = False

            with create_span(f"mcp.tool.{tool_name}", component="mcp_executor") as span:
                span.set_attribute("mcp.tool.name", tool_name)
                span.set_attribute("mcp.server.id", server_id)
                span.set_attribute("mcp.tool.args", str(kwargs)[:200])

                try:
                    result = await func(*args, **kwargs)

                    # Check if result indicates success
                    if isinstance(result, dict):
                        success = result.get("success", True)
                        cached = result.get("cached", False)
                        span.set_attribute("mcp.tool.success", success)
                        if "error" in result:
                            span.set_attribute("mcp.tool.error", str(result["error"])[:200])
                    else:
                        success = True

                    return result

                except Exception as e:
                    span.set_attribute("mcp.tool.success", False)
                    span.set_attribute("mcp.tool.error", str(e)[:200])
                    raise

                finally:
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("mcp.tool.duration_ms", duration_ms)
                    record_tool_execution(tool_name, server_id, duration_ms, success, cached)

        return wrapper
    return decorator


def register_all_tools(mcp: "FastMCP") -> None:
    """Register all tool modules with the MCP server.

    Args:
        mcp: FastMCP server instance
    """
    from . import sqlcl, opsi, logan, tenancy

    # Each module has a register_tools(mcp) function
    sqlcl.register_tools(mcp)
    opsi.register_tools(mcp)
    logan.register_tools(mcp)
    tenancy.register_tools(mcp)

    # Wrap all registered tools with tracing
    if _tracing_available:
        _wrap_tools_with_tracing(mcp)


def _wrap_tools_with_tracing(mcp: "FastMCP") -> None:
    """Wrap all registered tools with tracing instrumentation.

    This post-processes the registered tools to add observability
    without modifying each tool module individually.
    """
    # Access the internal tool registry
    if hasattr(mcp, '_tool_manager') and hasattr(mcp._tool_manager, '_tools'):
        tools = mcp._tool_manager._tools
        for tool_name, tool_info in tools.items():
            if hasattr(tool_info, 'fn') and callable(tool_info.fn):
                original_fn = tool_info.fn
                # Wrap with tracing
                tool_info.fn = traced_tool(tool_name)(original_fn)
