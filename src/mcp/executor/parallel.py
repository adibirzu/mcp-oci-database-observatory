"""Parallel MCP tool execution."""

import asyncio
from typing import TYPE_CHECKING

from src.core import get_logger
from src.core.types import ToolCall, ToolResult
from src.observability import create_span

if TYPE_CHECKING:
    from src.agents.base.context import AgentContext

    from .executor import ToolExecutor

logger = get_logger("mcp.executor.parallel")


class ParallelExecutor:
    """Executes multiple tools in parallel with dependency handling."""

    def __init__(self, executor: "ToolExecutor") -> None:
        """Initialize parallel executor.

        Args:
            executor: Base tool executor
        """
        self.executor = executor

    async def execute_parallel(
        self,
        tool_calls: list[ToolCall],
        context: "AgentContext",
    ) -> dict[str, ToolResult]:
        """Execute multiple tools in parallel.

        Args:
            tool_calls: List of tool calls
            context: Agent context

        Returns:
            Map of tool names to results
        """
        with create_span(
            "mcp.tools.parallel",
            component="mcp_executor",
            attributes={"tool_count": len(tool_calls)},
        ):
            # Group by dependencies
            groups = self._group_by_dependency(tool_calls)
            results: dict[str, ToolResult] = {}

            for group in groups:
                logger.debug(
                    "Executing tool group",
                    group_size=len(group),
                )

                # Execute group in parallel
                group_results = await asyncio.gather(
                    *[
                        self._execute_tool(call, context)
                        for call in group
                    ],
                    return_exceptions=True,
                )

                # Collect results
                for call, result in zip(group, group_results):
                    if isinstance(result, Exception):
                        results[call.tool] = ToolResult(
                            success=False,
                            error=str(result),
                            execution_time_ms=0,
                            cached=False,
                        )
                    else:
                        results[call.tool] = result

            logger.info(
                "Parallel execution complete",
                total_tools=len(tool_calls),
                successful=len([r for r in results.values() if r.success]),
            )

            return results

    async def _execute_tool(
        self,
        call: ToolCall,
        context: "AgentContext",
    ) -> ToolResult:
        """Execute a single tool call.

        Args:
            call: Tool call specification
            context: Agent context

        Returns:
            Tool result
        """
        return await self.executor.execute_direct(
            call.tool,
            call.params,
            context,
        )

    def _group_by_dependency(
        self,
        calls: list[ToolCall],
    ) -> list[list[ToolCall]]:
        """Group tool calls by dependencies.

        Tools without dependencies are in the first group.
        Tools with dependencies wait for their dependencies.

        Args:
            calls: All tool calls

        Returns:
            List of execution groups
        """
        groups: list[list[ToolCall]] = []
        resolved: set[str] = set()
        remaining = list(calls)

        while remaining:
            # Find calls with resolved dependencies
            ready = [
                call for call in remaining
                if not call.dependencies or all(
                    dep in resolved for dep in call.dependencies
                )
            ]

            if not ready:
                # Circular dependency - execute remaining
                logger.warning(
                    "Circular dependency detected",
                    remaining=len(remaining),
                )
                groups.append(remaining)
                break

            groups.append(ready)

            # Mark as resolved
            for call in ready:
                resolved.add(call.tool)

            # Remove from remaining
            remaining = [c for c in remaining if c not in ready]

        return groups
