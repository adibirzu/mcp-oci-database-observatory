"""Tests for MCP Tool Executor.

Tests verify tool execution, caching, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.mcp.executor.executor import ToolExecutor
from src.mcp.registry.catalog import ToolDefinition
from src.agents.base.context import AgentContext


@pytest.fixture
def mock_registry():
    """Create a mock ServerRegistry."""
    return MagicMock()


@pytest.fixture
def mock_catalog():
    """Create a mock ToolCatalog."""
    return MagicMock()


@pytest.fixture
def mock_cache():
    """Create a mock ToolResultCache."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    return MagicMock(spec=AgentContext, session_id="test-session")


@pytest.fixture
def sample_tool():
    """Create a sample tool definition."""
    return ToolDefinition(
        name="sqlcl__run-sql",
        server_id="sqlcl",
        original_name="run-sql",
        description="Execute SQL query",
        parameters={},
        ttl_seconds=0,
    )


@pytest.fixture
def executor(mock_registry, mock_catalog, mock_cache):
    """Create a ToolExecutor with mocks."""
    return ToolExecutor(mock_registry, mock_catalog, mock_cache)


class TestToolExecutorInit:
    """Tests for ToolExecutor initialization."""

    def test_init_with_all_params(self, mock_registry, mock_catalog, mock_cache):
        """Test initialization with all parameters."""
        executor = ToolExecutor(mock_registry, mock_catalog, mock_cache)

        assert executor.registry is mock_registry
        assert executor.catalog is mock_catalog
        assert executor.cache is mock_cache

    def test_init_without_cache(self, mock_registry, mock_catalog):
        """Test initialization without cache."""
        executor = ToolExecutor(mock_registry, mock_catalog)

        assert executor.cache is None


class TestExecuteDirect:
    """Tests for direct tool execution."""

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(
        self, executor, mock_catalog, mock_context
    ):
        """Test execution when tool is not found."""
        mock_catalog.get_tool.return_value = None

        with pytest.raises(Exception, match="Tool not found"):
            await executor.execute_direct("missing__tool", {}, mock_context)

    @pytest.mark.asyncio
    async def test_execute_server_not_found(
        self, executor, mock_catalog, mock_registry, mock_context, sample_tool
    ):
        """Test execution when server is not found."""
        mock_catalog.get_tool.return_value = sample_tool
        mock_registry.get_client.return_value = None

        with pytest.raises(Exception, match="Server not found"):
            await executor.execute_direct("sqlcl__run-sql", {}, mock_context)

    @pytest.mark.asyncio
    async def test_execute_success(
        self, executor, mock_catalog, mock_registry, mock_context, sample_tool
    ):
        """Test successful tool execution."""
        mock_catalog.get_tool.return_value = sample_tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "success"})
        mock_registry.get_client.return_value = mock_client

        result = await executor.execute_direct(
            "sqlcl__run-sql",
            {"sql": "SELECT 1"},
            mock_context,
        )

        assert result.success is True
        assert result.data == {"result": "success"}
        mock_client.call_tool.assert_called_once_with("run-sql", {"sql": "SELECT 1"})

    @pytest.mark.asyncio
    async def test_execute_handles_exception(
        self, executor, mock_catalog, mock_registry, mock_context, sample_tool
    ):
        """Test execution handles exceptions gracefully."""
        mock_catalog.get_tool.return_value = sample_tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(side_effect=Exception("Connection error"))
        mock_registry.get_client.return_value = mock_client

        result = await executor.execute_direct(
            "sqlcl__run-sql",
            {},
            mock_context,
        )

        assert result.success is False
        assert "Connection error" in result.error


class TestCaching:
    """Tests for caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit(
        self, mock_registry, mock_catalog, mock_cache, mock_context
    ):
        """Test cache hit returns cached result."""
        tool = ToolDefinition(
            name="opsi__get_fleet",
            server_id="opsi",
            original_name="get_fleet",
            description="Get fleet summary",
            ttl_seconds=1800,  # 30 min cache
        )
        mock_catalog.get_tool.return_value = tool
        mock_cache.get = AsyncMock(return_value={"cached": "data"})

        executor = ToolExecutor(mock_registry, mock_catalog, mock_cache)
        result = await executor.execute_direct("opsi__get_fleet", {}, mock_context)

        assert result.success is True
        assert result.cached is True
        assert result.data == {"cached": "data"}

    @pytest.mark.asyncio
    async def test_cache_miss_executes_tool(
        self, mock_registry, mock_catalog, mock_cache, mock_context
    ):
        """Test cache miss executes tool and caches result."""
        tool = ToolDefinition(
            name="opsi__get_fleet",
            server_id="opsi",
            original_name="get_fleet",
            description="Get fleet summary",
            ttl_seconds=1800,
        )
        mock_catalog.get_tool.return_value = tool
        mock_cache.get = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={"fresh": "data"})
        mock_registry.get_client.return_value = mock_client

        executor = ToolExecutor(mock_registry, mock_catalog, mock_cache)
        result = await executor.execute_direct("opsi__get_fleet", {}, mock_context)

        assert result.success is True
        assert result.cached is False
        assert result.data == {"fresh": "data"}
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_cache_for_realtime_tools(
        self, mock_registry, mock_catalog, mock_cache, mock_context
    ):
        """Test that realtime tools bypass cache."""
        tool = ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL",
            ttl_seconds=0,  # No caching
        )
        mock_catalog.get_tool.return_value = tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={"rows": []})
        mock_registry.get_client.return_value = mock_client

        executor = ToolExecutor(mock_registry, mock_catalog, mock_cache)
        result = await executor.execute_direct(
            "sqlcl__run-sql",
            {"sql": "SELECT 1"},
            mock_context,
        )

        assert result.success is True
        # Should not check or set cache
        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()


class TestCacheKeyBuilding:
    """Tests for cache key generation."""

    def test_cache_key_includes_tool_name(self, executor):
        """Test cache key includes tool name."""
        key = executor._build_cache_key("sqlcl__run-sql", {"sql": "SELECT 1"})

        assert "sqlcl__run-sql" in key

    def test_cache_key_includes_params_hash(self, executor):
        """Test cache key includes params hash."""
        key1 = executor._build_cache_key("tool", {"a": 1})
        key2 = executor._build_cache_key("tool", {"a": 2})

        assert key1 != key2

    def test_cache_key_deterministic(self, executor):
        """Test cache key is deterministic."""
        key1 = executor._build_cache_key("tool", {"a": 1, "b": 2})
        key2 = executor._build_cache_key("tool", {"b": 2, "a": 1})

        assert key1 == key2  # Same params, different order


class TestToolResultMetrics:
    """Tests for execution timing and metrics."""

    @pytest.mark.asyncio
    async def test_result_includes_execution_time(
        self, executor, mock_catalog, mock_registry, mock_context, sample_tool
    ):
        """Test result includes execution time."""
        mock_catalog.get_tool.return_value = sample_tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={})
        mock_registry.get_client.return_value = mock_client

        result = await executor.execute_direct(
            "sqlcl__run-sql",
            {},
            mock_context,
        )

        assert result.execution_time_ms >= 0
