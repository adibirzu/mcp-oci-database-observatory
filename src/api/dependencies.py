"""FastAPI dependency injection."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.agents.base.context import AgentContext
from src.agents.coordinator import CoordinatorAgent
from src.agents.database import MySQLAgent, OracleAgent, PostgresAgent
from src.cache.tool_cache import ToolResultCache
from src.core import get_logger, settings
from src.llm import LLMRouter, ProviderRegistry
from src.mcp.executor import ParallelExecutor, ToolExecutor
from src.mcp.registry import ServerRegistry, ToolCatalog

logger = get_logger("api.dependencies")


@lru_cache
def get_server_registry() -> ServerRegistry:
    """Get cached server registry."""
    return ServerRegistry()


@lru_cache
def get_tool_catalog(
    registry: Annotated[ServerRegistry, Depends(get_server_registry)]
) -> ToolCatalog:
    """Get cached tool catalog."""
    return ToolCatalog(registry)


@lru_cache
def get_tool_cache() -> ToolResultCache:
    """Get cached tool cache."""
    return ToolResultCache(settings.redis_url)


def get_tool_executor(
    registry: Annotated[ServerRegistry, Depends(get_server_registry)],
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
    cache: Annotated[ToolResultCache, Depends(get_tool_cache)],
) -> ToolExecutor:
    """Get tool executor."""
    return ToolExecutor(registry, catalog, cache)


def get_parallel_executor(
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)]
) -> ParallelExecutor:
    """Get parallel executor."""
    return ParallelExecutor(executor)


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    """Get cached provider registry."""
    return ProviderRegistry()


@lru_cache
def get_llm_router(
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)]
) -> LLMRouter:
    """Get cached LLM router."""
    return LLMRouter(registry)


@lru_cache
def get_oracle_agent() -> OracleAgent:
    """Get Oracle agent."""
    return OracleAgent()


@lru_cache
def get_mysql_agent() -> MySQLAgent:
    """Get MySQL agent."""
    return MySQLAgent()


@lru_cache
def get_postgres_agent() -> PostgresAgent:
    """Get PostgreSQL agent."""
    return PostgresAgent()


@lru_cache
def get_coordinator() -> CoordinatorAgent:
    """Get coordinator agent."""
    return CoordinatorAgent()


def get_agent_context(
    catalog: Annotated[ToolCatalog, Depends(get_tool_catalog)],
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    llm_router: Annotated[LLMRouter, Depends(get_llm_router)],
) -> AgentContext:
    """Get agent context with all dependencies."""
    import uuid

    return AgentContext(
        session_id=str(uuid.uuid4()),
        tool_catalog=catalog,
        tool_executor=executor,
        llm_router=llm_router,
    )
