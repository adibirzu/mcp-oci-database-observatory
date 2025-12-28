"""Core type definitions for the observatory framework."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DatabaseType(str, Enum):
    """Supported database types."""
    ORACLE = "oracle"
    MYSQL = "mysql"
    POSTGRES = "postgres"


class IntentType(str, Enum):
    """Query intent classifications."""
    DIAGNOSE = "diagnose"
    ANALYZE = "analyze"
    OPTIMIZE = "optimize"
    MONITOR = "monitor"
    COMPARE = "compare"


class Severity(str, Enum):
    """Finding severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class TaskType(str, Enum):
    """LLM task types for routing."""
    CLASSIFICATION = "classification"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    CODE_GENERATION = "code_generation"


@dataclass
class TimeRange:
    """Time range for queries."""
    start: datetime
    end: datetime


@dataclass
class IntentResult:
    """Result of intent classification."""
    primary_intent: IntentType
    database_type: DatabaseType | str  # Can be "multi" or "unknown"
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    suggested_agents: list[str] = field(default_factory=list)


@dataclass
class AgentTask:
    """Task assigned to a specialist agent."""
    id: str
    agent_type: DatabaseType
    intent: IntentResult
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 1


@dataclass
class DiagnosticFinding:
    """A diagnostic finding from an agent."""
    id: str
    severity: Severity
    category: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None


@dataclass
class AgentResult:
    """Result from agent execution."""
    task_id: str
    agent_type: DatabaseType
    success: bool
    findings: list[DiagnosticFinding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    execution_time_ms: int = 0
    tools_used: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    """MCP tool call specification."""
    tool: str  # Format: server__tool
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    """Result from MCP tool execution."""
    success: bool
    data: Any = None
    error: str | None = None
    execution_time_ms: int = 0
    cached: bool = False


@dataclass
class LLMOptions:
    """Options for LLM requests."""
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    task_type: TaskType | None = None


@dataclass
class LLMResponse:
    """Response from LLM provider."""
    text: str | None = None
    function_calls: list[dict[str, Any]] | None = None


@dataclass
class AgentResponse:
    """Response from agent processing."""
    success: bool
    agent_name: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    """MCP server configuration."""
    id: str
    name: str
    transport: str  # "stdio" or "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    databases: list[DatabaseType] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
