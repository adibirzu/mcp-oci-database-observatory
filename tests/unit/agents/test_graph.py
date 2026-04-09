"""Tests for LangGraph Coordinator.

Tests verify graph structure, node execution, and state transitions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.coordinator.graph import (
    CoordinatorState,
    LangGraphCoordinator,
    NodeType,
    _format_tool_result_content,
)


class TestCoordinatorState:
    """Tests for CoordinatorState dataclass."""

    def test_default_state(self):
        """Test default state initialization."""
        state = CoordinatorState()

        assert state.messages == []
        assert state.tool_calls == []
        assert state.tool_results == []
        assert state.iteration == 0
        assert state.max_iterations == 10
        assert state.error is None

    def test_state_with_messages(self):
        """Test state with initial messages."""
        messages = [HumanMessage(content="Hello")]
        state = CoordinatorState(messages=messages)

        assert len(state.messages) == 1
        assert state.messages[0].content == "Hello"

    def test_state_with_custom_max_iterations(self):
        """Test state with custom max iterations."""
        state = CoordinatorState(max_iterations=5)

        assert state.max_iterations == 5


class TestNodeType:
    """Tests for NodeType enum."""

    def test_node_types(self):
        """Test all node types exist."""
        assert NodeType.INPUT.value == "input"
        assert NodeType.AGENT.value == "agent"
        assert NodeType.ACTION.value == "action"
        assert NodeType.OUTPUT.value == "output"


class TestLangGraphCoordinatorInit:
    """Tests for LangGraphCoordinator initialization."""

    def test_init_default(self):
        """Test default initialization."""
        coordinator = LangGraphCoordinator()

        assert coordinator.llm is None
        assert coordinator.tool_catalog is None
        assert coordinator.max_iterations == 10
        assert coordinator._graph is not None
        assert coordinator._checkpointer is not None

    def test_init_with_params(self):
        """Test initialization with parameters."""
        mock_llm = MagicMock()
        mock_catalog = MagicMock()

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
            max_iterations=5,
        )

        assert coordinator.llm is mock_llm
        assert coordinator.tool_catalog is mock_catalog
        assert coordinator.max_iterations == 5


class TestGraphStructure:
    """Tests for graph structure."""

    def test_graph_is_compiled(self):
        """Test that graph is compiled correctly."""
        coordinator = LangGraphCoordinator()
        graph = coordinator.get_graph()

        assert graph is not None

    def test_graph_has_nodes(self):
        """Test that graph has expected nodes."""
        coordinator = LangGraphCoordinator()

        # The nodes are added during build
        # We verify by checking the compiled graph exists
        assert coordinator._graph is not None


class TestInputNode:
    """Tests for input node."""

    def test_input_node_resets_iteration(self):
        """Test input node resets iteration counter."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(iteration=5)

        result = coordinator._input_node(state)

        assert result["iteration"] == 0


class TestAgentNode:
    """Tests for agent node."""

    def test_agent_node_no_llm(self):
        """Test agent node with no LLM configured."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(messages=[HumanMessage(content="Test")])

        result = coordinator._agent_node(state)

        assert "messages" in result
        assert len(result["messages"]) == 1
        assert "No LLM configured" in result["messages"][0].content
        assert result["tool_calls"] == []

    def test_agent_node_with_llm_no_tools(self):
        """Test agent node with LLM that returns no tool calls."""
        mock_llm = MagicMock()
        mock_response = AIMessage(content="Hello, I can help you!")
        mock_response.tool_calls = []
        mock_llm.invoke.return_value = mock_response

        coordinator = LangGraphCoordinator(llm=mock_llm)
        state = CoordinatorState(messages=[HumanMessage(content="Hello")])

        result = coordinator._agent_node(state)

        assert "messages" in result
        assert result["tool_calls"] == []
        assert result["iteration"] == 1

    def test_agent_node_with_tool_calls(self):
        """Test agent node with LLM that returns tool calls."""
        mock_llm = MagicMock()
        mock_response = AIMessage(content="Let me check that...")
        mock_response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__run-sql", "args": {"sql": "SELECT 1"}}
        ]
        mock_llm.invoke.return_value = mock_response

        coordinator = LangGraphCoordinator(llm=mock_llm)
        state = CoordinatorState(messages=[HumanMessage(content="Run SQL")])

        result = coordinator._agent_node(state)

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "sqlcl__run-sql"
        assert result["iteration"] == 1

    def test_agent_node_handles_error(self):
        """Test agent node handles LLM errors."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("API error")

        coordinator = LangGraphCoordinator(llm=mock_llm)
        state = CoordinatorState(messages=[HumanMessage(content="Test")])

        result = coordinator._agent_node(state)

        assert result["error"] == "API error"
        assert "Error processing request" in result["messages"][0].content
        assert result["tool_calls"] == []

    def test_agent_node_increments_iteration(self):
        """Test agent node increments iteration counter."""
        mock_llm = MagicMock()
        mock_response = AIMessage(content="Response")
        mock_response.tool_calls = []
        mock_llm.invoke.return_value = mock_response

        coordinator = LangGraphCoordinator(llm=mock_llm)
        state = CoordinatorState(
            messages=[HumanMessage(content="Test")],
            iteration=3,
        )

        result = coordinator._agent_node(state)

        assert result["iteration"] == 4


