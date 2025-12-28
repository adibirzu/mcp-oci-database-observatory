"""Base agent abstract class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core import get_logger
from src.core.types import AgentResult, AgentTask, DatabaseType, DiagnosticFinding
from src.observability import create_span, record_agent_execution

from .capabilities import AgentCapability
from .context import AgentContext

if TYPE_CHECKING:
    from src.mcp.executor.executor import ToolExecutor
    from src.llm.router.router import LLMRouter

logger = get_logger("agents.base")


@dataclass
class Runbook:
    """A diagnostic runbook definition."""

    id: str
    name: str
    description: str
    steps: list["RunbookStep"] = field(default_factory=list)


@dataclass
class RunbookStep:
    """A single step in a runbook."""

    id: str
    name: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all specialist agents.

    Provides common infrastructure for:
    - Tool execution via MCP
    - LLM-assisted analysis
    - Runbook execution
    - Result aggregation
    """

    def __init__(
        self,
        executor: "ToolExecutor",
        llm_router: "LLMRouter",
    ) -> None:
        """Initialize agent with dependencies.

        Args:
            executor: MCP tool executor
            llm_router: LLM provider router
        """
        self.executor = executor
        self.llm_router = llm_router
        self._logger = get_logger(f"agents.{self.id}")

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique agent identifier."""
        ...

    @property
    @abstractmethod
    def database_type(self) -> DatabaseType:
        """Database type this agent specializes in."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[AgentCapability]:
        """List of capabilities this agent provides."""
        ...

    @property
    @abstractmethod
    def otel_service_name(self) -> str:
        """OTEL service name for this agent."""
        ...

    @abstractmethod
    async def execute(
        self,
        task: AgentTask,
        context: AgentContext,
    ) -> AgentResult:
        """Execute a task and return results.

        Args:
            task: Task to execute
            context: Execution context

        Returns:
            Agent execution result
        """
        ...

    @abstractmethod
    def get_runbook(self, task_type: str) -> Runbook | None:
        """Get runbook for a specific task type.

        Args:
            task_type: Type of diagnostic task

        Returns:
            Runbook if available, None otherwise
        """
        ...

    async def execute_runbook(
        self,
        runbook: Runbook,
        context: AgentContext,
        analyze_fn: Any | None = None,
    ) -> tuple[list[DiagnosticFinding], list[str]]:
        """Execute a runbook and collect findings.

        Args:
            runbook: Runbook to execute
            context: Execution context
            analyze_fn: Optional function to analyze step results

        Returns:
            Tuple of (findings, tools_used)
        """
        findings: list[DiagnosticFinding] = []
        tools_used: list[str] = []

        with create_span(
            f"agent.runbook.{runbook.id}",
            component=self.id,
            attributes={"runbook.name": runbook.name},
        ):
            for step in runbook.steps:
                self._logger.debug(
                    "Executing runbook step",
                    step=step.id,
                    tool=step.tool,
                )

                try:
                    result = await self.executor.execute_direct(
                        step.tool,
                        step.params,
                        context,
                    )
                    tools_used.append(step.tool)

                    if result.success and analyze_fn:
                        step_findings = analyze_fn(step.id, result.data)
                        findings.extend(step_findings)

                except Exception as e:
                    self._logger.error(
                        "Runbook step failed",
                        step=step.id,
                        error=str(e),
                    )

        return findings, tools_used

    def _create_result(
        self,
        task_id: str,
        success: bool,
        findings: list[DiagnosticFinding],
        tools_used: list[str],
        start_time_ms: int,
    ) -> AgentResult:
        """Create a standardized agent result.

        Args:
            task_id: Task identifier
            success: Whether execution succeeded
            findings: Diagnostic findings
            tools_used: Tools that were invoked
            start_time_ms: Start timestamp

        Returns:
            Structured agent result
        """
        import time

        duration_ms = int((time.time() * 1000) - start_time_ms)

        # Record metrics
        record_agent_execution(
            agent_type=self.database_type.value,
            task_id=task_id,
            duration_ms=duration_ms,
            tools_used=tools_used,
            findings_count=len(findings),
            success=success,
        )

        return AgentResult(
            task_id=task_id,
            agent_type=self.database_type,
            success=success,
            findings=findings,
            recommendations=self._generate_recommendations(findings),
            execution_time_ms=duration_ms,
            tools_used=tools_used,
        )

    def _generate_recommendations(
        self,
        findings: list[DiagnosticFinding],
    ) -> list[str]:
        """Generate recommendations from findings.

        Args:
            findings: List of diagnostic findings

        Returns:
            List of recommendations
        """
        return [f.recommendation for f in findings if f.recommendation]

    def has_capability(self, capability_id: str) -> bool:
        """Check if agent has a specific capability."""
        return any(c.id == capability_id for c in self.capabilities)

    def get_capability_score(self, capability_id: str) -> float:
        """Get confidence score for a capability."""
        for cap in self.capabilities:
            if cap.id == capability_id:
                return cap.confidence
        return 0.0
