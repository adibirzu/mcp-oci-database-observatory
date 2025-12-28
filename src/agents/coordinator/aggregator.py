"""Response aggregation from multiple agents."""

from src.core import get_logger
from src.core.types import AgentResult, DiagnosticFinding, Severity
from src.observability import create_span

logger = get_logger("agents.coordinator.aggregator")


class ResponseAggregator:
    """Aggregates and synthesizes responses from multiple agents."""

    async def aggregate(
        self,
        results: list[AgentResult],
    ) -> dict:
        """Aggregate multiple agent results into a unified response.

        Args:
            results: List of agent execution results

        Returns:
            Aggregated response dictionary
        """
        with create_span("agent.aggregate", component="coordinator"):
            # Collect all findings
            all_findings: list[DiagnosticFinding] = []
            all_recommendations: list[str] = []
            all_tools: list[str] = []
            total_time = 0
            success_count = 0

            for result in results:
                all_findings.extend(result.findings)
                all_recommendations.extend(result.recommendations)
                all_tools.extend(result.tools_used)
                total_time += result.execution_time_ms
                if result.success:
                    success_count += 1

            # Sort findings by severity
            sorted_findings = self._sort_by_severity(all_findings)

            # Deduplicate recommendations
            unique_recommendations = list(dict.fromkeys(all_recommendations))

            # Build summary
            summary = self._build_summary(sorted_findings)

            logger.info(
                "Aggregation complete",
                agents=len(results),
                successful=success_count,
                findings=len(sorted_findings),
                recommendations=len(unique_recommendations),
            )

            return {
                "success": success_count == len(results),
                "summary": summary,
                "findings": [self._finding_to_dict(f) for f in sorted_findings],
                "recommendations": unique_recommendations,
                "metrics": {
                    "agents_invoked": len(results),
                    "agents_successful": success_count,
                    "total_findings": len(sorted_findings),
                    "critical_findings": len(
                        [f for f in sorted_findings if f.severity == Severity.CRITICAL]
                    ),
                    "tools_used": list(set(all_tools)),
                    "total_execution_time_ms": total_time,
                },
            }

    def _sort_by_severity(
        self,
        findings: list[DiagnosticFinding],
    ) -> list[DiagnosticFinding]:
        """Sort findings by severity (critical first)."""
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.WARNING: 1,
            Severity.INFO: 2,
        }
        return sorted(
            findings,
            key=lambda f: severity_order.get(f.severity, 99),
        )

    def _build_summary(self, findings: list[DiagnosticFinding]) -> str:
        """Build a summary string from findings."""
        critical = len([f for f in findings if f.severity == Severity.CRITICAL])
        warning = len([f for f in findings if f.severity == Severity.WARNING])
        info = len([f for f in findings if f.severity == Severity.INFO])

        if critical > 0:
            return f"Found {critical} critical issue(s) requiring immediate attention"
        elif warning > 0:
            return f"Found {warning} warning(s) that should be reviewed"
        elif info > 0:
            return f"Analysis complete with {info} informational finding(s)"
        else:
            return "No issues detected"

    def _finding_to_dict(self, finding: DiagnosticFinding) -> dict:
        """Convert a finding to a dictionary."""
        return {
            "id": finding.id,
            "severity": finding.severity.value,
            "category": finding.category,
            "title": finding.title,
            "description": finding.description,
            "evidence": finding.evidence,
            "recommendation": finding.recommendation,
        }