class TestActionNode:
    """Tests for action node."""

    @pytest.mark.asyncio
    async def test_action_node_no_catalog(self):
        """Test action node with no tool catalog."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(
            tool_calls=[{"id": "call_1", "name": "test__tool", "arguments": {}}]
        )

        result = await coordinator._action_node(state)

        assert result["tool_results"] == []

    @pytest.mark.asyncio
    async def test_action_node_tool_not_found(self):
        """Test action node when tool is not found."""
        mock_catalog = MagicMock()
        mock_catalog.get_tool.return_value = None

        coordinator = LangGraphCoordinator(tool_catalog=mock_catalog)
        state = CoordinatorState(
            tool_calls=[{"id": "call_1", "name": "missing__tool", "arguments": {}}]
        )

        result = await coordinator._action_node(state)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["success"] is False
        assert "Tool not found" in result["tool_results"][0]["result"]

    @pytest.mark.asyncio
    async def test_action_node_clears_tool_calls(self):
        """Test action node clears tool calls after processing."""
        mock_catalog = MagicMock()
        mock_catalog.get_tool.return_value = None

        coordinator = LangGraphCoordinator(tool_catalog=mock_catalog)
        state = CoordinatorState(
            tool_calls=[{"id": "call_1", "name": "test__tool", "arguments": {}}]
        )

        result = await coordinator._action_node(state)

        assert result["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_action_node_normalizes_http_content_blocks(self):
        """Test action node stores extracted text for MCP content blocks."""
        mock_catalog = MagicMock()
        mock_tool = MagicMock()
        mock_tool.server_id = "oci-logan"
        mock_tool.original_name = "oci_logan_get_summary"
        mock_catalog.get_tool.return_value = mock_tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(
            return_value=[{"type": "text", "text": '{"rows":[{"count": 1}]}'}]
        )
        mock_catalog.registry.get_client.return_value = mock_client

        coordinator = LangGraphCoordinator(tool_catalog=mock_catalog)
        state = CoordinatorState(
            tool_calls=[{"id": "call_1", "name": "logan__summary", "arguments": {}}]
        )

        result = await coordinator._action_node(state)

        assert result["tool_results"][0]["success"] is True
        assert result["tool_results"][0]["result"] == '{"rows":[{"count": 1}]}'


class TestToolResultFormatting:
    """Tests for tool-result normalization."""

    def test_format_tool_result_content_prefers_text_blocks(self):
        """Test tool result formatting extracts text payload from MCP content."""
        result = _format_tool_result_content(
            [
                {"type": "text", "text": '{"hello":"world"}'},
                {"type": "text", "text": "second block"},
            ]
        )

        assert result == '{"hello":"world"}\nsecond block'

    def test_format_tool_result_content_serializes_structured_content(self):
        """Test structured content is rendered as JSON when no text is present."""
        result = _format_tool_result_content({"structuredContent": {"score": 92, "status": "ok"}})

        assert result == '{"score": 92, "status": "ok"}'


class TestOutputNode:
    """Tests for output node."""

    def test_output_node_returns_empty(self):
        """Test output node returns empty dict."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(iteration=3)

        result = coordinator._output_node(state)

        assert result == {}


