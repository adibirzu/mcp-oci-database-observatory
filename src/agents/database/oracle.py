"""Oracle Database specialist agent."""

from typing import Any

from src.agents.base.capabilities import Capability
from src.agents.base.context import AgentContext
from src.core import get_logger
from src.core.types import ToolCall
from src.observability import create_span

from .base import DatabaseAgent

logger = get_logger("agents.database.oracle")


# Oracle-specific SQL queries for diagnostics
ORACLE_HEALTH_CHECK = "SELECT 1 FROM DUAL"

ORACLE_TOP_SQL = """
SELECT sql_id, executions, elapsed_time/1000000 elapsed_sec,
       cpu_time/1000000 cpu_sec, buffer_gets, disk_reads
FROM v$sql
WHERE elapsed_time > 0
ORDER BY elapsed_time DESC
FETCH FIRST 10 ROWS ONLY
"""

ORACLE_WAIT_EVENTS = """
SELECT event, total_waits, time_waited_micro/1000000 time_sec,
       average_wait/1000 avg_wait_ms
FROM v$system_event
WHERE wait_class != 'Idle'
ORDER BY time_waited_micro DESC
FETCH FIRST 10 ROWS ONLY
"""

ORACLE_SESSION_STATS = """
SELECT status, COUNT(*) session_count
FROM v$session
WHERE type = 'USER'
GROUP BY status
"""

ORACLE_TABLESPACE_USAGE = """
SELECT tablespace_name,
       ROUND(used_space * 8192 / 1024 / 1024) used_mb,
       ROUND(tablespace_size * 8192 / 1024 / 1024) total_mb,
       ROUND((used_space / tablespace_size) * 100, 2) pct_used
FROM dba_tablespace_usage_metrics
ORDER BY pct_used DESC
"""


class OracleAgent(DatabaseAgent):
    """Specialist agent for Oracle Database."""

    name = "oracle_agent"
    description = "Expert in Oracle Database monitoring, tuning, and troubleshooting"
    mcp_server_id = "sqlcl"

    def __init__(self) -> None:
        """Initialize Oracle agent."""
        super().__init__()
        self.capabilities = [
            Capability.PERFORMANCE_ANALYSIS,
            Capability.SQL_EXECUTION,
            Capability.TROUBLESHOOTING,
            Capability.METRICS_COLLECTION,
            Capability.LOG_ANALYSIS,
        ]

    @property
    def database_type(self) -> str:
        """Get database type."""
        return "oracle"

    async def _check_health(self, context: AgentContext) -> dict[str, Any]:
        """Check Oracle database health."""
        with create_span(
            "agent.oracle.health_check",
            component="oracle_agent",
        ):
            # Use OPSI for comprehensive health
            opsi_result = await self._call_tool(
                context,
                "oci-opsi",
                "get_fleet_summary",
                {},
            )

            # Quick ping via SQLcl
            sqlcl_result = await self._call_tool(
                context,
                "sqlcl",
                "run-sql",
                {"sql": ORACLE_HEALTH_CHECK},
            )

            return {
                "success": True,
                "agent": self.name,
                "database_type": self.database_type,
                "health": {
                    "ping": sqlcl_result.get("success", False),
                    "fleet_summary": opsi_result.get("data"),
                },
            }

    async def _analyze_performance(
        self,
        query: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Analyze Oracle database performance."""
        with create_span(
            "agent.oracle.performance",
            component="oracle_agent",
        ):
            results = {}

            # Get top SQL
            top_sql = await self._call_tool(
                context,
                "sqlcl",
                "run-sql",
                {"sql": ORACLE_TOP_SQL},
            )
            results["top_sql"] = top_sql.get("data")

            # Get wait events
            wait_events = await self._call_tool(
                context,
                "sqlcl",
                "run-sql",
                {"sql": ORACLE_WAIT_EVENTS},
            )
            results["wait_events"] = wait_events.get("data")

            # Get session stats
            sessions = await self._call_tool(
                context,
                "sqlcl",
                "run-sql",
                {"sql": ORACLE_SESSION_STATS},
            )
            results["sessions"] = sessions.get("data")

            # Use OPSI for CPU analysis
            if "cpu" in query.lower():
                cpu_analysis = await self._call_tool(
                    context,
                    "oci-opsi",
                    "skill_analyze_cpu_usage",
                    {},
                )
                results["cpu_analysis"] = cpu_analysis.get("data")

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
        """Execute SQL via SQLcl."""
        with create_span(
            "agent.oracle.execute_sql",
            component="oracle_agent",
            attributes={"sql_length": len(sql)},
        ):
            result = await self._call_tool(
                context,
                "sqlcl",
                "run-sql",
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
        """Build Oracle-specific system prompt."""
        return """You are an expert Oracle Database administrator and performance specialist.

Your capabilities:
- Analyze SQL performance using V$ views and AWR/ASH data
- Diagnose wait events and blocking sessions
- Optimize SQL queries and execution plans
- Troubleshoot RAC, Data Guard, and ASM issues
- Monitor tablespace usage and storage
- Analyze alert logs and trace files

When analyzing performance:
1. Start with V$SYSTEM_EVENT for wait class overview
2. Check V$SQL for top SQL by elapsed time
3. Examine V$SESSION for active sessions
4. Use AWR/ASH for historical analysis
5. Consider resource manager and parallel query impacts

Available tools use the SQLcl MCP server for direct SQL execution
and OCI OPSI for Operations Insights analytics."""

    async def _establish_connection(
        self,
        connection_name: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """Connect to Oracle database via SQLcl."""
        result = await self._call_tool(
            context,
            "sqlcl",
            "connect",
            {"connection": connection_name},
        )
        return {
            "success": result.get("success", False),
            "message": f"Connected to {connection_name}" if result.get("success") else result.get("error"),
        }

    async def _close_connection(self, context: AgentContext) -> dict[str, Any]:
        """Disconnect from Oracle database."""
        result = await self._call_tool(
            context,
            "sqlcl",
            "disconnect",
            {},
        )
        return {
            "success": result.get("success", True),
            "message": "Disconnected from Oracle database",
        }

    async def _call_tool(
        self,
        context: AgentContext,
        server_id: str,
        tool_name: str,
        params: dict,
    ) -> dict[str, Any]:
        """Call an MCP tool.

        Args:
            context: Agent context
            server_id: MCP server ID
            tool_name: Tool name
            params: Tool parameters

        Returns:
            Tool result
        """
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
