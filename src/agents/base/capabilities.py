"""Agent capability definitions."""

from dataclasses import dataclass, field
from enum import Enum

from src.core.types import DatabaseType


class Capability(str, Enum):
    """Agent capability types."""

    PERFORMANCE_ANALYSIS = "performance_analysis"
    SQL_EXECUTION = "sql_execution"
    TROUBLESHOOTING = "troubleshooting"
    METRICS_COLLECTION = "metrics_collection"
    LOG_ANALYSIS = "log_analysis"
    SECURITY_AUDIT = "security_audit"
    COST_ANALYSIS = "cost_analysis"


class CapabilityCategory(str, Enum):
    """Categories of agent capabilities."""

    DIAGNOSTIC = "diagnostic"
    ANALYTICAL = "analytical"
    ADMINISTRATIVE = "administrative"
    MONITORING = "monitoring"


@dataclass
class AgentCapability:
    """Definition of a single agent capability."""

    id: str
    name: str
    category: CapabilityCategory
    confidence: float  # 0.0 to 1.0
    description: str
    required_tools: list[str] = field(default_factory=list)


# Oracle-specific capabilities
ORACLE_CAPABILITIES = [
    AgentCapability(
        id="awr_analysis",
        name="AWR Analysis",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.95,
        description="Analyze AWR reports for performance issues",
        required_tools=["sqlcl__run-sql"],
    ),
    AgentCapability(
        id="ash_analysis",
        name="ASH Analysis",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.95,
        description="Active Session History analysis",
        required_tools=["sqlcl__run-sql"],
    ),
    AgentCapability(
        id="rac_diagnostics",
        name="RAC Diagnostics",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.85,
        description="RAC cluster analysis and diagnostics",
        required_tools=["sqlcl__run-sql"],
    ),
    AgentCapability(
        id="dataguard_monitoring",
        name="DataGuard Monitoring",
        category=CapabilityCategory.MONITORING,
        confidence=0.90,
        description="DataGuard status and lag monitoring",
        required_tools=["sqlcl__run-sql"],
    ),
    AgentCapability(
        id="opsi_metrics",
        name="OPSI Metrics",
        category=CapabilityCategory.ANALYTICAL,
        confidence=0.95,
        description="OCI Operations Insights metrics",
        required_tools=["oci-opsi__skill_analyze_cpu_usage"],
    ),
]

# MySQL-specific capabilities
MYSQL_CAPABILITIES = [
    AgentCapability(
        id="perf_schema",
        name="Performance Schema",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.90,
        description="Query performance analysis",
        required_tools=["mysql-mcp__query"],
    ),
    AgentCapability(
        id="innodb_diagnostics",
        name="InnoDB Diagnostics",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.90,
        description="InnoDB engine analysis",
        required_tools=["mysql-mcp__query"],
    ),
    AgentCapability(
        id="replication_status",
        name="Replication Status",
        category=CapabilityCategory.MONITORING,
        confidence=0.85,
        description="Replica lag monitoring",
        required_tools=["mysql-mcp__query"],
    ),
    AgentCapability(
        id="heatwave_analytics",
        name="HeatWave Analytics",
        category=CapabilityCategory.ANALYTICAL,
        confidence=0.80,
        description="HeatWave cluster analysis",
        required_tools=["mysql-mcp__heatwave"],
    ),
]

# PostgreSQL-specific capabilities
POSTGRES_CAPABILITIES = [
    AgentCapability(
        id="pg_stat_analysis",
        name="pg_stat Analysis",
        category=CapabilityCategory.DIAGNOSTIC,
        confidence=0.90,
        description="Statistics collector analysis",
        required_tools=["postgres-mcp__query"],
    ),
    AgentCapability(
        id="vacuum_optimization",
        name="Vacuum Optimization",
        category=CapabilityCategory.ADMINISTRATIVE,
        confidence=0.85,
        description="Autovacuum tuning and dead tuple analysis",
        required_tools=["postgres-mcp__query"],
    ),
    AgentCapability(
        id="wal_monitoring",
        name="WAL Monitoring",
        category=CapabilityCategory.MONITORING,
        confidence=0.85,
        description="Write-ahead log analysis",
        required_tools=["postgres-mcp__query"],
    ),
    AgentCapability(
        id="extension_analysis",
        name="Extension Analysis",
        category=CapabilityCategory.ANALYTICAL,
        confidence=0.80,
        description="Extension usage and recommendations",
        required_tools=["postgres-mcp__query"],
    ),
]


def get_capabilities_for_database(db_type: DatabaseType) -> list[AgentCapability]:
    """Get capabilities for a specific database type."""
    match db_type:
        case DatabaseType.ORACLE:
            return ORACLE_CAPABILITIES
        case DatabaseType.MYSQL:
            return MYSQL_CAPABILITIES
        case DatabaseType.POSTGRES:
            return POSTGRES_CAPABILITIES
