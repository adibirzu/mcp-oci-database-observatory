"""Tests for MCP Tool Catalog.

Tests verify tool aggregation, namespacing, and TTL assignment.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.mcp.registry.catalog import ToolCatalog, ToolDefinition
from src.mcp.registry.registry import ServerRegistry


@pytest.fixture
def mock_registry():
    """Create a mock ServerRegistry."""
    registry = MagicMock(spec=ServerRegistry)
    return registry


@pytest.fixture
def catalog(mock_registry):
    """Create a ToolCatalog with mock registry."""
    return ToolCatalog(mock_registry)


class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""

    def test_tool_definition_creation(self):
        """Test basic ToolDefinition creation."""
        tool = ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL query",
            parameters={"sql": {"type": "string"}},
            ttl_seconds=0,
        )

        assert tool.name == "sqlcl__run-sql"
        assert tool.server_id == "sqlcl"
        assert tool.original_name == "run-sql"
        assert tool.description == "Execute SQL query"
        assert tool.parameters == {"sql": {"type": "string"}}
        assert tool.ttl_seconds == 0

    def test_tool_definition_defaults(self):
        """Test ToolDefinition default values."""
        tool = ToolDefinition(
            name="test__tool",
            server_id="test",
            original_name="tool",
            description="Test tool",
        )

        assert tool.parameters == {}
        assert tool.ttl_seconds == 120  # Default TTL


class TestToolCatalogInit:
    """Tests for ToolCatalog initialization."""

    def test_catalog_init(self, mock_registry):
        """Test catalog initialization."""
        catalog = ToolCatalog(mock_registry)

        assert catalog.registry is mock_registry
        assert catalog._tools == {}


class TestToolCatalogRefresh:
    """Tests for ToolCatalog refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_aggregates_tools(self, catalog, mock_registry):
        """Test that refresh aggregates tools from all servers."""
        # Setup mock clients
        mock_client1 = MagicMock()
        mock_client1.is_connected = True
        mock_client1.get_tools.return_value = [
            {"name": "run-sql", "description": "Execute SQL", "inputSchema": {}},
            {"name": "connect", "description": "Connect to DB", "inputSchema": {}},
        ]

        mock_client2 = MagicMock()
        mock_client2.is_connected = True
        mock_client2.get_tools.return_value = [
            {"name": "skill_analyze_cpu", "description": "Analyze CPU usage", "inputSchema": {}},
        ]

        # Setup registry to return servers
        mock_registry.list_servers.return_value = [
            {"id": "sqlcl", "name": "SQLcl"},
            {"id": "opsi", "name": "OPSI"},
        ]
        mock_registry.get_client.side_effect = lambda sid: {
            "sqlcl": mock_client1,
            "opsi": mock_client2,
        }.get(sid)

        await catalog.refresh()

        # Should have 3 tools
        assert len(catalog._tools) == 3
        assert "sqlcl__run-sql" in catalog._tools
        assert "sqlcl__connect" in catalog._tools
        assert "opsi__skill_analyze_cpu" in catalog._tools

    @pytest.mark.asyncio
    async def test_refresh_clears_existing_tools(self, catalog, mock_registry):
        """Test that refresh clears existing tools."""
        # Pre-populate with some tools
        catalog._tools["old__tool"] = ToolDefinition(
            name="old__tool",
            server_id="old",
            original_name="tool",
            description="Old tool",
        )

        mock_registry.list_servers.return_value = []

        await catalog.refresh()

        assert len(catalog._tools) == 0

    @pytest.mark.asyncio
    async def test_refresh_skips_disconnected_servers(self, catalog, mock_registry):
        """Test that refresh skips disconnected servers."""
        mock_client = MagicMock()
        mock_client.is_connected = False

        mock_registry.list_servers.return_value = [{"id": "offline", "name": "Offline"}]
        mock_registry.get_client.return_value = mock_client

        await catalog.refresh()

        assert len(catalog._tools) == 0
        mock_client.get_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_handles_errors(self, catalog, mock_registry):
        """Test that refresh handles server errors gracefully."""
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.get_tools.side_effect = Exception("Connection error")

        mock_registry.list_servers.return_value = [{"id": "broken", "name": "Broken"}]
        mock_registry.get_client.return_value = mock_client

        # Should not raise
        await catalog.refresh()

        assert len(catalog._tools) == 0


