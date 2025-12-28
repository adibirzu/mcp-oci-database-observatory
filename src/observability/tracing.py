"""OCI APM / OpenTelemetry tracing configuration.

Each component has a unique service name but shares the same APM project.
Traces are exported to OCI APM via OTLP HTTP protocol.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.resource import ResourceAttributes

from src.core import get_logger, settings

# Try to import HTTPX instrumentation (class name varies by version)
try:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentation
    _httpx_instrumentation = HTTPXClientInstrumentation
except ImportError:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXInstrumentor
        _httpx_instrumentation = HTTPXInstrumentor
    except ImportError:
        _httpx_instrumentation = None

# Try to import Logging instrumentation (class name varies by version)
try:
    from opentelemetry.instrumentation.logging import LoggingInstrumentation
    _logging_instrumentation = LoggingInstrumentation
except ImportError:
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        _logging_instrumentation = LoggingInstrumentor
    except ImportError:
        _logging_instrumentation = None

logger = get_logger("observability.tracing")

# Service name constants for different components
SERVICE_NAMES = {
    "api": "oci-obs-api",
    "coordinator": "oci-obs-coordinator",
    "oracle_agent": "oci-obs-agent-oracle",
    "mysql_agent": "oci-obs-agent-mysql",
    "postgres_agent": "oci-obs-agent-postgres",
    "mcp_executor": "oci-obs-mcp-executor",
    "llm_router": "oci-obs-llm-router",
}

# Global tracer instance
tracer: trace.Tracer | None = None
_provider: TracerProvider | None = None


def init_tracing(
    service_name: str | None = None,
    component: str = "api",
) -> trace.Tracer:
    """Initialize OpenTelemetry tracing with OCI APM export.

    Args:
        service_name: Override service name (defaults to component lookup)
        component: Component type for service name lookup

    Returns:
        Configured tracer instance
    """
    global tracer, _provider

    if not settings.otel_tracing_enabled:
        logger.info("Tracing disabled by configuration")
        tracer = trace.get_tracer(__name__)
        return tracer

    # Determine service name
    svc_name = service_name or SERVICE_NAMES.get(component, settings.otel_service_name)

    # Create resource with service metadata
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: svc_name,
        ResourceAttributes.SERVICE_VERSION: "0.1.0",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.environment,
        "oci.apm.project": "oci-database-observatory",
    })

    # Create tracer provider
    _provider = TracerProvider(resource=resource)

    # Configure OCI APM exporter if endpoint is set
    if settings.oci_apm_endpoint and settings.oci_apm_private_key:
        exporter = OTLPSpanExporter(
            endpoint=settings.oci_apm_endpoint,
            headers={
                "authorization": settings.oci_apm_private_key,
            },
        )
        _provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "OCI APM tracing enabled",
            service=svc_name,
            endpoint=settings.oci_apm_endpoint[:50] + "...",
        )
    else:
        logger.warning(
            "OCI APM endpoint not configured, traces will not be exported",
            service=svc_name,
        )

    # Set as global provider
    trace.set_tracer_provider(_provider)

    # Instrument HTTP clients
    if _httpx_instrumentation:
        _httpx_instrumentation().instrument()

    # Instrument logging to include trace context
    if _logging_instrumentation:
        _logging_instrumentation().instrument()

    # Get tracer
    tracer = trace.get_tracer(svc_name, "0.1.0")

    logger.info("Tracing initialized", service=svc_name)
    return tracer


def shutdown_tracing() -> None:
    """Shutdown tracing and flush pending spans."""
    global _provider
    if _provider:
        _provider.shutdown()
        logger.info("Tracing shutdown complete")


def get_tracer(component: str | None = None) -> trace.Tracer:
    """Get a tracer for a specific component.

    Args:
        component: Component name for service identification

    Returns:
        Tracer instance
    """
    if component:
        svc_name = SERVICE_NAMES.get(component, f"oci-obs-{component}")
        return trace.get_tracer(svc_name, "0.1.0")
    return tracer or trace.get_tracer(__name__)
