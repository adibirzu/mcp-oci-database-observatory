"""MySQL Database specialist agent."""

from typing import Any

from src.agents.base.capabilities import Capability
from src.agents.base.context import AgentContext
from src.core import get_logger
from src.observability import create_span

from .base import DatabaseAgent

logger = get_logger("agents.database.mysql")


# MySQL-specific SQL queries for diagnostics
MYSQL_HEALTH_CHECK = "SELECT 1"

MYSQL_PROCESS_LIST = """
SELECT id, user, host, db, command, time, state, info
FROM information_schema.processlist
WHERE command != 'Sleep'
ORDER BY time DESC
LIMIT 20
"""

MYSQL_InnoDB_STATUS = "SHOW ENGINE INNODB STATUS"

MYSQL_SLOW_QUERIES = """
SELECT digest_text, count_star, avg_timer_wait/1000000000 avg_ms,
       sum_rows_examined, sum_rows_sent
FROM performance_schema.events_statements_summary_by_digest
WHERE schema_name IS NOT NULL
ORDER BY avg_timer_wait DESC
LIMIT 10
"""

MYSQL_TABLE_STATS = """
SELECT table_schema, table_name, table_rows,
       ROUND(data_length/1024/1024, 2) data_mb,
       ROUND(index_length/1024/1024, 2) index_mb
FROM information_schema.tables
WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY data_length DESC
LIMIT 20
"""

MYSQL_REPLICATION_STATUS = "SHOW REPLICA STATUS"


class MySQLAgent(DatabaseAgent):
    """Specialist agent for MySQL Database."""

    name = "mysql_agent"
    description = "Expert in MySQL/MariaDB monitoring, tuning, and troubleshooting"
    mcp_server_id = "mysql-mcp"

    def __init__(self) -> None:
        """Initialize MySQL agent."""
        super().__init__()
        self.capabilities = [
            Capability.PERFORMANCE_ANALYSIS,
            Capability.SQL_EXECUTION,
            Capability.TROUBLESHOOTING,
            Capability.METRICS_COLLECTION,
        ]

    @property
    def database_type(self) -> str:
        """Get database type."""
        return "mysql"

    async def _check_health(self, context: AgentContext) -> dict[str, Any]:
        """Check MySQL database health."""
        with create_span(
            "agent.mysql.health_check",
            component="mysql_agent",
        ):
            # Quick ping
            ping_result = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": MYSQL_HEALTH_CHECK},
            )

            # Get active processes
            processes = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": MYSQL_PROCESS_LIST},
            )

            return {
                "success": True,
                "agent": self.name,
                "database_type": self.database_type,
                "health": {
                    "ping": ping_result.get("success", False),
                    "active_processes": processes.get("data"),
                },
            }

    async def _analyze_performance(
        self,
        query: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Analyze MySQL database performance."""
        with create_span(
            "agent.mysql.performance",
            component="mysql_agent",
        ):
            results = {}

            # Get slow queries
            slow_queries = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": MYSQL_SLOW_QUERIES},
            )
            results["slow_queries"] = slow_queries.get("data")

            # Get InnoDB status
            innodb = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": MYSQL_InnoDB_STATUS},
            )
            results["innodb_status"] = innodb.get("data")

            # Get table stats
            tables = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": MYSQL_TABLE_STATS},
            )
            results["table_stats"] = tables.get("data")

            # Check replication if relevant
            if "replication" in query.lower() or "replica" in query.lower():
                replication = await self._call_tool(
                    context,
                    self.mcp_server_id,
                    "execute-sql",
                    {"sql": MYSQL_REPLICATION_STATUS},
                )
                results["replication_status"] = replication.get("data")

            return {
                "success": True,
                "agent": self.name,
                "database_type": self.database_type,
                "performance": results,
            }

    async def _execute_sql(
        self,
        sql: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Execute SQL on MySQL."""
        with create_span(
            "agent.mysql.execute_sql",
            component="mysql_agent",
            attributes={"sql_length": len(sql)},
        ):
            result = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": sql},
            )

            return {
                "success": result.get("success", False),
                "agent": self.name,
                "database_type": self.database_type,
                "result": result.get("data"),
                "error": result.get("error"),
            }

    def _build_system_prompt(self) -> str:
        """Build MySQL-specific system prompt."""
        return """You are an expert MySQL Database administrator and performance specialist.

Your capabilities:
- Analyze query performance using Performance Schema
- Diagnose InnoDB buffer pool and lock contention
- Optimize SQL queries and indexes
- Troubleshoot replication issues
- Monitor table fragmentation and growth
- Analyze slow query logs

When analyzing performance:
1. Check performance_schema.events_statements_summary_by_digest for slow queries
2. Examine SHOW ENGINE INNODB STATUS for lock waits and deadlocks
3. Review processlist for long-running queries
4. Check table statistics and index usage
5. Consider buffer pool hit ratio and key buffer utilization

Available tools use the MySQL MCP server for SQL execution."""

    async def _establish_connection(
        self,
        connection_name: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """Connect to MySQL database."""
        result = await self._call_tool(
            context,
            self.mcp_server_id,
            "connect",
            {"connection": connection_name},
        )
        return {
            "success": result.get("success", False),
            "message": f"Connected to MySQL: {connection_name}" if result.get("success") else result.get("error"),
        }

    async def _close_connection(self, context: AgentContext) -> dict[str, Any]:
        """Disconnect from MySQL database."""
        result = await self._call_tool(
            context,
            self.mcp_server_id,
            "disconnect",
            {},
        )
        return {
            "success": result.get("success", True),
            "message": "Disconnected from MySQL database",
        }

    async def _call_tool(
        self,
        context: AgentContext,
        server_id: str,
        tool_name: str,
        params: dict,
    ) -> dict[str, Any]:
        """Call an MCP tool."""
        if not context.tool_executor:
            return {"success": False, "error": "No tool executor available"}

        namespaced_name = f"{server_id}__{tool_name}"
        result = await context.tool_executor.execute_direct(
            namespaced_name,
            params,
            context,
        )

        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "cached": result.cached,
        }
