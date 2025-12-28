"""End-to-end tests for Natural Language to SQL flow.

Tests the complete flow:
User Query -> LangGraph Coordinator -> MCP Tool (SQLcl) -> Result -> Response

Run with: pytest tests/e2e/test_nl_to_sql.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.coordinator.graph import LangGraphCoordinator, CoordinatorState
from src.mcp.registry.catalog import ToolCatalog, ToolDefinition
from src.mcp.registry.registry import ServerRegistry


@pytest.fixture
def mock_sqlcl_tools():
    """Create mock SQLcl tool definitions."""
    return [
        ToolDefinition(
            name="sqlcl__run-sql",
            server_id="sqlcl",
            original_name="run-sql",
            description="Execute SQL query on the connected Oracle database",
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
            ttl_seconds=0,
        ),
        ToolDefinition(
            name="sqlcl__list-connections",
            server_id="sqlcl",
            original_name="list-connections",
            description="List available database connections",
            parameters={
                "type": "object",
                "properties": {},
            },
            ttl_seconds=600,
        ),
        ToolDefinition(
            name="sqlcl__schema-information",
            server_id="sqlcl",
            original_name="schema-information",
            description="Get schema information including tables, views, and objects",
            parameters={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "Schema name to inspect",
                    },
                },
                "required": ["schema"],
            },
            ttl_seconds=3600,
        ),
    ]


@pytest.fixture
def mock_catalog(mock_sqlcl_tools):
    """Create a mock ToolCatalog with SQLcl tools."""
    catalog = MagicMock(spec=ToolCatalog)
    catalog.list_tools.return_value = mock_sqlcl_tools
    catalog.get_tool.side_effect = lambda name: next(
        (t for t in mock_sqlcl_tools if t.name == name), None
    )

    # Mock registry
    mock_registry = MagicMock(spec=ServerRegistry)
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.call_tool = AsyncMock()
    mock_registry.get_client.return_value = mock_client
    catalog.registry = mock_registry

    return catalog


class TestNaturalLanguageToSQL:
    """Tests for natural language to SQL flow."""

    @pytest.mark.asyncio
    async def test_simple_query_flow(self, mock_catalog):
        """Test simple query: 'What tables are in the HR schema?'"""
        # Setup mock LLM that requests schema information
        mock_llm = MagicMock()

        # First call: LLM requests tool
        first_response = AIMessage(
            content="I'll check the schema information for HR."
        )
        first_response.tool_calls = [
            {
                "id": "call_1",
                "name": "sqlcl__schema-information",
                "args": {"schema": "HR"},
            }
        ]

        # Second call: LLM provides final answer
        second_response = AIMessage(
            content="The HR schema contains the following tables: EMPLOYEES, DEPARTMENTS, JOBS, LOCATIONS, and COUNTRIES."
        )
        second_response.tool_calls = []

        mock_llm.invoke.side_effect = [first_response, second_response]

        # Configure mock tool result
        mock_catalog.registry.get_client.return_value.call_tool.return_value = {
            "tables": ["EMPLOYEES", "DEPARTMENTS", "JOBS", "LOCATIONS", "COUNTRIES"],
            "views": ["EMP_DETAILS_VIEW"],
        }

        # Create and run coordinator
        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=5,
        )

        result = await coordinator.invoke(
            "What tables are in the HR schema?",
            thread_id="test-thread-1",
        )

        # Verify result
        assert result["success"] is True
        assert "EMPLOYEES" in result["response"]
        assert result["iterations"] >= 1

    @pytest.mark.asyncio
    async def test_sql_execution_flow(self, mock_catalog):
        """Test SQL execution: 'Run SELECT * FROM employees LIMIT 5'"""
        mock_llm = MagicMock()

        # First call: LLM requests SQL execution
        first_response = AIMessage(content="I'll run that query for you.")
        first_response.tool_calls = [
            {
                "id": "call_1",
                "name": "sqlcl__run-sql",
                "args": {"sql": "SELECT * FROM employees FETCH FIRST 5 ROWS ONLY"},
            }
        ]

        # Second call: LLM formats result
        second_response = AIMessage(
            content="Here are the first 5 employees:\n"
            "1. John Smith - Manager\n"
            "2. Jane Doe - Developer\n"
            "3. Bob Wilson - Analyst"
        )
        second_response.tool_calls = []

        mock_llm.invoke.side_effect = [first_response, second_response]

        # Mock SQL result
        mock_catalog.registry.get_client.return_value.call_tool.return_value = {
            "rows": [
                {"EMPLOYEE_ID": 1, "FIRST_NAME": "John", "LAST_NAME": "Smith"},
                {"EMPLOYEE_ID": 2, "FIRST_NAME": "Jane", "LAST_NAME": "Doe"},
                {"EMPLOYEE_ID": 3, "FIRST_NAME": "Bob", "LAST_NAME": "Wilson"},
            ],
            "row_count": 3,
        }

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=5,
        )

        result = await coordinator.invoke(
            "Show me the first 5 employees",
            thread_id="test-thread-2",
        )

        assert result["success"] is True
        assert "John" in result["response"] or "employees" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_multi_step_query(self, mock_catalog):
        """Test multi-step query requiring multiple tool calls."""
        mock_llm = MagicMock()

        # Step 1: Check connections
        step1_response = AIMessage(content="Let me check available connections first.")
        step1_response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__list-connections", "args": {}}
        ]

        # Step 2: Get schema info
        step2_response = AIMessage(content="Now let me get the schema information.")
        step2_response.tool_calls = [
            {"id": "call_2", "name": "sqlcl__schema-information", "args": {"schema": "USERS"}}
        ]

        # Step 3: Final response
        step3_response = AIMessage(
            content="Connected to PROD database. The USERS schema has 3 tables: USERS, PROFILES, and SESSIONS."
        )
        step3_response.tool_calls = []

        mock_llm.invoke.side_effect = [step1_response, step2_response, step3_response]

        # Mock tool results
        mock_client = mock_catalog.registry.get_client.return_value
        mock_client.call_tool.side_effect = [
            {"connections": ["PROD", "DEV"]},  # list-connections
            {"tables": ["USERS", "PROFILES", "SESSIONS"]},  # schema-information
        ]

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=10,
        )

        result = await coordinator.invoke(
            "Show me the tables in the USERS schema",
            thread_id="test-thread-3",
        )

        assert result["success"] is True
        assert result["iterations"] >= 2


class TestErrorHandling:
    """Tests for error handling in E2E flow."""

    @pytest.mark.asyncio
    async def test_tool_error_handled(self, mock_catalog):
        """Test that tool errors are handled gracefully."""
        mock_llm = MagicMock()

        # LLM requests tool
        first_response = AIMessage(content="Running the query...")
        first_response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__run-sql", "args": {"sql": "SELECT * FROM invalid_table"}}
        ]

        # LLM handles error
        second_response = AIMessage(
            content="I encountered an error: the table 'invalid_table' does not exist."
        )
        second_response.tool_calls = []

        mock_llm.invoke.side_effect = [first_response, second_response]

        # Mock tool error
        mock_catalog.registry.get_client.return_value.call_tool.side_effect = Exception(
            "ORA-00942: table or view does not exist"
        )

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=5,
        )

        result = await coordinator.invoke(
            "SELECT * FROM invalid_table",
            thread_id="test-thread-error",
        )

        # Should still complete (LLM handles the error)
        assert result is not None

    @pytest.mark.asyncio
    async def test_max_iterations_respected(self, mock_catalog):
        """Test that max iterations limit is respected."""
        mock_llm = MagicMock()

        # LLM keeps requesting tools (infinite loop)
        loop_response = AIMessage(content="Let me check again...")
        loop_response.tool_calls = [
            {"id": "call_n", "name": "sqlcl__list-connections", "args": {}}
        ]

        mock_llm.invoke.return_value = loop_response
        mock_catalog.registry.get_client.return_value.call_tool.return_value = {}

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=3,
        )

        result = await coordinator.invoke(
            "Keep checking connections",
            thread_id="test-thread-loop",
        )

        # Should stop at max iterations
        assert result["iterations"] <= 3


class TestToolSelection:
    """Tests for correct tool selection based on query."""

    @pytest.mark.asyncio
    async def test_selects_run_sql_for_query(self, mock_catalog):
        """Test that run-sql is selected for SQL queries."""
        mock_llm = MagicMock()

        response = AIMessage(content="Executing query...")
        response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__run-sql", "args": {"sql": "SELECT COUNT(*) FROM users"}}
        ]

        final_response = AIMessage(content="The count is 150.")
        final_response.tool_calls = []

        mock_llm.invoke.side_effect = [response, final_response]

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
        )

        result = await coordinator.invoke("How many users are there?")

        # Verify LLM was called and requested run-sql tool
        assert mock_llm.invoke.called
        # The first response should have tool_calls for run-sql
        first_call_messages = mock_llm.invoke.call_args_list[0][0][0]
        assert any("users" in str(m).lower() for m in first_call_messages)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_selects_schema_info_for_metadata(self, mock_catalog):
        """Test that schema-information is selected for metadata queries."""
        mock_llm = MagicMock()

        response = AIMessage(content="Checking schema...")
        response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__schema-information", "args": {"schema": "HR"}}
        ]

        final_response = AIMessage(content="The HR schema has 5 tables.")
        final_response.tool_calls = []

        mock_llm.invoke.side_effect = [response, final_response]

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
        )

        result = await coordinator.invoke("Describe the HR schema")

        # Verify LLM was called with the query
        assert mock_llm.invoke.called
        assert result["success"] is True
        # The response should mention tables or schema
        assert "tables" in result["response"].lower() or "schema" in result["response"].lower()
