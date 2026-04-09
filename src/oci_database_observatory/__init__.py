"""OCI Database Observatory MCP Server.

A modular, multi-tenancy MCP server for Oracle Database operations,
OCI Operations Insights, and Logging Analytics.

Architecture:
- Stateless tool providers (MCP best practices)
- Multi-tenancy support via OCI profiles
- Response caching for fast AI agent interactions
- Modular tool registration

Tool Categories:
- SQLcl: execute_sql, get_schema_info, list_connections, database_status
- OPSI: get_fleet_summary, search_databases, analyze_cpu/memory/io_usage
- Logan: execute_logan_query, list_log_sources, list_entities, list_parsers
- Tenancy: list_oci_profiles, set_active_profile, list_compartments

Usage:
    python -m src.oci_database_observatory
"""

__version__ = "0.2.0"

# Exports
from .config import TenancyProfile, TenancyManager, get_tenancy_manager
from .clients import get_oci_manager, get_sqlcl_client, disconnect_sqlcl
from .cache import ResponseCache, get_cache, cached_call

__all__ = [
    "TenancyProfile",
    "TenancyManager",
    "get_tenancy_manager",
    "get_oci_manager",
    "get_sqlcl_client",
    "disconnect_sqlcl",
    "ResponseCache",
    "get_cache",
    "cached_call",
]
