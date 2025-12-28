"""Tests for MCP Tool Converter.

Tests verify conversion of MCP tools to LangChain format.
"""

import pytest
from unittest.mock import MagicMock

from langchain_core.tools import StructuredTool

from src.mcp.tools.converter import (
    ToolConverter,
    convert_to_langchain_tools,
)
from src.mcp.registry.catalog import ToolCatalog, ToolDefinition


@pytest.fixture
def mock_catalog():
    """Create a mock ToolCatalog."""
    catalog = MagicMock(spec=ToolCatalog)
    return catalog


@pytest.fixture
def sample_tools():
    """Create sample tool definitions."""
    return [
        ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL query on the database",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL query to execute",
                    },
                },
                "required": ["sql"],
            },
        ),
        ToolDefinition(
            name="opsi__analyze_cpu",
            server_id="opsi",
            original_name="analyze_cpu",
            description="Analyze CPU usage for database",
            parameters={
                "type": "object",
                "properties": {
                    "db_id": {
                        "type": "string",
                        "description": "Database ID",
                    },
                },
                "required": ["db_id"],
            },
        ),
    ]


class TestToolConverterInit:
    """Tests for ToolConverter initialization."""

    def test_init_with_catalog(self, mock_catalog):
        """Test initialization with catalog."""
        converter = ToolConverter(mock_catalog)

        assert converter.tool_catalog is mock_catalog
        assert converter.executor is None

    def test_init_with_executor(self, mock_catalog):
        """Test initialization with executor."""
        def mock_executor(name, args):
            return "result"

        converter = ToolConverter(mock_catalog, executor=mock_executor)

        assert converter.executor is mock_executor


class TestToLangchainTools:
    """Tests for converting to LangChain tools."""

    def test_converts_tools_to_structured_tools(self, mock_catalog, sample_tools):
        """Test conversion to StructuredTool list."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools()

        assert len(tools) == 2
        assert all(isinstance(t, StructuredTool) for t in tools)

    def test_tool_has_correct_name(self, mock_catalog, sample_tools):
        """Test that converted tools have correct names."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools()

        names = [t.name for t in tools]
        assert "sqlcl__run-sql" in names
        assert "opsi__analyze_cpu" in names

    def test_tool_has_description(self, mock_catalog, sample_tools):
        """Test that converted tools have descriptions."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools()

        for tool in tools:
            assert tool.description is not None
            assert len(tool.description) > 0

    def test_filter_by_server(self, mock_catalog, sample_tools):
        """Test filtering tools by server."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]  # Only sqlcl

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools(server_filter="sqlcl")

        mock_catalog.list_tools.assert_called_once_with(server_id="sqlcl")
        assert len(tools) == 1
        assert tools[0].name == "sqlcl__run-sql"

    def test_tool_with_executor(self, mock_catalog, sample_tools):
        """Test that tools use provided executor."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]

        def mock_executor(name, args):
            return f"Executed {name}"

        converter = ToolConverter(mock_catalog, executor=mock_executor)
        tools = converter.to_langchain_tools()

        # Invoke the tool
        result = tools[0].invoke({"sql": "SELECT 1"})
        assert "Executed sqlcl__run-sql" in result

    def test_tool_without_executor(self, mock_catalog, sample_tools):
        """Test tool behavior without executor."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools()

        # Invoke the tool - should return placeholder
        result = tools[0].invoke({"sql": "SELECT 1"})
        assert "sqlcl__run-sql" in result
        assert "SELECT 1" in result


class TestToToolDefinitions:
    """Tests for converting to dict format."""

    def test_converts_to_dicts(self, mock_catalog, sample_tools):
        """Test conversion to dict list."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        assert len(defs) == 2
        assert all(isinstance(d, dict) for d in defs)

    def test_dict_has_required_fields(self, mock_catalog, sample_tools):
        """Test that dicts have name, description, parameters."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        assert "name" in defs[0]
        assert "description" in defs[0]
        assert "parameters" in defs[0]

    def test_dict_preserves_parameters(self, mock_catalog, sample_tools):
        """Test that parameters are preserved."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        params = defs[0]["parameters"]
        assert params["type"] == "object"
        assert "sql" in params["properties"]
        assert "sql" in params["required"]


class TestToolWithEmptyParameters:
    """Tests for tools with empty or missing parameters."""

    def test_empty_parameters(self, mock_catalog):
        """Test handling of empty parameters."""
        tool = ToolDefinition(
            name="test__ping",
            server_id="test",
            original_name="ping",
            description="Ping the server",
            parameters={},
        )
        mock_catalog.list_tools.return_value = [tool]

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        # Should provide default schema
        assert defs[0]["parameters"]["type"] == "object"

    def test_missing_description(self, mock_catalog):
        """Test handling of missing description."""
        tool = ToolDefinition(
            name="test__tool",
            server_id="test",
            original_name="tool",
            description="",
        )
        mock_catalog.list_tools.return_value = [tool]

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        # Should generate description from original name
        assert "tool" in defs[0]["description"]


class TestConvenienceFunction:
    """Tests for the convenience function."""

    def test_convert_to_langchain_tools(self, mock_catalog, sample_tools):
        """Test the convenience function."""
        mock_catalog.list_tools.return_value = sample_tools

        tools = convert_to_langchain_tools(mock_catalog)

        assert len(tools) == 2
        assert all(isinstance(t, StructuredTool) for t in tools)

    def test_convert_with_server_filter(self, mock_catalog, sample_tools):
        """Test convenience function with server filter."""
        mock_catalog.list_tools.return_value = [sample_tools[0]]

        tools = convert_to_langchain_tools(
            mock_catalog,
            server_filter="sqlcl",
        )

        mock_catalog.list_tools.assert_called_once_with(server_id="sqlcl")
        assert len(tools) == 1


class TestToolBindingToLLM:
    """Tests for binding tools to LLM."""

    def test_tools_compatible_with_bind_tools(self, mock_catalog, sample_tools):
        """Test that converted tools work with LLM bind_tools."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        tools = converter.to_langchain_tools()

        # Create a mock LLM and verify tools can be bound
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        # This should not raise
        result = mock_llm.bind_tools(tools)

        mock_llm.bind_tools.assert_called_once_with(tools)

    def test_tool_definitions_format(self, mock_catalog, sample_tools):
        """Test tool definitions are in correct format for LLMs."""
        mock_catalog.list_tools.return_value = sample_tools

        converter = ToolConverter(mock_catalog)
        defs = converter.to_tool_definitions()

        # Each definition should have the OpenAI-compatible format
        for tool_def in defs:
            assert "name" in tool_def
            assert isinstance(tool_def["name"], str)
            assert "description" in tool_def
            assert isinstance(tool_def["description"], str)
            assert "parameters" in tool_def
            assert isinstance(tool_def["parameters"], dict)
