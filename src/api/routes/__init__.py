"""API routes module."""

from .agents import router as agents_router
from .compliance import router as compliance_router
from .health import router as health_router
from .llm import router as llm_router
from .mcp import router as mcp_router

__all__ = [
    "agents_router",
    "compliance_router",
    "health_router",
    "llm_router",
    "mcp_router",
]
