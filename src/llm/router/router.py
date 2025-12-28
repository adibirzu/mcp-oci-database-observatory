"""Task-based LLM router."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.core import get_logger
from src.observability import create_span

from ..providers.base import LLMResponse, ToolDefinition
from ..providers.registry import ProviderRegistry

logger = get_logger("llm.router")


class TaskType(Enum):
    """Types of tasks for routing."""

    GENERAL = "general"
    CODE_ANALYSIS = "code_analysis"
    SQL_GENERATION = "sql_generation"
    TROUBLESHOOTING = "troubleshooting"
    DOCUMENTATION = "documentation"
    SECURITY_AUDIT = "security_audit"
    PERFORMANCE = "performance"


@dataclass
class RoutingRule:
    """Rule for routing tasks to providers."""

    task_type: TaskType
    provider: str
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096


class LLMRouter:
    """Routes LLM requests based on task type."""

    DEFAULT_RULES: dict[TaskType, RoutingRule] = {
        TaskType.GENERAL: RoutingRule(
            task_type=TaskType.GENERAL,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
        ),
        TaskType.CODE_ANALYSIS: RoutingRule(
            task_type=TaskType.CODE_ANALYSIS,
            provider="oracle_code_assist",
            temperature=0.3,
        ),
        TaskType.SQL_GENERATION: RoutingRule(
            task_type=TaskType.SQL_GENERATION,
            provider="oracle_code_assist",
            temperature=0.2,
            max_tokens=2048,
        ),
        TaskType.TROUBLESHOOTING: RoutingRule(
            task_type=TaskType.TROUBLESHOOTING,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            temperature=0.5,
        ),
        TaskType.DOCUMENTATION: RoutingRule(
            task_type=TaskType.DOCUMENTATION,
            provider="openai",
            model="gpt-4o",
            temperature=0.7,
        ),
        TaskType.SECURITY_AUDIT: RoutingRule(
            task_type=TaskType.SECURITY_AUDIT,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            temperature=0.3,
        ),
        TaskType.PERFORMANCE: RoutingRule(
            task_type=TaskType.PERFORMANCE,
            provider="oracle_code_assist",
            temperature=0.3,
        ),
    }

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        """Initialize router.

        Args:
            registry: Provider registry (created if not provided)
        """
        self.registry = registry or ProviderRegistry()
        self._rules = dict(self.DEFAULT_RULES)

    def set_rule(self, rule: RoutingRule) -> None:
        """Set a routing rule.

        Args:
            rule: Routing rule to set
        """
        self._rules[rule.task_type] = rule
        logger.debug(
            "Routing rule updated",
            task_type=rule.task_type.value,
            provider=rule.provider,
        )

    def get_rule(self, task_type: TaskType) -> RoutingRule:
        """Get the routing rule for a task type.

        Args:
            task_type: Task type

        Returns:
            Routing rule
        """
        return self._rules.get(task_type, self._rules[TaskType.GENERAL])

    def classify_task(self, query: str) -> TaskType:
        """Classify a query into a task type.

        Args:
            query: User query

        Returns:
            Detected task type
        """
        query_lower = query.lower()

        # SQL keywords
        sql_keywords = ["select", "insert", "update", "delete", "create", "alter", "drop", "sql"]
        if any(kw in query_lower for kw in sql_keywords):
            return TaskType.SQL_GENERATION

        # Code analysis
        code_keywords = ["analyze", "review", "code", "function", "class", "bug"]
        if any(kw in query_lower for kw in code_keywords):
            return TaskType.CODE_ANALYSIS

        # Troubleshooting
        trouble_keywords = ["error", "fail", "issue", "problem", "slow", "debug", "fix"]
        if any(kw in query_lower for kw in trouble_keywords):
            return TaskType.TROUBLESHOOTING

        # Performance
        perf_keywords = ["performance", "cpu", "memory", "latency", "throughput", "optimize"]
        if any(kw in query_lower for kw in perf_keywords):
            return TaskType.PERFORMANCE

        # Security
        security_keywords = ["security", "vulnerability", "audit", "permission", "access"]
        if any(kw in query_lower for kw in security_keywords):
            return TaskType.SECURITY_AUDIT

        # Documentation
        doc_keywords = ["document", "explain", "describe", "summarize", "readme"]
        if any(kw in query_lower for kw in doc_keywords):
            return TaskType.DOCUMENTATION

        return TaskType.GENERAL

    async def route(
        self,
        query: str,
        messages: list[dict[str, Any]],
        task_type: TaskType | None = None,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Route a request to the appropriate provider.

        Args:
            query: Original query (for classification)
            messages: Conversation messages
            task_type: Override task type (auto-detect if None)
            tools: Tool definitions
            **kwargs: Additional options

        Returns:
            LLM response
        """
        with create_span(
            "llm.router.route",
            component="llm_router",
        ):
            # Classify if not provided
            if task_type is None:
                task_type = self.classify_task(query)

            rule = self.get_rule(task_type)

            logger.info(
                "Routing request",
                task_type=task_type.value,
                provider=rule.provider,
                model=rule.model,
            )

            # Generate with fallback
            return await self.registry.generate_with_fallback(
                messages=messages,
                preferred_provider=rule.provider,
                model=rule.model,
                temperature=kwargs.get("temperature", rule.temperature),
                max_tokens=kwargs.get("max_tokens", rule.max_tokens),
                tools=tools,
                **kwargs,
            )
