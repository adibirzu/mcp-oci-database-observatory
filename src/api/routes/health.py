"""Health check routes."""

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.api.dependencies import get_server_registry, get_tool_cache
from src.cache.tool_cache import ToolResultCache
from src.core import settings
from src.mcp.registry import ServerRegistry

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, Any]:
    """Basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "oci-database-observatory",
        "version": "0.1.0",
    }


@router.get("/ready")
async def readiness_check(
    registry: Annotated[ServerRegistry, Depends(get_server_registry)],
    cache: Annotated[ToolResultCache, Depends(get_tool_cache)],
) -> dict[str, Any]:
    """Readiness check with dependencies."""
    servers = registry.list_servers()
    connected_servers = [s for s in servers if s.get("connected")]

    cache_status = await cache.health_check()

    return {
        "status": "ready" if connected_servers else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "mcp_servers": {
                "total": len(servers),
                "connected": len(connected_servers),
                "servers": servers,
            },
            "cache": cache_status,
        },
    }


@router.get("/live")
async def liveness_check() -> dict[str, str]:
    """Liveness check."""
    return {"status": "alive"}


@router.get("/config")
async def config_info() -> dict[str, Any]:
    """Get non-sensitive configuration info."""
    return {
        "environment": settings.environment,
        "log_level": settings.log_level,
        "otel_enabled": settings.otel_tracing_enabled,
        "otel_service_name": settings.otel_service_name,
        "llm_provider": settings.llm_provider,
        "mcp_servers": {
            "opsi": settings.opsi_http_url,
            "logan": settings.logan_http_url,
            "oci_mcp": settings.oci_mcp_http_url,
            "mysql": settings.mysql_mcp_url,
            "postgres": settings.postgres_mcp_url,
        },
    }
