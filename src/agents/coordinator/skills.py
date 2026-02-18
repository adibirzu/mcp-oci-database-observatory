"""OPSI workflow skills for coordinator orchestration.

This module provides high-level skills that orchestrate multiple OPSI tool calls
into meaningful workflows for common DBA use cases.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.agents.base.context import AgentContext
from src.agents.oracle.runbooks import load_runbook
from src.core import get_logger
from src.observability import create_span

logger = get_logger("agents.coordinator.skills")


class SkillType(str, Enum):
    """Types of coordinator skills."""

    # OPSI-based skills
    FLEET_HEALTH = "fleet_health"
    PERFORMANCE_TROUBLESHOOT = "performance_troubleshoot"
    COST_OPTIMIZATION = "cost_optimization"
    SQL_DEEP_DIVE = "sql_deep_dive"
    CAPACITY_PLANNING = "capacity_planning"
    DATABASE_HEALTH = "database_health"

    # Database Management API skills
    AWR_ANALYSIS = "awr_analysis"
    SQL_TUNING = "sql_tuning"
    ALERT_ANALYSIS = "alert_analysis"

    # Runbook-based diagnostic skills
    BLOCKING_SESSIONS = "blocking_sessions"
    LONG_OPERATIONS = "long_operations"
    PARALLELISM_ANALYSIS = "parallelism_analysis"
    FULL_TABLE_SCANS = "full_table_scans"
    SQL_MONITOR = "sql_monitor"


@dataclass
class SkillResult:
    """Result from skill execution."""

    skill: SkillType
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    error: str | None = None


class OPSISkills:
    """OPSI workflow skills for database observability.

    Provides high-level skills that orchestrate multiple OPSI tool calls
    to deliver comprehensive analysis for common DBA scenarios.
    """

    # MCP server IDs
    OPSI_SERVER = "oci-opsi"
    DBMGMT_SERVER = "database-observatory"
    SQLCL_SERVER = "sqlcl"

    def __init__(self) -> None:
        """Initialize OPSI skills."""
        self._skill_handlers = {
            # OPSI-based skills
            SkillType.FLEET_HEALTH: self._fleet_health_skill,
            SkillType.PERFORMANCE_TROUBLESHOOT: self._performance_troubleshoot_skill,
            SkillType.COST_OPTIMIZATION: self._cost_optimization_skill,
            SkillType.SQL_DEEP_DIVE: self._sql_deep_dive_skill,
            SkillType.CAPACITY_PLANNING: self._capacity_planning_skill,
            SkillType.DATABASE_HEALTH: self._database_health_skill,
            # Database Management API skills
            SkillType.AWR_ANALYSIS: self._awr_analysis_skill,
            SkillType.SQL_TUNING: self._sql_tuning_skill,
            SkillType.ALERT_ANALYSIS: self._alert_analysis_skill,
            # Runbook-based diagnostic skills
            SkillType.BLOCKING_SESSIONS: self._blocking_sessions_skill,
            SkillType.LONG_OPERATIONS: self._long_operations_skill,
            SkillType.PARALLELISM_ANALYSIS: self._parallelism_analysis_skill,
            SkillType.FULL_TABLE_SCANS: self._full_table_scans_skill,
            SkillType.SQL_MONITOR: self._sql_monitor_skill,
        }

    async def execute(
        self,
        skill_type: SkillType,
        context: AgentContext,
        params: dict[str, Any] | None = None,
    ) -> SkillResult:
        """Execute a skill workflow.

        Args:
            skill_type: Type of skill to execute
            context: Agent execution context
            params: Optional skill parameters

        Returns:
            SkillResult with findings and recommendations
        """
        handler = self._skill_handlers.get(skill_type)
        if not handler:
            return SkillResult(
                skill=skill_type,
                success=False,
                error=f"Unknown skill type: {skill_type}",
            )

        try:
            return await handler(context, params or {})
        except Exception as e:
            logger.error("Skill execution failed", skill=skill_type.value, error=str(e))
            return SkillResult(
                skill=skill_type,
                success=False,
                error=str(e),
            )

    async def _call_tool(
        self,
        context: AgentContext,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an OPSI MCP tool.

        Args:
            context: Agent context with tool executor
            tool_name: OPSI tool name (without server prefix)
            params: Tool parameters

        Returns:
            Tool execution result
        """
        if not context.tool_executor:
            return {"success": False, "error": "No tool executor available"}

        namespaced_name = f"{self.OPSI_SERVER}__{tool_name}"
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

    async def _call_dbmgmt_tool(
        self,
        context: AgentContext,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a Database Management MCP tool.

        Args:
            context: Agent context with tool executor
            tool_name: DB Management tool name (without server prefix)
            params: Tool parameters

        Returns:
            Tool execution result
        """
        if not context.tool_executor:
            return {"success": False, "error": "No tool executor available"}

        namespaced_name = f"{self.DBMGMT_SERVER}__{tool_name}"
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

    async def _execute_runbook_sql(
        self,
        context: AgentContext,
        sql: str,
        connection_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute SQL from a runbook via SQLcl.

        Args:
            context: Agent context with tool executor
            sql: SQL query to execute
            connection_name: Optional SQLcl connection name

        Returns:
            SQL execution result with success, data, error
        """
        if not context.tool_executor:
            return {"success": False, "error": "No tool executor available"}

        params = {"sql": sql}
        if connection_name:
            params["connection"] = connection_name

        namespaced_name = f"{self.SQLCL_SERVER}__run-sql"
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

    async def _fleet_health_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Assess overall database fleet health.

        Workflow:
        1. Get fleet summary for overview
        2. Check for cost optimization opportunities
        3. Analyze resource utilization trends

        Args:
            context: Agent context
            params: Optional parameters (compartment_id, etc.)

        Returns:
            SkillResult with fleet health assessment
        """
        with create_span(
            "skill.fleet_health",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            # Step 1: Fleet summary
            fleet = await self._call_tool(context, "get_fleet_summary", params)
            if fleet.get("success"):
                data["fleet_summary"] = fleet.get("data")
                fleet_data = fleet.get("data", {})

                # Extract findings from fleet data
                if isinstance(fleet_data, dict):
                    db_count = fleet_data.get("database_count", 0)
                    findings.append(f"Fleet contains {db_count} monitored databases")

            # Step 2: Cost opportunities
            cost = await self._call_tool(context, "find_cost_opportunities", params)
            if cost.get("success"):
                data["cost_opportunities"] = cost.get("data")
                cost_data = cost.get("data", {})

                if isinstance(cost_data, dict):
                    savings = cost_data.get("total_savings", 0)
                    if savings > 0:
                        findings.append(f"Potential cost savings: ${savings:.2f}/month")
                        recommendations.append(
                            "Review rightsizing recommendations for cost optimization"
                        )

            # Step 3: Resource utilization
            resources = await self._call_tool(
                context,
                "get_resource_utilization",
                params,
            )
            if resources.get("success"):
                data["resource_utilization"] = resources.get("data")

            return SkillResult(
                skill=SkillType.FLEET_HEALTH,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _performance_troubleshoot_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Troubleshoot database performance issues.

        Workflow:
        1. Get SQL statistics for top resource consumers
        2. Check SQL insights for degradation
        3. Get ADDM recommendations
        4. Analyze CPU/memory if database_id provided

        Args:
            context: Agent context
            params: Should include database_id for specific DB analysis

        Returns:
            SkillResult with troubleshooting findings
        """
        with create_span(
            "skill.performance_troubleshoot",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}
            database_id = params.get("database_id")

            # Step 1: SQL Statistics
            sql_stats = await self._call_tool(
                context,
                "get_sql_statistics",
                params,
            )
            if sql_stats.get("success"):
                data["sql_statistics"] = sql_stats.get("data")
                stats_data = sql_stats.get("data", {})

                if isinstance(stats_data, dict):
                    top_sql_count = len(stats_data.get("top_sql", []))
                    if top_sql_count > 0:
                        findings.append(
                            f"Identified {top_sql_count} top SQL statements by resource usage"
                        )

            # Step 2: SQL Insights for degradation
            insights = await self._call_tool(context, "get_sql_insights", params)
            if insights.get("success"):
                data["sql_insights"] = insights.get("data")
                insights_data = insights.get("data", {})

                if isinstance(insights_data, dict):
                    degraded = insights_data.get("degraded_sql", [])
                    variants = insights_data.get("plan_variants", [])

                    if degraded:
                        findings.append(f"Found {len(degraded)} degraded SQL statements")
                        recommendations.append(
                            "Review degraded SQL for recent changes or statistics updates"
                        )

                    if variants:
                        findings.append(
                            f"Found {len(variants)} SQL with plan instability"
                        )
                        recommendations.append(
                            "Consider SQL plan baselines for unstable plans"
                        )

            # Step 3: ADDM Recommendations
            addm = await self._call_tool(context, "get_addm_recommendations", params)
            if addm.get("success"):
                data["addm_recommendations"] = addm.get("data")
                addm_data = addm.get("data", {})

                if isinstance(addm_data, dict):
                    recs = addm_data.get("recommendations", [])
                    for rec in recs[:3]:  # Top 3 recommendations
                        if isinstance(rec, dict):
                            recommendations.append(rec.get("finding", str(rec)))

            # Step 4: CPU/Memory analysis if database_id provided
            if database_id:
                cpu = await self._call_tool(context, "analyze_cpu", params)
                if cpu.get("success"):
                    data["cpu_analysis"] = cpu.get("data")
                    cpu_data = cpu.get("data", {})

                    if isinstance(cpu_data, dict):
                        avg_cpu = cpu_data.get("average_utilization", 0)
                        if avg_cpu > 80:
                            findings.append(f"High CPU utilization: {avg_cpu:.1f}%")
                            recommendations.append(
                                "Investigate high CPU consumers in SQL statistics"
                            )

                memory = await self._call_tool(context, "analyze_memory", params)
                if memory.get("success"):
                    data["memory_analysis"] = memory.get("data")

            return SkillResult(
                skill=SkillType.PERFORMANCE_TROUBLESHOOT,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _cost_optimization_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze cost optimization opportunities.

        Workflow:
        1. Find cost opportunities (rightsizing, unused resources)
        2. Get savings summary by category
        3. Analyze resource utilization for underused DBs

        Args:
            context: Agent context
            params: Optional compartment filtering

        Returns:
            SkillResult with cost optimization analysis
        """
        with create_span(
            "skill.cost_optimization",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            # Step 1: Cost opportunities
            opportunities = await self._call_tool(
                context,
                "find_cost_opportunities",
                params,
            )
            if opportunities.get("success"):
                data["cost_opportunities"] = opportunities.get("data")
                opp_data = opportunities.get("data", {})

                if isinstance(opp_data, dict):
                    total = opp_data.get("total_monthly_savings", 0)
                    findings.append(f"Total potential savings: ${total:.2f}/month")

                    by_type = opp_data.get("by_type", {})
                    for opp_type, amount in by_type.items():
                        if amount > 0:
                            recommendations.append(
                                f"{opp_type}: potential ${amount:.2f}/month savings"
                            )

            # Step 2: Savings summary
            savings = await self._call_tool(context, "get_savings_summary", params)
            if savings.get("success"):
                data["savings_summary"] = savings.get("data")

            # Step 3: Resource utilization for context
            resources = await self._call_tool(
                context,
                "get_resource_utilization",
                params,
            )
            if resources.get("success"):
                data["resource_utilization"] = resources.get("data")
                res_data = resources.get("data", {})

                if isinstance(res_data, dict):
                    underutilized = res_data.get("underutilized_databases", [])
                    if underutilized:
                        findings.append(
                            f"Found {len(underutilized)} underutilized databases"
                        )

            return SkillResult(
                skill=SkillType.COST_OPTIMIZATION,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _sql_deep_dive_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Deep dive into SQL performance.

        Workflow:
        1. Get comprehensive SQL statistics
        2. Check SQL insights for issues
        3. Analyze execution plans if sql_id provided

        Args:
            context: Agent context
            params: Should include database_id, optionally sql_id

        Returns:
            SkillResult with SQL analysis
        """
        with create_span(
            "skill.sql_deep_dive",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}
            sql_id = params.get("sql_id")

            # Step 1: SQL Statistics
            stats = await self._call_tool(context, "get_sql_statistics", params)
            if stats.get("success"):
                data["sql_statistics"] = stats.get("data")
                stats_data = stats.get("data", {})

                if isinstance(stats_data, dict):
                    top_by_cpu = stats_data.get("top_by_cpu", [])
                    top_by_elapsed = stats_data.get("top_by_elapsed", [])

                    if top_by_cpu:
                        findings.append(
                            f"Top {len(top_by_cpu)} SQL by CPU consumption identified"
                        )
                    if top_by_elapsed:
                        findings.append(
                            f"Top {len(top_by_elapsed)} SQL by elapsed time identified"
                        )

            # Step 2: SQL Insights
            insights = await self._call_tool(context, "get_sql_insights", params)
            if insights.get("success"):
                data["sql_insights"] = insights.get("data")
                insights_data = insights.get("data", {})

                if isinstance(insights_data, dict):
                    degraded = insights_data.get("degraded_sql", [])
                    improving = insights_data.get("improving_sql", [])

                    if degraded:
                        findings.append(f"{len(degraded)} SQL statements have degraded")
                        recommendations.append(
                            "Check for stale statistics or plan changes"
                        )
                    if improving:
                        findings.append(
                            f"{len(improving)} SQL statements have improved"
                        )

            # Step 3: Execution plans for specific SQL
            if sql_id and params.get("database_id"):
                plans = await self._call_tool(
                    context,
                    "get_sql_plans",
                    {
                        "database_id": params["database_id"],
                        "sql_identifier": sql_id,
                    },
                )
                if plans.get("success"):
                    data["sql_plans"] = plans.get("data")
                    plans_data = plans.get("data", {})

                    if isinstance(plans_data, dict):
                        plan_count = len(plans_data.get("plans", []))
                        if plan_count > 1:
                            findings.append(
                                f"SQL has {plan_count} different execution plans"
                            )
                            recommendations.append(
                                "Consider SQL plan baselines to stabilize execution"
                            )

            return SkillResult(
                skill=SkillType.SQL_DEEP_DIVE,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _capacity_planning_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze capacity and resource trends.

        Workflow:
        1. Get resource utilization with projections
        2. Analyze CPU trends
        3. Analyze memory trends
        4. Check I/O performance

        Args:
            context: Agent context
            params: Optional database_id for specific DB

        Returns:
            SkillResult with capacity analysis
        """
        with create_span(
            "skill.capacity_planning",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            # Step 1: Resource utilization with projections
            resources = await self._call_tool(
                context,
                "get_resource_utilization",
                params,
            )
            if resources.get("success"):
                data["resource_utilization"] = resources.get("data")
                res_data = resources.get("data", {})

                if isinstance(res_data, dict):
                    projections = res_data.get("capacity_projections", {})
                    for resource, projection in projections.items():
                        if isinstance(projection, dict):
                            days_to_full = projection.get("days_to_full")
                            if days_to_full and days_to_full < 30:
                                findings.append(
                                    f"{resource} capacity exhaustion in {days_to_full} days"
                                )
                                recommendations.append(
                                    f"Plan {resource} expansion or optimization"
                                )

            # Step 2: CPU analysis
            cpu = await self._call_tool(context, "analyze_cpu", params)
            if cpu.get("success"):
                data["cpu_analysis"] = cpu.get("data")
                cpu_data = cpu.get("data", {})

                if isinstance(cpu_data, dict):
                    trend = cpu_data.get("trend")
                    if trend == "increasing":
                        findings.append("CPU utilization showing upward trend")
                        recommendations.append(
                            "Monitor CPU growth and plan for scaling"
                        )

            # Step 3: Memory analysis
            memory = await self._call_tool(context, "analyze_memory", params)
            if memory.get("success"):
                data["memory_analysis"] = memory.get("data")
                mem_data = memory.get("data", {})

                if isinstance(mem_data, dict):
                    avg_mem = mem_data.get("average_utilization", 0)
                    if avg_mem > 85:
                        findings.append(f"High memory utilization: {avg_mem:.1f}%")
                        recommendations.append(
                            "Consider memory expansion or SGA/PGA tuning"
                        )

            # Step 4: I/O analysis
            io = await self._call_tool(context, "analyze_io", params)
            if io.get("success"):
                data["io_analysis"] = io.get("data")

            return SkillResult(
                skill=SkillType.CAPACITY_PLANNING,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _database_health_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Comprehensive single-database health check.

        Workflow:
        1. Get performance summary (CPU, memory, I/O combined)
        2. Check ADDM recommendations
        3. Analyze SQL insights
        4. Get resource utilization

        Args:
            context: Agent context
            params: Must include database_id

        Returns:
            SkillResult with database health assessment
        """
        with create_span(
            "skill.database_health",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            database_id = params.get("database_id")
            if not database_id:
                return SkillResult(
                    skill=SkillType.DATABASE_HEALTH,
                    success=False,
                    error="database_id is required for database health check",
                )

            # Step 1: Performance summary
            perf = await self._call_tool(
                context,
                "get_performance_summary",
                params,
            )
            if perf.get("success"):
                data["performance_summary"] = perf.get("data")
                perf_data = perf.get("data", {})

                if isinstance(perf_data, dict):
                    cpu = perf_data.get("cpu_utilization", {})
                    memory = perf_data.get("memory_utilization", {})

                    if isinstance(cpu, dict):
                        avg_cpu = cpu.get("average", 0)
                        if avg_cpu > 70:
                            findings.append(f"Elevated CPU: {avg_cpu:.1f}% average")

                    if isinstance(memory, dict):
                        avg_mem = memory.get("average", 0)
                        if avg_mem > 80:
                            findings.append(f"High memory: {avg_mem:.1f}% average")

            # Step 2: ADDM recommendations
            addm = await self._call_tool(context, "get_addm_recommendations", params)
            if addm.get("success"):
                data["addm_recommendations"] = addm.get("data")
                addm_data = addm.get("data", {})

                if isinstance(addm_data, dict):
                    recs = addm_data.get("recommendations", [])
                    findings.append(f"ADDM found {len(recs)} recommendations")
                    for rec in recs[:5]:
                        if isinstance(rec, dict):
                            recommendations.append(
                                rec.get("finding", str(rec))
                            )

            # Step 3: SQL insights
            insights = await self._call_tool(context, "get_sql_insights", params)
            if insights.get("success"):
                data["sql_insights"] = insights.get("data")

            # Step 4: Resource utilization
            resources = await self._call_tool(
                context,
                "get_resource_utilization",
                params,
            )
            if resources.get("success"):
                data["resource_utilization"] = resources.get("data")

            # Generate health score
            health_score = self._calculate_health_score(data)
            data["health_score"] = health_score
            findings.insert(0, f"Database health score: {health_score}/100")

            if health_score < 70:
                recommendations.insert(
                    0,
                    "Database requires attention - review findings and recommendations",
                )

            return SkillResult(
                skill=SkillType.DATABASE_HEALTH,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    def _calculate_health_score(self, data: dict[str, Any]) -> int:
        """Calculate a simple health score from collected data.

        Args:
            data: Collected skill data

        Returns:
            Health score 0-100
        """
        score = 100
        deductions = 0

        # Check performance summary
        perf = data.get("performance_summary", {})
        if isinstance(perf, dict):
            cpu = perf.get("cpu_utilization", {})
            if isinstance(cpu, dict):
                avg_cpu = cpu.get("average", 0)
                if avg_cpu > 90:
                    deductions += 20
                elif avg_cpu > 70:
                    deductions += 10

            memory = perf.get("memory_utilization", {})
            if isinstance(memory, dict):
                avg_mem = memory.get("average", 0)
                if avg_mem > 90:
                    deductions += 15
                elif avg_mem > 80:
                    deductions += 5

        # Check ADDM recommendations
        addm = data.get("addm_recommendations", {})
        if isinstance(addm, dict):
            recs = addm.get("recommendations", [])
            high_impact = sum(
                1 for r in recs
                if isinstance(r, dict) and r.get("impact", "").lower() == "high"
            )
            deductions += min(high_impact * 5, 20)

        # Check SQL insights
        insights = data.get("sql_insights", {})
        if isinstance(insights, dict):
            degraded = len(insights.get("degraded_sql", []))
            deductions += min(degraded * 3, 15)

        return max(0, score - deductions)

    # ==========================================
    # Database Management API Skills
    # ==========================================

    async def _awr_analysis_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Deep AWR analysis using Database Management API.

        Workflow:
        1. Get AWR SQL report for top SQL consumers
        2. Summarize wait events for bottleneck identification
        3. Analyze CPU usage patterns

        Args:
            context: Agent context
            params: Must include managed_database_id, optionally begin/end snapshot IDs

        Returns:
            SkillResult with comprehensive AWR analysis
        """
        with create_span(
            "skill.awr_analysis",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            managed_database_id = params.get("managed_database_id")
            if not managed_database_id:
                return SkillResult(
                    skill=SkillType.AWR_ANALYSIS,
                    success=False,
                    error="managed_database_id is required for AWR analysis",
                )

            # Step 1: AWR SQL Report
            sql_report = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_get_awr_sql_report",
                params,
            )
            if sql_report.get("success"):
                data["awr_sql_report"] = sql_report.get("data")
                report_data = sql_report.get("data", {})

                if isinstance(report_data, dict):
                    top_sql = report_data.get("top_sql_statements", [])
                    if top_sql:
                        findings.append(
                            f"Identified {len(top_sql)} top SQL statements in AWR"
                        )
                        # Check for high-impact SQL
                        high_cpu = [s for s in top_sql if isinstance(s, dict) and s.get("cpu_percent", 0) > 20]
                        if high_cpu:
                            recommendations.append(
                                f"Review {len(high_cpu)} SQL statements consuming >20% CPU"
                            )

            # Step 2: Wait Events Summary
            wait_events = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_summarize_awr_wait_events",
                params,
            )
            if wait_events.get("success"):
                data["wait_events_summary"] = wait_events.get("data")
                events_data = wait_events.get("data", {})

                if isinstance(events_data, dict):
                    top_waits = events_data.get("top_wait_events", [])
                    for wait in top_waits[:3]:
                        if isinstance(wait, dict):
                            event_name = wait.get("event_name", "Unknown")
                            wait_pct = wait.get("wait_percent", 0)
                            if wait_pct > 10:
                                findings.append(
                                    f"Significant wait: {event_name} ({wait_pct:.1f}%)"
                                )

            # Step 3: CPU Usage Summary
            cpu_summary = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_summarize_awr_cpu",
                params,
            )
            if cpu_summary.get("success"):
                data["cpu_summary"] = cpu_summary.get("data")
                cpu_data = cpu_summary.get("data", {})

                if isinstance(cpu_data, dict):
                    avg_cpu = cpu_data.get("average_cpu_percent", 0)
                    peak_cpu = cpu_data.get("peak_cpu_percent", 0)
                    if peak_cpu > 90:
                        findings.append(f"CPU peaked at {peak_cpu:.1f}% during AWR period")
                        recommendations.append(
                            "Investigate workload spikes during peak CPU periods"
                        )
                    if avg_cpu > 70:
                        findings.append(f"High average CPU utilization: {avg_cpu:.1f}%")

            return SkillResult(
                skill=SkillType.AWR_ANALYSIS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _sql_tuning_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """SQL tuning analysis using Database Management API.

        Workflow:
        1. List SQL Tuning Advisor tasks and their status
        2. Get SQL Tuning Advisor summary for recommendations
        3. Analyze cursor cache for execution patterns

        Args:
            context: Agent context
            params: Must include managed_database_id

        Returns:
            SkillResult with SQL tuning analysis
        """
        with create_span(
            "skill.sql_tuning",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            managed_database_id = params.get("managed_database_id")
            if not managed_database_id:
                return SkillResult(
                    skill=SkillType.SQL_TUNING,
                    success=False,
                    error="managed_database_id is required for SQL tuning analysis",
                )

            # Step 1: SQL Tuning Advisor Tasks
            advisor_tasks = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_list_sql_tuning_advisor_tasks",
                params,
            )
            if advisor_tasks.get("success"):
                data["sql_tuning_tasks"] = advisor_tasks.get("data")
                tasks_data = advisor_tasks.get("data", {})

                if isinstance(tasks_data, dict):
                    tasks = tasks_data.get("tasks", [])
                    completed = [t for t in tasks if isinstance(t, dict) and t.get("status") == "COMPLETED"]
                    findings.append(f"Found {len(tasks)} SQL Tuning Advisor tasks ({len(completed)} completed)")

            # Step 2: SQL Tuning Advisor Summary
            advisor_summary = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_get_sql_tuning_advisor_summary",
                params,
            )
            if advisor_summary.get("success"):
                data["sql_tuning_summary"] = advisor_summary.get("data")
                summary_data = advisor_summary.get("data", {})

                if isinstance(summary_data, dict):
                    total_findings = summary_data.get("total_findings", 0)
                    implemented = summary_data.get("implemented_recommendations", 0)

                    if total_findings > 0:
                        findings.append(
                            f"SQL Tuning Advisor: {total_findings} findings, "
                            f"{implemented} implemented"
                        )
                        if total_findings > implemented:
                            recommendations.append(
                                f"Review {total_findings - implemented} pending SQL tuning recommendations"
                            )

                    # Check for profile/index recommendations
                    profiles = summary_data.get("sql_profile_recommendations", 0)
                    indexes = summary_data.get("index_recommendations", 0)
                    if profiles > 0:
                        recommendations.append(
                            f"Consider implementing {profiles} SQL profile recommendations"
                        )
                    if indexes > 0:
                        recommendations.append(
                            f"Evaluate {indexes} index recommendations"
                        )

            # Step 3: Cursor Cache Analysis
            cursor_cache = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_list_cursor_cache_statements",
                params,
            )
            if cursor_cache.get("success"):
                data["cursor_cache"] = cursor_cache.get("data")
                cache_data = cursor_cache.get("data", {})

                if isinstance(cache_data, dict):
                    statements = cache_data.get("statements", [])
                    # Find statements with multiple child cursors (potential bind issues)
                    multi_child = [
                        s for s in statements
                        if isinstance(s, dict) and s.get("child_cursor_count", 0) > 10
                    ]
                    if multi_child:
                        findings.append(
                            f"{len(multi_child)} SQL statements have excessive child cursors"
                        )
                        recommendations.append(
                            "Investigate cursor sharing issues for statements with many child cursors"
                        )

            return SkillResult(
                skill=SkillType.SQL_TUNING,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _alert_analysis_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze database attention logs and alerts.

        Workflow:
        1. Count attention logs by severity/type
        2. List recent attention logs for detail
        3. Identify patterns and recurring issues

        Args:
            context: Agent context
            params: Must include managed_database_id, optionally time_range

        Returns:
            SkillResult with alert analysis
        """
        with create_span(
            "skill.alert_analysis",
            component="coordinator",
        ):
            findings = []
            recommendations = []
            data = {}

            managed_database_id = params.get("managed_database_id")
            if not managed_database_id:
                return SkillResult(
                    skill=SkillType.ALERT_ANALYSIS,
                    success=False,
                    error="managed_database_id is required for alert analysis",
                )

            # Step 1: Count attention logs by severity
            log_counts = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_count_attention_logs",
                params,
            )
            if log_counts.get("success"):
                data["attention_log_counts"] = log_counts.get("data")
                counts_data = log_counts.get("data", {})

                if isinstance(counts_data, dict):
                    total = counts_data.get("total_count", 0)
                    by_severity = counts_data.get("by_severity", {})

                    findings.append(f"Total attention log entries: {total}")

                    critical = by_severity.get("CRITICAL", 0)
                    warning = by_severity.get("WARNING", 0)

                    if critical > 0:
                        findings.append(f"CRITICAL alerts: {critical}")
                        recommendations.append(
                            "Immediately investigate critical database alerts"
                        )
                    if warning > 5:
                        findings.append(f"WARNING alerts: {warning}")
                        recommendations.append(
                            "Review warning alerts for potential issues"
                        )

            # Step 2: List recent attention logs
            attention_logs = await self._call_dbmgmt_tool(
                context,
                "oci_dbmgmt_list_attention_logs",
                params,
            )
            if attention_logs.get("success"):
                data["attention_logs"] = attention_logs.get("data")
                logs_data = attention_logs.get("data", {})

                if isinstance(logs_data, dict):
                    logs = logs_data.get("items", [])

                    # Identify recurring messages
                    message_counts: dict[str, int] = {}
                    for log in logs:
                        if isinstance(log, dict):
                            msg_type = log.get("message_type", "Unknown")
                            message_counts[msg_type] = message_counts.get(msg_type, 0) + 1

                    # Find recurring issues
                    recurring = [
                        (msg, count) for msg, count in message_counts.items()
                        if count >= 3
                    ]
                    if recurring:
                        findings.append(f"Found {len(recurring)} recurring alert patterns")
                        for msg, count in sorted(recurring, key=lambda x: -x[1])[:3]:
                            recommendations.append(
                                f"Investigate recurring alert: '{msg}' ({count} occurrences)"
                            )

            # Determine overall alert health
            alert_score = self._calculate_alert_score(data)
            data["alert_health_score"] = alert_score
            if alert_score < 70:
                findings.insert(0, f"Alert health score: {alert_score}/100 (needs attention)")
            else:
                findings.insert(0, f"Alert health score: {alert_score}/100")

            return SkillResult(
                skill=SkillType.ALERT_ANALYSIS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    def _calculate_alert_score(self, data: dict[str, Any]) -> int:
        """Calculate alert health score from attention log data.

        Args:
            data: Collected alert analysis data

        Returns:
            Alert health score 0-100
        """
        score = 100
        deductions = 0

        counts = data.get("attention_log_counts", {})
        if isinstance(counts, dict):
            by_severity = counts.get("by_severity", {})
            critical = by_severity.get("CRITICAL", 0)
            warning = by_severity.get("WARNING", 0)

            # Deduct for critical alerts
            deductions += min(critical * 10, 40)
            # Deduct for warnings
            deductions += min(warning * 2, 20)

        logs = data.get("attention_logs", {})
        if isinstance(logs, dict):
            items = logs.get("items", [])
            # Deduct for high volume of alerts
            if len(items) > 50:
                deductions += 15
            elif len(items) > 20:
                deductions += 10

        return max(0, score - deductions)

    # ==========================================
    # Runbook-based Diagnostic Skills
    # ==========================================

    async def _blocking_sessions_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze blocking sessions and lock contention.

        Workflow:
        1. Load blocking_sessions runbook
        2. Execute queries to identify blocking chains
        3. Analyze lock contention patterns

        Args:
            context: Agent context
            params: Should include connection_name for database

        Returns:
            SkillResult with blocking session analysis
        """
        with create_span(
            "skill.blocking_sessions",
            component="coordinator",
        ):
            findings: list[str] = []
            recommendations: list[str] = []
            data: dict[str, Any] = {}

            connection_name = params.get("connection_name")

            try:
                runbook = load_runbook("blocking_sessions")
            except (ValueError, FileNotFoundError) as e:
                return SkillResult(
                    skill=SkillType.BLOCKING_SESSIONS,
                    success=False,
                    error=f"Failed to load blocking_sessions runbook: {e}",
                )

            # Execute key queries from the runbook
            for query in runbook.queries[:3]:  # First 3 most relevant queries
                result = await self._execute_runbook_sql(
                    context,
                    query.sql,
                    connection_name,
                )
                if result.get("success"):
                    data[query.name.lower().replace(" ", "_")] = result.get("data")

                    # Analyze results
                    rows = result.get("data", {}).get("rows", [])
                    if rows:
                        findings.append(
                            f"{query.name}: Found {len(rows)} blocking-related records"
                        )

            # Generate recommendations based on findings
            if data.get("query_1"):
                rows = data["query_1"].get("rows", [])
                if rows:
                    recommendations.append(
                        "Review blocking session chains - consider killing blocking sessions if appropriate"
                    )
                    recommendations.append(
                        "Investigate the SQL being run by blocking sessions"
                    )
                else:
                    findings.append("No active blocking sessions detected")

            return SkillResult(
                skill=SkillType.BLOCKING_SESSIONS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _long_operations_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze long-running database operations.

        Workflow:
        1. Load long_operations runbook
        2. Execute queries to find long-running operations
        3. Identify patterns and estimate completion times

        Args:
            context: Agent context
            params: Should include connection_name for database

        Returns:
            SkillResult with long operations analysis
        """
        with create_span(
            "skill.long_operations",
            component="coordinator",
        ):
            findings: list[str] = []
            recommendations: list[str] = []
            data: dict[str, Any] = {}

            connection_name = params.get("connection_name")

            try:
                runbook = load_runbook("long_operations")
            except (ValueError, FileNotFoundError) as e:
                return SkillResult(
                    skill=SkillType.LONG_OPERATIONS,
                    success=False,
                    error=f"Failed to load long_operations runbook: {e}",
                )

            # Execute key queries
            for query in runbook.queries[:4]:  # First 4 queries
                result = await self._execute_runbook_sql(
                    context,
                    query.sql,
                    connection_name,
                )
                if result.get("success"):
                    data[query.name.lower().replace(" ", "_")] = result.get("data")

            # Analyze active long operations
            active_ops = data.get("query_1", {}).get("rows", [])
            if active_ops:
                findings.append(f"Found {len(active_ops)} currently running long operations")
                for op in active_ops[:5]:  # Top 5
                    if isinstance(op, dict):
                        elapsed = op.get("elapsed_seconds", 0)
                        op_name = op.get("operation_name", "Unknown")
                        pct = op.get("pct_complete", 0)
                        findings.append(f"  - {op_name}: {pct}% complete, {elapsed}s elapsed")

                recommendations.append(
                    "Monitor long-running operations for expected completion times"
                )
            else:
                findings.append("No active long-running operations detected")

            # Check for threshold-exceeding operations
            threshold_ops = data.get("query_6", {}).get("rows", [])
            if threshold_ops:
                findings.append(
                    f"ALERT: {len(threshold_ops)} operations exceeding duration threshold"
                )
                recommendations.append(
                    "Investigate operations exceeding expected duration thresholds"
                )

            return SkillResult(
                skill=SkillType.LONG_OPERATIONS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _parallelism_analysis_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze parallel execution and detect downgrades.

        Workflow:
        1. Load parallelism_stats runbook
        2. Execute queries to analyze parallel execution
        3. Identify downgrade issues and resource constraints

        Args:
            context: Agent context
            params: Should include connection_name for database

        Returns:
            SkillResult with parallelism analysis
        """
        with create_span(
            "skill.parallelism_analysis",
            component="coordinator",
        ):
            findings: list[str] = []
            recommendations: list[str] = []
            data: dict[str, Any] = {}

            connection_name = params.get("connection_name")

            try:
                runbook = load_runbook("parallelism_stats")
            except (ValueError, FileNotFoundError) as e:
                return SkillResult(
                    skill=SkillType.PARALLELISM_ANALYSIS,
                    success=False,
                    error=f"Failed to load parallelism_stats runbook: {e}",
                )

            # Execute key queries
            for query in runbook.queries[:5]:
                result = await self._execute_runbook_sql(
                    context,
                    query.sql,
                    connection_name,
                )
                if result.get("success"):
                    data[query.name.lower().replace(" ", "_")] = result.get("data")

            # Analyze parallel sessions
            px_sessions = data.get("query_1", {}).get("rows", [])
            downgraded = [
                s for s in px_sessions
                if isinstance(s, dict) and s.get("parallel_status") == "DOWNGRADED"
            ]
            if downgraded:
                findings.append(
                    f"Found {len(downgraded)} parallel operations running with reduced parallelism"
                )
                recommendations.append(
                    "Investigate parallel downgrade reasons - check PGA memory and parallel server availability"
                )

            # Check PQ statistics
            pq_stats = data.get("query_2", {}).get("rows", [])
            if pq_stats:
                findings.append(f"Parallel execution statistics: {len(pq_stats)} metrics available")

            # Check resource manager limits
            rm_data = data.get("query_6", {}).get("rows", [])
            at_limit = [
                r for r in rm_data
                if isinstance(r, dict) and r.get("pq_status") == "AT LIMIT"
            ]
            if at_limit:
                findings.append(
                    f"WARNING: {len(at_limit)} consumer groups at parallel server limit"
                )
                recommendations.append(
                    "Consider adjusting Resource Manager parallel server limits"
                )

            # Check parallel parameters
            params_data = data.get("query_7", {}).get("rows", [])
            if params_data:
                data["parallel_parameters"] = params_data

            return SkillResult(
                skill=SkillType.PARALLELISM_ANALYSIS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _full_table_scans_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Analyze full table scan operations.

        Workflow:
        1. Load full_table_scans runbook
        2. Execute queries to identify costly full scans
        3. Recommend index or optimization strategies

        Args:
            context: Agent context
            params: Should include connection_name for database

        Returns:
            SkillResult with full table scan analysis
        """
        with create_span(
            "skill.full_table_scans",
            component="coordinator",
        ):
            findings: list[str] = []
            recommendations: list[str] = []
            data: dict[str, Any] = {}

            connection_name = params.get("connection_name")

            try:
                runbook = load_runbook("full_table_scans")
            except (ValueError, FileNotFoundError) as e:
                return SkillResult(
                    skill=SkillType.FULL_TABLE_SCANS,
                    success=False,
                    error=f"Failed to load full_table_scans runbook: {e}",
                )

            # Execute key queries
            for query in runbook.queries[:5]:
                result = await self._execute_runbook_sql(
                    context,
                    query.sql,
                    connection_name,
                )
                if result.get("success"):
                    data[query.name.lower().replace(" ", "_")] = result.get("data")

            # Active scans in progress
            active_scans = data.get("query_1", {}).get("rows", [])
            if active_scans:
                findings.append(
                    f"Found {len(active_scans)} full table scans currently in progress"
                )
                for scan in active_scans[:3]:
                    if isinstance(scan, dict):
                        table = scan.get("table_name", "Unknown")
                        elapsed = scan.get("elapsed_seconds", 0)
                        pct = scan.get("pct_complete", 0)
                        findings.append(f"  - {table}: {pct}% complete, {elapsed}s elapsed")

            # SQL statements with full scans
            scan_sql = data.get("query_2", {}).get("rows", [])
            if scan_sql:
                high_cost = [
                    s for s in scan_sql
                    if isinstance(s, dict) and s.get("disk_reads_per_exec", 0) > 10000
                ]
                findings.append(
                    f"Found {len(scan_sql)} SQL statements using full table scans"
                )
                if high_cost:
                    recommendations.append(
                        f"Review {len(high_cost)} high-I/O full scan statements for indexing opportunities"
                    )

            # Large tables being scanned
            large_scans = data.get("query_3", {}).get("rows", [])
            if large_scans:
                findings.append(
                    f"Found {len(large_scans)} large tables being full scanned"
                )
                for table in large_scans[:3]:
                    if isinstance(table, dict):
                        name = table.get("table_name", "Unknown")
                        size_mb = table.get("table_size_mb", 0)
                        findings.append(f"  - {name}: {size_mb}MB")

            # Missing index recommendations
            missing_idx = data.get("query_5", {}).get("rows", [])
            if missing_idx:
                recommendations.append(
                    f"Consider adding indexes for {len(missing_idx)} tables with filter predicates"
                )

            # Stale statistics
            stale_stats = data.get("query_7", {}).get("rows", [])
            if stale_stats:
                findings.append(
                    f"WARNING: {len(stale_stats)} tables with stale statistics may be causing unnecessary full scans"
                )
                recommendations.append(
                    "Update statistics on tables with stale stats to improve optimizer decisions"
                )

            return SkillResult(
                skill=SkillType.FULL_TABLE_SCANS,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    async def _sql_monitor_skill(
        self,
        context: AgentContext,
        params: dict[str, Any],
    ) -> SkillResult:
        """Real-time SQL monitoring analysis.

        Workflow:
        1. Load sql_monitor runbook
        2. Execute queries against V$SQL_MONITOR
        3. Identify long-running and problematic SQL

        Args:
            context: Agent context
            params: Should include connection_name for database

        Returns:
            SkillResult with SQL monitor analysis

        Note: Requires Oracle Enterprise Edition with Tuning Pack license
        """
        with create_span(
            "skill.sql_monitor",
            component="coordinator",
        ):
            findings: list[str] = []
            recommendations: list[str] = []
            data: dict[str, Any] = {}

            connection_name = params.get("connection_name")

            try:
                runbook = load_runbook("sql_monitor")
            except (ValueError, FileNotFoundError) as e:
                return SkillResult(
                    skill=SkillType.SQL_MONITOR,
                    success=False,
                    error=f"Failed to load sql_monitor runbook: {e}",
                )

            # Execute key queries
            for query in runbook.queries[:6]:
                result = await self._execute_runbook_sql(
                    context,
                    query.sql,
                    connection_name,
                )
                if result.get("success"):
                    data[query.name.lower().replace(" ", "_")] = result.get("data")
                elif "ORA-" in str(result.get("error", "")):
                    # License or privilege error - note it but continue
                    data["license_note"] = (
                        "V$SQL_MONITOR requires Oracle Enterprise Edition with Tuning Pack"
                    )
                    break

            # Currently executing SQL
            executing = data.get("query_1", {}).get("rows", [])
            if executing:
                findings.append(
                    f"Found {len(executing)} SQL statements currently being monitored"
                )
                for sql in executing[:5]:
                    if isinstance(sql, dict):
                        sql_id = sql.get("sql_id", "Unknown")
                        elapsed = sql.get("elapsed_sec", 0)
                        user = sql.get("username", "Unknown")
                        findings.append(f"  - {sql_id} ({user}): {elapsed}s elapsed")

            # Long-running monitored SQL
            long_running = data.get("query_2", {}).get("rows", [])
            if long_running:
                findings.append(
                    f"Found {len(long_running)} SQL executions exceeding duration threshold"
                )
                recommendations.append(
                    "Review long-running SQL for optimization opportunities"
                )

            # Parallel execution analysis
            px_sql = data.get("query_4", {}).get("rows", [])
            downgraded = [
                s for s in px_sql
                if isinstance(s, dict) and s.get("px_status") == "DOWNGRADED"
            ]
            if downgraded:
                findings.append(
                    f"Found {len(downgraded)} parallel SQL executions with reduced parallelism"
                )
                recommendations.append(
                    "Investigate parallel execution downgrades"
                )

            # Wait event breakdown
            waits = data.get("query_5", {}).get("rows", [])
            if waits:
                high_io = [
                    w for w in waits
                    if isinstance(w, dict) and w.get("io_pct", 0) > 50
                ]
                if high_io:
                    findings.append(
                        f"{len(high_io)} SQL statements spending >50% time on I/O"
                    )
                    recommendations.append(
                        "Investigate high I/O SQL for indexing or partitioning opportunities"
                    )

            # Cardinality estimation issues
            card_issues = data.get("query_6", {}).get("rows", [])
            if card_issues:
                severe = [
                    c for c in card_issues
                    if isinstance(c, dict) and "SEVERE" in c.get("estimate_quality", "")
                ]
                if severe:
                    findings.append(
                        f"Found {len(severe)} plan operations with severe cardinality misestimates"
                    )
                    recommendations.append(
                        "Review table/index statistics for tables with cardinality issues"
                    )

            return SkillResult(
                skill=SkillType.SQL_MONITOR,
                success=True,
                data=data,
                findings=findings,
                recommendations=recommendations,
            )

    def list_skills(self) -> list[dict[str, str]]:
        """List available skills with descriptions.

        Returns:
            List of skill info dictionaries
        """
        return [
            {
                "type": SkillType.FLEET_HEALTH.value,
                "name": "Fleet Health Assessment",
                "description": "Assess overall database fleet health with cost opportunities",
            },
            {
                "type": SkillType.PERFORMANCE_TROUBLESHOOT.value,
                "name": "Performance Troubleshooting",
                "description": "Diagnose performance issues with SQL and ADDM analysis",
            },
            {
                "type": SkillType.COST_OPTIMIZATION.value,
                "name": "Cost Optimization Analysis",
                "description": "Find rightsizing and cost savings opportunities",
            },
            {
                "type": SkillType.SQL_DEEP_DIVE.value,
                "name": "SQL Performance Deep Dive",
                "description": "Comprehensive SQL analysis with execution plans",
            },
            {
                "type": SkillType.CAPACITY_PLANNING.value,
                "name": "Capacity Planning",
                "description": "Resource trends and capacity projections",
            },
            {
                "type": SkillType.DATABASE_HEALTH.value,
                "name": "Database Health Check",
                "description": "Comprehensive single-database health assessment",
            },
            # Database Management API skills
            {
                "type": SkillType.AWR_ANALYSIS.value,
                "name": "AWR Performance Analysis",
                "description": "AWR-based analysis of SQL performance, wait events, and CPU usage",
            },
            {
                "type": SkillType.SQL_TUNING.value,
                "name": "SQL Tuning Analysis",
                "description": "SQL Tuning Advisor tasks, recommendations, and cursor cache analysis",
            },
            {
                "type": SkillType.ALERT_ANALYSIS.value,
                "name": "Database Alert Analysis",
                "description": "Attention log analysis with severity breakdown and recurring patterns",
            },
            # Runbook-based diagnostic skills
            {
                "type": SkillType.BLOCKING_SESSIONS.value,
                "name": "Blocking Sessions Analysis",
                "description": "Detect lock contention, blocking chains, and session waits",
            },
            {
                "type": SkillType.LONG_OPERATIONS.value,
                "name": "Long Running Operations",
                "description": "Monitor V$SESSION_LONGOPS for extended operations and progress",
            },
            {
                "type": SkillType.PARALLELISM_ANALYSIS.value,
                "name": "Parallelism Analysis",
                "description": "Analyze parallel execution, detect downgrades and resource constraints",
            },
            {
                "type": SkillType.FULL_TABLE_SCANS.value,
                "name": "Full Table Scan Detection",
                "description": "Identify expensive full table scans and missing index opportunities",
            },
            {
                "type": SkillType.SQL_MONITOR.value,
                "name": "SQL Real-time Monitor",
                "description": "Real-time SQL monitoring via V$SQL_MONITOR (Enterprise Edition)",
            },
        ]
