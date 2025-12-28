"""PostgreSQL Database specialist agent."""

from typing import Any

from src.agents.base.capabilities import Capability
from src.agents.base.context import AgentContext
from src.core import get_logger
from src.observability import create_span

from .base import DatabaseAgent

logger = get_logger("agents.database.postgres")


# PostgreSQL-specific SQL queries for diagnostics
PG_HEALTH_CHECK = "SELECT 1"

PG_ACTIVE_QUERIES = """
SELECT pid, usename, datname, state, query_start,
       now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle' AND pid != pg_backend_pid()
ORDER BY duration DESC
LIMIT 20
"""

PG_BLOCKING_QUERIES = """
SELECT blocked.pid AS blocked_pid,
       blocked.query AS blocked_query,
       blocking.pid AS blocking_pid,
       blocking.query AS blocking_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked ON blocked.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking ON blocking.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted
"""

PG_TABLE_STATS = """
SELECT schemaname, relname, n_live_tup, n_dead_tup,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20
"""

PG_INDEX_USAGE = """
SELECT schemaname, relname, indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan
LIMIT 20
"""

PG_CACHE_HIT_RATIO = """
SELECT
    sum(heap_blks_read) AS heap_read,
    sum(heap_blks_hit) AS heap_hit,
    CASE WHEN sum(heap_blks_read) + sum(heap_blks_hit) > 0
         THEN round(sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))::numeric * 100, 2)
         ELSE 0
    END AS ratio
FROM pg_statio_user_tables
"""


class PostgresAgent(DatabaseAgent):
    """Specialist agent for PostgreSQL Database."""

    name = "postgres_agent"
    description = "Expert in PostgreSQL monitoring, tuning, and troubleshooting"
    mcp_server_id = "postgres-mcp"

    def __init__(self) -> None:
        """Initialize PostgreSQL agent."""
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
        return "postgres"

    async def _check_health(self, context: AgentContext) -> dict[str, Any]:
        """Check PostgreSQL database health."""
        with create_span(
            "agent.postgres.health_check",
            component="postgres_agent",
        ):
            # Quick ping
            ping_result = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_HEALTH_CHECK},
            )

            # Get active queries
            active = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_ACTIVE_QUERIES},
            )

            # Get cache hit ratio
            cache = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_CACHE_HIT_RATIO},
            )

            return {
                "success": True,
                "agent": self.name,
                "database_type": self.database_type,
                "health": {
                    "ping": ping_result.get("success", False),
                    "active_queries": active.get("data"),
                    "cache_hit_ratio": cache.get("data"),
                },
            }

    async def _analyze_performance(
        self,
        query: str,
        context: AgentContext,
        params: dict,
    ) -> dict[str, Any]:
        """Analyze PostgreSQL database performance."""
        with create_span(
            "agent.postgres.performance",
            component="postgres_agent",
        ):
            results = {}

            # Get active queries
            active = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_ACTIVE_QUERIES},
            )
            results["active_queries"] = active.get("data")

            # Check for blocking
            blocking = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_BLOCKING_QUERIES},
            )
            results["blocking_queries"] = blocking.get("data")

            # Get table stats (vacuum/analyze)
            tables = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_TABLE_STATS},
            )
            results["table_stats"] = tables.get("data")

            # Get index usage
            indexes = await self._call_tool(
                context,
                self.mcp_server_id,
                "execute-sql",
                {"sql": PG_INDEX_USAGE},
            )
            results["index_usage"] = indexes.get("data")

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
        """Execute SQL on PostgreSQL."""
        with create_span(
            "agent.postgres.execute_sql",
            component="postgres_agent",
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
        """Build PostgreSQL-specific system prompt."""
        return """You are an expert PostgreSQL Database administrator and performance specialist.

Your capabilities:
- Analyze query performance using pg_stat_statements
- Diagnose lock contention and blocking queries
- Optimize SQL queries and indexes
- Troubleshoot autovacuum and bloat issues
- Monitor table and index statistics
- Analyze PostgreSQL logs

When analyzing performance:
1. Check pg_stat_activity for active and blocked queries
2. Examine pg_stat_user_tables for dead tuples and vacuum status
3. Review pg_stat_user_indexes for unused indexes
4. Check cache hit ratio via pg_statio_user_tables
5. Consider connection pooling and shared_buffers settings

Available tools use the PostgreSQL MCP server for SQL execution."""

    async def _establish_connection(
        self,
        connection_name: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """Connect to PostgreSQL database."""
        result = await self._call_tool(
            context,
            self.mcp_server_id,
            "connect",
            {"connection": connection_name},
        )
        return {
            "success": result.get("success", False),
            "message": f"Connected to PostgreSQL: {connection_name}" if result.get("success") else result.get("error"),
        }

    async def _close_connection(self, context: AgentContext) -> dict[str, Any]:
        """Disconnect from PostgreSQL database."""
        result = await self._call_tool(
            context,
            self.mcp_server_id,
            "disconnect",
            {},
        )
        return {
            "success": result.get("success", True),
            "message": "Disconnected from PostgreSQL database",
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
