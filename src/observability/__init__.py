"""OCI APM / OpenTelemetry observability module.

Provides unified observability for the MCP server:
- OCI APM tracing via OpenTelemetry (OTLP HTTP)
- OCI Logging with APM trace correlation
- Metrics recording for tools, LLM, agents, and queries
"""

from .metrics import (
    record_agent_execution,
    record_cache_hit,
    record_llm_request,
    record_query_processing,
    record_tool_execution,
)
from .oci_logging import (
    get_trace_id,
    init_oci_logging,
    shutdown_oci_logging,
)
from .spans import create_span, get_current_span, span
from .tracing import force_flush_traces, get_tracer, init_tracing, shutdown_tracing, tracer

__all__ = [
    # Tracing
    "init_tracing",
    "shutdown_tracing",
    "force_flush_traces",
    "tracer",
    "get_tracer",
    # Spans
    "span",
    "create_span",
    "get_current_span",
    # Metrics
    "record_tool_execution",
    "record_llm_request",
    "record_cache_hit",
    "record_agent_execution",
    "record_query_processing",
    # OCI Logging
    "init_oci_logging",
    "shutdown_oci_logging",
    "get_trace_id",
]


def init_observability(component: str = "api", profile: str = "DEFAULT") -> None:
    """Initialize all observability components.

    Args:
        component: Component name for service identification
        profile: OCI config profile to use

    This initializes:
    - OCI APM tracing (if OCI_APM_ENDPOINT configured)
    - OCI Logging (if OCI_LOG_GROUP_ID and OCI_LOG_ID configured)
    """
    # Initialize tracing first (logs will include trace IDs)
    init_tracing(component=component)

    # Initialize OCI Logging with trace correlation
    init_oci_logging(profile=profile)


def shutdown_observability() -> None:
    """Shutdown all observability components gracefully."""
    shutdown_oci_logging()
    shutdown_tracing()