class TestToolCatalogTTL:
    """Tests for TTL assignment based on tool type."""

    def test_ttl_static_tools(self, catalog):
        """Test TTL for static tools (1 hour)."""
        assert catalog._get_ttl("list_oci_profiles") == 3600
        assert catalog._get_ttl("list_parsers") == 3600
        assert catalog._get_ttl("schema-information") == 3600

    def test_ttl_stable_tools(self, catalog):
        """Test TTL for stable tools (30 min)."""
        assert catalog._get_ttl("list_compartments") == 1800
        assert catalog._get_ttl("list_log_sources") == 1800
        assert catalog._get_ttl("get_fleet_summary") == 1800

    def test_ttl_infrastructure_tools(self, catalog):
        """Test TTL for infrastructure tools (10 min)."""
        assert catalog._get_ttl("list_autonomous_databases") == 600
        assert catalog._get_ttl("list-connections") == 600
        assert catalog._get_ttl("list_databases") == 600

    def test_ttl_realtime_tools(self, catalog):
        """Test TTL for realtime tools (no cache)."""
        assert catalog._get_ttl("run-sql") == 0
        assert catalog._get_ttl("connect") == 0
        assert catalog._get_ttl("disconnect") == 0
        assert catalog._get_ttl("ping") == 0

    def test_ttl_default(self, catalog):
        """Test default TTL (2 min)."""
        assert catalog._get_ttl("some_unknown_tool") == 120


class TestToolCatalogLookup:
    """Tests for tool lookup methods."""

    def test_get_tool_found(self, catalog):
        """Test getting an existing tool."""
        tool = ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL",
        )
        catalog._tools["sqlcl__run-sql"] = tool

        result = catalog.get_tool("sqlcl__run-sql")

        assert result is tool

    def test_get_tool_not_found(self, catalog):
        """Test getting a non-existent tool."""
        result = catalog.get_tool("nonexistent__tool")

        assert result is None

    def test_get_ttl_for_tool(self, catalog):
        """Test getting TTL for a registered tool."""
        tool = ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL",
            ttl_seconds=0,
        )
        catalog._tools["sqlcl__run-sql"] = tool

        result = catalog.get_ttl("sqlcl__run-sql")

        assert result == 0

    def test_get_ttl_for_missing_tool(self, catalog):
        """Test getting TTL for a missing tool."""
        result = catalog.get_ttl("nonexistent__tool")

        assert result == 0


class TestToolCatalogList:
    """Tests for listing tools."""

    def test_list_all_tools(self, catalog):
        """Test listing all tools."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="SQL",
            ),
            "opsi__analyze": ToolDefinition(
                name="opsi__analyze", server_id="opsi",
                original_name="analyze", description="Analyze",
            ),
        }

        result = catalog.list_tools()

        assert len(result) == 2

    def test_list_tools_by_server(self, catalog):
        """Test listing tools filtered by server."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="SQL",
            ),
            "sqlcl__connect": ToolDefinition(
                name="sqlcl__connect", server_id="sqlcl",
                original_name="connect", description="Connect",
            ),
            "opsi__analyze": ToolDefinition(
                name="opsi__analyze", server_id="opsi",
                original_name="analyze", description="Analyze",
            ),
        }

        result = catalog.list_tools(server_id="sqlcl")

        assert len(result) == 2
        assert all(t.server_id == "sqlcl" for t in result)

    def test_list_tools_empty_server_filter(self, catalog):
        """Test listing tools for server with no tools."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="SQL",
            ),
        }

        result = catalog.list_tools(server_id="nonexistent")

        assert len(result) == 0


class TestToolCatalogSearch:
    """Tests for tool search functionality."""

    def test_search_by_name(self, catalog):
        """Test searching tools by name."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="Execute SQL query",
            ),
            "opsi__analyze_cpu": ToolDefinition(
                name="opsi__analyze_cpu", server_id="opsi",
                original_name="analyze_cpu", description="CPU analysis",
            ),
        }

        result = catalog.search_tools("sql")

        # "sqlcl__run-sql" matches (contains "sql" in name and description)
        assert len(result) == 1
        assert result[0].name == "sqlcl__run-sql"

    def test_search_by_description(self, catalog):
        """Test searching tools by description."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="Execute SQL query on database",
            ),
            "opsi__analyze_cpu": ToolDefinition(
                name="opsi__analyze_cpu", server_id="opsi",
                original_name="analyze_cpu", description="CPU analysis tool",
            ),
        }

        result = catalog.search_tools("database")

        assert len(result) == 1
        assert result[0].name == "sqlcl__run-sql"

    def test_search_case_insensitive(self, catalog):
        """Test that search is case insensitive."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="Execute SQL Query",
            ),
        }

        result = catalog.search_tools("SQL")

        assert len(result) == 1

    def test_search_no_results(self, catalog):
        """Test search with no matches."""
        catalog._tools = {
            "sqlcl__run-sql": ToolDefinition(
                name="sqlcl__run-sql", server_id="sqlcl",
                original_name="run-sql", description="Execute SQL query",
            ),
        }

        result = catalog.search_tools("kubernetes")

        assert len(result) == 0