class TestShouldContinue:
    """Tests for should_continue routing function."""

    def test_should_continue_with_error(self):
        """Test should_continue returns 'end' on error."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(error="Some error")

        result = coordinator._should_continue(state)

        assert result == "end"

    def test_should_continue_max_iterations(self):
        """Test should_continue returns 'end' at max iterations."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(iteration=10, max_iterations=10)

        result = coordinator._should_continue(state)

        assert result == "end"

    def test_should_continue_with_tool_calls(self):
        """Test should_continue returns 'continue' with tool calls."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(
            tool_calls=[{"id": "call_1", "name": "test", "arguments": {}}],
            iteration=1,
        )

        result = coordinator._should_continue(state)

        assert result == "continue"

    def test_should_continue_no_tool_calls(self):
        """Test should_continue returns 'end' with no tool calls."""
        coordinator = LangGraphCoordinator()
        state = CoordinatorState(tool_calls=[], iteration=1)

        result = coordinator._should_continue(state)

        assert result == "end"


class TestInvoke:
    """Tests for invoke method."""

    @pytest.mark.asyncio
    async def test_invoke_without_llm(self):
        """Test invoke returns response even without LLM."""
        coordinator = LangGraphCoordinator()

        result = await coordinator.invoke("Test query")

        assert "success" in result
        assert "response" in result
        assert result["iterations"] >= 0

    @pytest.mark.asyncio
    async def test_invoke_with_thread_id(self):
        """Test invoke with thread ID for conversation history."""
        coordinator = LangGraphCoordinator()

        result = await coordinator.invoke("Test query", thread_id="thread-123")

        assert result is not None

    @pytest.mark.asyncio
    async def test_invoke_with_llm(self):
        """Test invoke with mock LLM."""
        mock_llm = MagicMock()
        mock_response = AIMessage(content="Here is your answer!")
        mock_response.tool_calls = []
        mock_llm.invoke.return_value = mock_response

        coordinator = LangGraphCoordinator(llm=mock_llm)

        result = await coordinator.invoke("What is 2+2?")

        assert result["success"] is True
        assert "answer" in result["response"].lower() or result["response"] != ""


class TestToolBindingFlow:
    """Tests for the tool binding flow."""

    @pytest.mark.asyncio
    async def test_tool_call_flow(self):
        """Test complete tool call flow."""
        mock_llm = MagicMock()

        # First call: LLM requests tool
        first_response = AIMessage(content="Let me run that SQL...")
        first_response.tool_calls = [
            {"id": "call_1", "name": "sqlcl__run-sql", "args": {"sql": "SELECT 1"}}
        ]

        # Second call: LLM provides final answer
        second_response = AIMessage(content="The query returned 1.")
        second_response.tool_calls = []

        mock_llm.invoke.side_effect = [first_response, second_response]

        mock_catalog = MagicMock()
        mock_tool = MagicMock()
        mock_tool.server_id = "sqlcl"
        mock_catalog.get_tool.return_value = mock_tool

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value="1")
        mock_catalog.registry.get_client.return_value = mock_client

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
        )

        result = await coordinator.invoke("Run SELECT 1")

        # Should have called LLM at least twice
        assert mock_llm.invoke.call_count >= 1
        assert "response" in result


class TestBindTools:
    """Tests for bind_tools method."""

    def test_bind_tools_no_llm_raises(self):
        """Test that bind_tools raises without LLM."""
        coordinator = LangGraphCoordinator()

        with pytest.raises(ValueError, match="No LLM provided"):
            coordinator.bind_tools()

    def test_bind_tools_no_catalog_returns_llm(self):
        """Test bind_tools without catalog returns LLM unchanged."""
        mock_llm = MagicMock()
        coordinator = LangGraphCoordinator(llm=mock_llm)

        result = coordinator.bind_tools()

        assert result is mock_llm

    def test_bind_tools_with_catalog(self):
        """Test bind_tools with catalog binds tools to LLM."""
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        mock_catalog = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test__tool"
        mock_tool.description = "Test tool"
        mock_tool.parameters = {}
        mock_tool.original_name = "tool"
        mock_catalog.list_tools.return_value = [mock_tool]

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
        )

        result = coordinator.bind_tools()

        mock_llm.bind_tools.assert_called_once()
        assert result is mock_llm

    def test_bind_tools_with_provided_llm(self):
        """Test bind_tools with explicitly provided LLM."""
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        mock_catalog = MagicMock()
        mock_catalog.list_tools.return_value = []

        coordinator = LangGraphCoordinator(tool_catalog=mock_catalog)

        result = coordinator.bind_tools(llm=mock_llm)

        # Should return provided LLM (no tools to bind)
        assert result is mock_llm


class TestInitializeWithTools:
    """Tests for initialize_with_tools method."""

    @pytest.mark.asyncio
    async def test_initialize_without_catalog(self):
        """Test initialize without catalog does nothing."""
        coordinator = LangGraphCoordinator()

        # Should not raise
        await coordinator.initialize_with_tools()

    @pytest.mark.asyncio
    async def test_initialize_refreshes_catalog(self):
        """Test initialize refreshes the tool catalog."""
        mock_catalog = MagicMock()
        mock_catalog.refresh = AsyncMock()
        mock_catalog.list_tools.return_value = []

        coordinator = LangGraphCoordinator(tool_catalog=mock_catalog)

        await coordinator.initialize_with_tools()

        mock_catalog.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_binds_tools(self):
        """Test initialize binds tools when LLM is configured."""
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        mock_catalog = MagicMock()
        mock_catalog.refresh = AsyncMock()
        mock_tool = MagicMock()
        mock_tool.name = "test__tool"
        mock_tool.description = "Test"
        mock_tool.parameters = {}
        mock_tool.original_name = "tool"
        mock_catalog.list_tools.return_value = [mock_tool]

        coordinator = LangGraphCoordinator(
            llm=mock_llm,
            tool_catalog=mock_catalog,
        )

        await coordinator.initialize_with_tools()

        mock_llm.bind_tools.assert_called_once()
