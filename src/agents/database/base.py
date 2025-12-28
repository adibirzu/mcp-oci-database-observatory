"""Base database agent with common functionality."""

from abc import abstractmethod
from typing import Any

from src.agents.base.agent import BaseAgent
from src.agents.base.capabilities import Capability
from src.agents.base.context import AgentContext
from src.core import get_logger
from src.core.types import ToolCall
from src.observability import create_span

logger = get_logger("agents.database.base")


class DatabaseAgent(BaseAgent):
    """Abstract base class for database-specific agents."""

    # MCP server ID for this database type
    mcp_server_id: str = ""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize database agent."""
        super().__init__(**kwargs)
        self._connection_name: str | None = None

    @property
    @abstractmethod
    def database_type(self) -> str:
        """Get the database type (oracle, mysql, postgres)."""
        pass

    @property
    def otel_service_name(self) -> str:
        """Get OTEL service name for this agent."""
        return f"oci-obs-agent-{self.database_type}"

    async def process(
        self,
        query: str,
        context: AgentContext,
        parameters: dict | None = None,
    ) -> dict[str, Any]:
        """Process a database-related query.

        Args:
            query: User query
            context: Agent context
            parameters: Optional parameters

        Returns:
            Processing result
        """
        with create_span(
            f"agent.{self.database_type}.process",
            component=f"{self.database_type}_agent",
            attributes={"query": query[:100]},
        ):
            params = parameters or {}

            # Check for specific operations
            if self._is_health_check(query):
                return await self._check_health(context)

            if self._is_performance_query(query):
                return await self._analyze_performance(query, context, params)

            if self._is_sql_query(query):
                return await self._execute_sql(query, context, params)

            # General query - use LLM
            return await self._process_with_llm(query, context, params)

    def _is_health_check(self, query: str) -> bool:
        """Check if query is a health check request."""
        keywords = ["health", "ping", "status", "alive", "connection"]
        return any(kw in query.lower() for kw in keywords)

    def _is_performance_query(self, query: str) -> bool:
        """Check if query is about performance."""
        keywords = ["performance", "slow", "cpu", "memory", "wait", "blocking"]
        return any(kw in query.lower() for kw in keywords)

    def _is_sql_query(self, query: str) -> bool:
        """Check if query contains SQL to execute."""
        sql_keywords = ["select", "insert", "update", "delete", "create", "alter", "drop"]
        return any(query.lower().strip().startswith(kw) for kw in sql_keywords)

    @abstractmethod
    async def _check_health(self, context: AgentContext) -> dict[str, Any]:
        """Check database health.

        Args:
            context: Agent context

        Returns:
            Health check result
        """
        pass

    @abstractmethod
    async def _analyze_performance(
        self,
        query: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Analyze database performance.

        Args:
            query: Performance query
            context: Agent context
            params: Parameters

        Returns:
            Performance analysis
        """
        pass

    @abstractmethod
    async def _execute_sql(
        self,
        sql: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Execute SQL against the database.

        Args:
            sql: SQL statement
            context: Agent context
            params: Parameters

        Returns:
            SQL execution result
        """
        pass

    async def _process_with_llm(
        self,
        query: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Process query using LLM.

        Args:
            query: User query
            context: Agent context
            params: Parameters

        Returns:
            LLM response
        """
        # Build messages with database context
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {"role": "user", "content": query},
        ]

        # Get tools for this database
        tools = await self._get_available_tools(context)

        # Route to LLM
        response = await context.llm_router.route(
            query=query,
            messages=messages,
            tools=tools,
        )

        return {
            "success": True,
            "agent": self.name,
            "database_type": self.database_type,
            "response": response.content,
            "tool_calls": response.tool_calls,
        }

    @abstractmethod
    def _build_system_prompt(self) -> str:
        """Build system prompt for this database type."""
        pass

    async def _get_available_tools(self, context: AgentContext) -> list:
        """Get available MCP tools for this database.

        Args:
            context: Agent context

        Returns:
            List of tool definitions
        """
        if not context.tool_catalog:
            return []

        tools = context.tool_catalog.list_tools(server_id=self.mcp_server_id)
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]

    async def connect(
        self,
        connection_name: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """Connect to a database.

        Args:
            connection_name: Connection identifier
            context: Agent context

        Returns:
            Connection result
        """
        self._connection_name = connection_name
        return await self._establish_connection(connection_name, context)

    @abstractmethod
    async def _establish_connection(
        self,
        connection_name: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """Establish database connection.

        Args:
            connection_name: Connection identifier
            context: Agent context

        Returns:
            Connection result
        """
        pass

    async def disconnect(self, context: AgentContext) -> dict[str, Any]:
        """Disconnect from database.

        Args:
            context: Agent context

        Returns:
            Disconnect result
        """
        if not self._connection_name:
            return {"success": True, "message": "No active connection"}

        result = await self._close_connection(context)
        self._connection_name = None
        return result

    @abstractmethod
    async def _close_connection(self, context: AgentContext) -> dict[str, Any]:
        """Close database connection.

        Args:
            context: Agent context

        Returns:
            Close result
        """
        pass
