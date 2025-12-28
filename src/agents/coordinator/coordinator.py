"""Main coordinator agent for multi-agent orchestration."""

import asyncio
import time
from typing import TYPE_CHECKING

from src.core import get_logger
from src.core.types import AgentResult
from src.observability import create_span, record_query_processing

from ..base.context import AgentContext
from .aggregator import ResponseAggregator
from .intent import IntentClassifier
from .router import AgentRouter

if TYPE_CHECKING:
    from src.agents.base.agent import BaseAgent

logger = get_logger("agents.coordinator")


class CoordinatorAgent:
    """Orchestrates multi-agent query processing.

    Responsibilities:
    - Classify user intent
    - Route to appropriate specialist agents
    - Execute agents in parallel where possible
    - Aggregate and synthesize final response
    """

    name = "coordinator"
    otel_service_name = "oci-obs-coordinator"

    def __init__(self) -> None:
        """Initialize coordinator with sub-components."""
        self.classifier = IntentClassifier()
        self.router = AgentRouter()
        self.aggregator = ResponseAggregator()

    def register_agent(self, agent: "BaseAgent") -> None:
        """Register a specialist agent.

        Args:
            agent: Agent to register
        """
        self.router.register_agent(agent)

    async def process_query(
        self,
        query: str,
        context: AgentContext,
        parameters: dict | None = None,
    ) -> dict:
        """Process a user query through the agent pipeline.

        Args:
            query: User's natural language query
            context: Execution context
            parameters: Additional parameters

        Returns:
            Aggregated response from all agents
        """
        start_time = time.time()

        with create_span(
            "agent.query",
            component="coordinator",
            attributes={"query.length": len(query)},
        ):
            # Step 1: Classify intent
            logger.info("Processing query", query=query[:100])
            intent = await self.classifier.classify(query)

            # Step 2: Route to agents
            tasks = await self.router.route(intent, parameters)

            if not tasks:
                logger.warning("No agents available for query")
                return {
                    "success": False,
                    "error": "No agents available to handle this query",
                    "intent": {
                        "type": intent.primary_intent.value,
                        "database": (
                            intent.database_type
                            if isinstance(intent.database_type, str)
                            else intent.database_type.value
                        ),
                        "confidence": intent.confidence,
                    },
                }

            # Step 3: Execute agents in parallel
            results = await self._execute_agents(tasks, context)

            # Step 4: Aggregate results
            response = await self.aggregator.aggregate(results)

            # Record metrics
            duration_ms = int((time.time() - start_time) * 1000)
            record_query_processing(
                query=query,
                intent=intent.primary_intent.value,
                database_type=(
                    intent.database_type
                    if isinstance(intent.database_type, str)
                    else intent.database_type.value
                ),
                agents_invoked=[t.agent_type.value for t in tasks],
                total_duration_ms=duration_ms,
            )

            # Add intent info to response
            response["intent"] = {
                "type": intent.primary_intent.value,
                "database": (
                    intent.database_type
                    if isinstance(intent.database_type, str)
                    else intent.database_type.value
                ),
                "confidence": intent.confidence,
            }

            logger.info(
                "Query processing complete",
                duration_ms=duration_ms,
                agents=len(results),
                findings=len(response.get("findings", [])),
            )

            return response

    async def _execute_agents(
        self,
        tasks: list,
        context: AgentContext,
    ) -> list[AgentResult]:
        """Execute agent tasks in parallel.

        Args:
            tasks: List of agent tasks
            context: Execution context

        Returns:
            List of agent results
        """
        with create_span(
            "agent.execute_all",
            component="coordinator",
            attributes={"task_count": len(tasks)},
        ):
            async def execute_task(task) -> AgentResult | None:
                agent = self.router.get_agent(task.agent_type.value)
                if not agent:
                    logger.error(
                        "Agent not found for task",
                        task_id=task.id,
                        agent_type=task.agent_type.value,
                    )
                    return None

                try:
                    return await agent.execute(task, context)
                except Exception as e:
                    logger.error(
                        "Agent execution failed",
                        task_id=task.id,
                        agent=task.agent_type.value,
                        error=str(e),
                    )
                    # Return empty result on failure
                    return AgentResult(
                        task_id=task.id,
                        agent_type=task.agent_type,
                        success=False,
                        findings=[],
                        recommendations=[],
                        execution_time_ms=0,
                        tools_used=[],
                    )

            # Execute all tasks concurrently
            results = await asyncio.gather(
                *[execute_task(task) for task in tasks],
                return_exceptions=False,
            )

            # Filter out None results
            return [r for r in results if r is not None]

    def list_agents(self) -> list[dict]:
        """List all registered agents with their capabilities.

        Returns:
            List of agent info dictionaries
        """
        agents = []
        for agent_id in self.router.list_agents():
            agent = self.router.get_agent(agent_id)
            if agent:
                agents.append({
                    "id": agent.id,
                    "database_type": agent.database_type.value,
                    "capabilities": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "confidence": c.confidence,
                        }
                        for c in agent.capabilities
                    ],
                })
        return agents
