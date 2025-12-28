"""Agent routing based on intent and capabilities."""

from typing import TYPE_CHECKING

from src.core import get_logger
from src.core.types import AgentTask, DatabaseType, IntentResult
from src.observability import create_span
from uuid import uuid4

if TYPE_CHECKING:
    from src.agents.base.agent import BaseAgent

logger = get_logger("agents.coordinator.router")


class AgentRouter:
    """Routes tasks to appropriate specialist agents."""

    def __init__(self) -> None:
        """Initialize router with empty agent registry."""
        self._agents: dict[str, "BaseAgent"] = {}

    def register_agent(self, agent: "BaseAgent") -> None:
        """Register a specialist agent.

        Args:
            agent: Agent instance to register
        """
        self._agents[agent.id] = agent
        logger.info("Agent registered", agent_id=agent.id)

    def get_agent(self, agent_id: str) -> "BaseAgent | None":
        """Get a registered agent by ID.

        Args:
            agent_id: Agent identifier

        Returns:
            Agent instance or None
        """
        return self._agents.get(agent_id)

    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return list(self._agents.keys())

    async def route(
        self,
        intent: IntentResult,
        parameters: dict | None = None,
    ) -> list[AgentTask]:
        """Route intent to appropriate agent tasks.

        Args:
            intent: Classified intent result
            parameters: Additional task parameters

        Returns:
            List of agent tasks to execute
        """
        with create_span(
            "agent.route",
            component="coordinator",
            attributes={
                "intent": intent.primary_intent.value,
                "database_type": (
                    intent.database_type
                    if isinstance(intent.database_type, str)
                    else intent.database_type.value
                ),
            },
        ):
            tasks: list[AgentTask] = []

            # Determine which agents to invoke
            target_agents = self._select_agents(intent)

            # Create tasks for each agent
            for i, agent_id in enumerate(target_agents):
                agent = self._agents.get(agent_id)
                if not agent:
                    logger.warning(
                        "Agent not registered",
                        agent_id=agent_id,
                    )
                    continue

                task = AgentTask(
                    id=f"task_{uuid4().hex[:8]}",
                    agent_type=agent.database_type,
                    intent=intent,
                    parameters=parameters or {},
                    priority=len(target_agents) - i,  # Higher priority first
                )
                tasks.append(task)

                logger.debug(
                    "Task created",
                    task_id=task.id,
                    agent=agent_id,
                    priority=task.priority,
                )

            logger.info(
                "Routing complete",
                tasks_created=len(tasks),
                agents=target_agents,
            )

            return tasks

    def _select_agents(self, intent: IntentResult) -> list[str]:
        """Select agents based on intent.

        Args:
            intent: Classified intent

        Returns:
            List of agent IDs to invoke
        """
        # If specific agents suggested, use those
        if intent.suggested_agents:
            available = [
                a for a in intent.suggested_agents
                if a in self._agents
            ]
            if available:
                return available

        # Otherwise, select by database type
        if isinstance(intent.database_type, DatabaseType):
            matching = [
                agent_id
                for agent_id, agent in self._agents.items()
                if agent.database_type == intent.database_type
            ]
            return matching

        # Multi or unknown - return all agents
        return list(self._agents.keys())

    def get_agent_for_capability(
        self,
        capability_id: str,
    ) -> "BaseAgent | None":
        """Find an agent with a specific capability.

        Args:
            capability_id: Capability to look for

        Returns:
            Agent with highest confidence for capability, or None
        """
        best_agent: "BaseAgent | None" = None
        best_score = 0.0

        for agent in self._agents.values():
            score = agent.get_capability_score(capability_id)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent
