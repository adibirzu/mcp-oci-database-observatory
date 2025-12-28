"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock

# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.setex = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.ping = AsyncMock(return_value=True)
    client.info = AsyncMock(return_value={"used_memory_human": "1M"})
    return client


@pytest.fixture
def mock_tool_catalog():
    """Mock tool catalog."""
    catalog = MagicMock()
    catalog.list_tools = MagicMock(return_value=[])
    catalog.get_tool = MagicMock(return_value=None)
    catalog.search_tools = MagicMock(return_value=[])
    return catalog


@pytest.fixture
def mock_tool_executor():
    """Mock tool executor."""
    from src.core.types import ToolResult

    executor = AsyncMock()
    executor.execute_direct = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"result": "test"},
            execution_time_ms=100,
            cached=False,
        )
    )
    return executor


@pytest.fixture
def mock_llm_router():
    """Mock LLM router."""
    from src.llm.providers.base import LLMResponse

    router = AsyncMock()
    router.route = AsyncMock(
        return_value=LLMResponse(
            content="Test response",
            model="test-model",
            provider="test",
            usage={"input_tokens": 10, "output_tokens": 20},
        )
    )
    router.classify_task = MagicMock(return_value=MagicMock(value="general"))
    return router


@pytest.fixture
def agent_context(mock_tool_catalog, mock_tool_executor, mock_llm_router):
    """Create agent context with mocks."""
    from src.agents.base.context import AgentContext

    return AgentContext(
        session_id="test-session",
        tool_catalog=mock_tool_catalog,
        tool_executor=mock_tool_executor,
        llm_router=mock_llm_router,
    )
