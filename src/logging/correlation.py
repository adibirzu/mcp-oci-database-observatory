"""APM trace correlation utilities."""

from opentelemetry import trace
from opentelemetry.trace import SpanContext

from src.core import get_logger

logger = get_logger("oci.logging.correlation")


def get_current_trace_context() -> dict[str, str]:
    """Get the current trace context for log correlation.

    Returns:
        Dictionary with trace_id, span_id, and trace_flags
    """
    span = trace.get_current_span()
    span_context = span.get_span_context()

    if span_context.is_valid:
        return {
            "trace_id": format(span_context.trace_id, "032x"),
            "span_id": format(span_context.span_id, "016x"),
            "trace_flags": str(span_context.trace_flags),
        }

    return {}


def inject_trace_context(log_record: dict) -> dict:
    """Inject current trace context into a log record.

    Args:
        log_record: Log record dictionary

    Returns:
        Log record with trace context
    """
    trace_context = get_current_trace_context()
    if trace_context:
        log_record.update(trace_context)
    return log_record


def build_apm_correlation_link(trace_id: str) -> str:
    """Build a link to OCI APM trace explorer.

    Args:
        trace_id: Trace ID

    Returns:
        URL to trace in APM console
    """
    from src.core import settings

    if not settings.oci_apm_domain_id:
        return ""

    region = settings.oci_region or "us-ashburn-1"
    domain_id = settings.oci_apm_domain_id

    return (
        f"https://cloud.oracle.com/apm/apm-traces?"
        f"region={region}&apmDomainId={domain_id}&traceId={trace_id}"
    )


def create_correlated_log_entry(
    message: str,
    level: str = "INFO",
    extra: dict | None = None,
) -> dict:
    """Create a log entry with APM correlation.

    Args:
        message: Log message
        level: Log level
        extra: Additional fields

    Returns:
        Log entry dictionary
    """
    from datetime import datetime, timezone

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }

    # Inject trace context
    entry = inject_trace_context(entry)

    # Add APM link if trace is present
    if "trace_id" in entry:
        entry["apm_link"] = build_apm_correlation_link(entry["trace_id"])

    # Add extra fields
    if extra:
        entry.update(extra)

    return entry
