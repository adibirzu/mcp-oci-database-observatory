"""OCI APM / OpenTelemetry observability module."""

from .metrics import (
    record_agent_execution,
    record_cache_hit,
    record_llm_request,
    record_query_processing,
    record_tool_execution,
)
from .spans import create_span, get_current_span, span
from .tracing import init_tracing, shutdown_tracing, tracer

__all__ = [
    "init_tracing",
    "shutdown_tracing",
    "tracer",
    "span",
    "create_span",
    "get_current_span",
    "record_tool_execution",
    "record_llm_request",
    "record_cache_hit",
    "record_agent_execution",
    "record_query_processing",
]
