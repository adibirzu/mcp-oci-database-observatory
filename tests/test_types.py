"""Tests for core types."""

import pytest


def test_tool_result_success():
    """Test successful tool result."""
    from src.core.types import ToolResult

    result = ToolResult(
        success=True,
        data={"key": "value"},
        execution_time_ms=150,
        cached=False,
    )

    assert result.success is True
    assert result.data == {"key": "value"}
    assert result.error is None
    assert result.execution_time_ms == 150
    assert result.cached is False


def test_tool_result_failure():
    """Test failed tool result."""
    from src.core.types import ToolResult

    result = ToolResult(
        success=False,
        error="Tool not found",
        execution_time_ms=10,
        cached=False,
    )

    assert result.success is False
    assert result.data is None
    assert result.error == "Tool not found"


def test_tool_call():
    """Test tool call structure."""
    from src.core.types import ToolCall

    call = ToolCall(
        tool="server__tool-name",
        params={"param1": "value1"},
        dependencies=["other__tool"],
    )

    assert call.tool == "server__tool-name"
    assert call.params == {"param1": "value1"}
    assert call.dependencies == ["other__tool"]


def test_agent_response():
    """Test agent response structure."""
    from src.core.types import AgentResponse

    response = AgentResponse(
        success=True,
        agent_name="oracle_agent",
        content="Analysis complete",
        tool_calls=[{"name": "run-sql", "result": "ok"}],
        metadata={"execution_time": 500},
    )

    assert response.success is True
    assert response.agent_name == "oracle_agent"
    assert len(response.tool_calls) == 1
