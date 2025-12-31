"""OCI APM / OpenTelemetry tracing configuration.

Each component has a unique service name but shares the same APM project.
Traces are exported to OCI APM via Zipkin format (OCI APM doesn't support OTLP).
"""

import json
from typing import Sequence

import requests
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
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


class OCIAPMExporter(SpanExporter):
    """Custom span exporter for OCI APM using Zipkin format.

    OCI APM requires:
    - Zipkin v2 JSON format
    - Authorization header with data key
    - Specific URL parameters for data format
    """

    def __init__(self, endpoint: str, data_key: str, service_name: str = "unknown"):
        """Initialize OCI APM exporter.

        Args:
            endpoint: Full OCI APM endpoint URL with parameters
            data_key: OCI APM data key (public or private)
            service_name: Default service name for spans
        """
        self.endpoint = endpoint
        self.data_key = data_key
        self.service_name = service_name
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"dataKey {data_key}",
        })

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to OCI APM.

        Args:
            spans: Sequence of spans to export

        Returns:
            SpanExportResult indicating success or failure
        """
        if not spans:
            return SpanExportResult.SUCCESS

        try:
            zipkin_spans = self._convert_to_zipkin(spans)

            response = self._session.post(
                self.endpoint,
                data=json.dumps(zipkin_spans),
                timeout=30,
            )

            if response.status_code in (200, 202):
                return SpanExportResult.SUCCESS
            else:
                logger.warning(
                    "OCI APM export failed",
                    status=response.status_code,
                    response=response.text[:200],
                )
                return SpanExportResult.FAILURE

        except Exception as e:
            logger.error("OCI APM export error", error=str(e))
            return SpanExportResult.FAILURE

    def _convert_to_zipkin(self, spans: Sequence[ReadableSpan]) -> list[dict]:
        """Convert OpenTelemetry spans to Zipkin v2 format.

        Args:
            spans: OpenTelemetry spans

        Returns:
            List of Zipkin span dicts
        """
        zipkin_spans = []

        for span in spans:
            ctx = span.get_span_context()

            # Convert trace and span IDs to hex strings
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")

            # Get parent span ID if exists
            parent_id = None
            if span.parent and span.parent.span_id:
                parent_id = format(span.parent.span_id, "016x")

            # Build Zipkin span
            zipkin_span = {
                "traceId": trace_id,
                "id": span_id,
                "name": span.name,
                "timestamp": span.start_time // 1000,  # Convert ns to microseconds
                "duration": (span.end_time - span.start_time) // 1000,
                "localEndpoint": {
                    "serviceName": self._get_service_name(span),
                },
            }

            if parent_id:
                zipkin_span["parentId"] = parent_id

            # Add tags from attributes
            if span.attributes:
                zipkin_span["tags"] = {
                    str(k): str(v) for k, v in span.attributes.items()
                }

            # Add span kind
            if span.kind:
                zipkin_span["kind"] = span.kind.name

            zipkin_spans.append(zipkin_span)

        return zipkin_spans

    def _get_service_name(self, span: ReadableSpan) -> str:
        """Extract service name from span resource."""
        if span.resource and span.resource.attributes:
            svc = span.resource.attributes.get("service.name")
            if svc:
                return str(svc)
        return self.service_name

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        self._session.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush is a no-op for this exporter."""
        return True


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


def _build_oci_apm_endpoint(base_url: str, use_public: bool = True) -> str:
    """Build the OCI APM endpoint URL with required parameters.

    OCI APM requires Zipkin format with specific URL parameters.

    Args:
        base_url: OCI APM data upload endpoint base URL
        use_public: Use public (True) or private (False) endpoint

    Returns:
        Full endpoint URL with parameters
    """
    endpoint_type = "public-span" if use_public else "private-span"
    return f"{base_url}/20200101/observations/{endpoint_type}?dataFormat=zipkin&dataFormatVersion=2"


def init_tracing(
    service_name: str | None = None,
    component: str = "api",
) -> trace.Tracer:
    """Initialize OpenTelemetry tracing with OCI APM export.

    OCI APM uses Zipkin format for trace ingestion. The exporter is configured
    to send traces to the OCI APM public endpoint using the public data key.

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
        ResourceAttributes.SERVICE_VERSION: "0.2.0",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.environment,
        "oci.apm.project": "oci-database-observatory",
    })

    # Create tracer provider
    _provider = TracerProvider(resource=resource)

    # Get APM configuration - prefer public key for Zipkin
    apm_base_url = getattr(settings, 'oci_apm_data_upload_endpoint', None)
    apm_public_key = settings.oci_apm_public_key
    apm_private_key = settings.oci_apm_private_key

    # Build the endpoint URL
    if apm_base_url and (apm_public_key or apm_private_key):
        # Use public endpoint with public key (preferred)
        use_public = bool(apm_public_key)
        data_key = apm_public_key if use_public else apm_private_key

        endpoint = _build_oci_apm_endpoint(apm_base_url, use_public)

        # Create custom OCI APM exporter
        exporter = OCIAPMExporter(
            endpoint=endpoint,
            data_key=data_key,
            service_name=svc_name,
        )

        _provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "OCI APM tracing enabled",
            service=svc_name,
            endpoint=endpoint[:60] + "...",
            key_type="public" if use_public else "private",
        )
    else:
        logger.warning(
            "OCI APM endpoint not configured, traces will not be exported",
            service=svc_name,
            help="Set OCI_APM_DATA_UPLOAD_ENDPOINT and OCI_APM_PUBLIC_DATA_KEY",
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
    tracer = trace.get_tracer(svc_name, "0.2.0")

    logger.info("Tracing initialized", service=svc_name)
    return tracer


def shutdown_tracing() -> None:
    """Shutdown tracing and flush pending spans."""
    global _provider
    if _provider:
        # Force flush all pending spans before shutdown
        # This ensures traces are exported even on quick process termination
        try:
            _provider.force_flush(timeout_millis=5000)
            logger.info("Tracing force flush complete")
        except Exception as e:
            logger.warning("Tracing force flush failed", error=str(e))

        _provider.shutdown()
        logger.info("Tracing shutdown complete")


def force_flush_traces(timeout_ms: int = 5000) -> bool:
    """Force flush pending traces without shutdown.

    Call this after important operations to ensure traces are exported.

    Args:
        timeout_ms: Maximum time to wait for flush

    Returns:
        True if flush succeeded
    """
    global _provider
    if _provider:
        try:
            return _provider.force_flush(timeout_millis=timeout_ms)
        except Exception:
            return False
    return True


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
