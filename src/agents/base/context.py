"""Agent execution context management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.core.types import TimeRange

if TYPE_CHECKING:
    from src.llm import LLMRouter
    from src.mcp.executor import ToolExecutor
    from src.mcp.registry import ToolCatalog


@dataclass
class AgentContext:
    """Execution context passed to agents.

    Contains session information, constraints, dependencies,
    and metadata that agents use during task execution.
    """

    session_id: str
    user_id: str | None = None
    tenancy_id: str | None = None
    oci_profile: str = "DEFAULT"
    databases: list[str] = field(default_factory=list)
    time_range: TimeRange | None = None
    max_iterations: int = 12
    iteration_count: int = 0
    parent_trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Runtime dependencies (injected)
    tool_catalog: "ToolCatalog | None" = None
    tool_executor: "ToolExecutor | None" = None
    llm_router: "LLMRouter | None" = None


def create_context(
    user_id: str | None = None,
    tenancy_id: str | None = None,
    oci_profile: str = "DEFAULT",
    databases: list[str] | None = None,
    time_range: TimeRange | None = None,
    max_iterations: int = 12,
    metadata: dict[str, Any] | None = None,
) -> AgentContext:
    """Create a new agent context.

    Args:
        user_id: Optional user identifier
        tenancy_id: Optional OCI tenancy ID
        oci_profile: OCI CLI profile name
        databases: List of target database names
        time_range: Optional time range for queries
        max_iterations: Maximum agent iterations
        metadata: Additional context metadata

    Returns:
        Configured AgentContext
    """
    return AgentContext(
        session_id=f"sess_{uuid4().hex[:12]}",
        user_id=user_id,
        tenancy_id=tenancy_id,
        oci_profile=oci_profile,
        databases=databases or [],
        time_range=time_range,
        max_iterations=max_iterations,
        metadata=metadata or {},
    )


def increment_iteration(context: AgentContext) -> AgentContext:
    """Increment iteration count and return updated context."""
    context.iteration_count += 1
    return context


def has_reached_limit(context: AgentContext) -> bool:
    """Check if iteration limit has been reached."""
    return context.iteration_count >= context.max_iterations


def with_metadata(context: AgentContext, **kwargs: Any) -> AgentContext:
    """Return context with additional metadata."""
    context.metadata.update(kwargs)
    return context
