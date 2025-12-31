"""OCI Logging integration with APM trace correlation.

Sends structured logs to OCI Logging service with automatic
trace ID injection from OpenTelemetry context.
"""

import asyncio
import json
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from src.core import get_logger, settings

logger = get_logger("observability.oci_logging")

# Batch settings
BATCH_SIZE = 50
FLUSH_INTERVAL_SECONDS = 5.0
MAX_MESSAGE_SIZE = 32768  # 32KB per log entry


class OCILoggingHandler(logging.Handler):
    """Python logging handler that sends logs to OCI Logging service.

    Features:
    - Automatic APM trace ID correlation
    - Batched log submission for efficiency
    - Background thread for async sending
    - Structured JSON log format
    - Graceful degradation on OCI errors
    """

    def __init__(
        self,
        log_group_id: str | None = None,
        log_id: str | None = None,
        profile: str = "DEFAULT",
    ):
        super().__init__()
        self.log_group_id = log_group_id or settings.oci_log_group_id
        self.log_id = log_id or settings.oci_log_id
        self.profile = profile

        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10000)
        self._shutdown = threading.Event()
        self._flush_thread: threading.Thread | None = None
        self._loggingingestion_client = None

        # Initialize OCI client if configured
        if self.log_group_id and self.log_id:
            self._init_oci_client()
            self._start_flush_thread()
        else:
            logger.warning(
                "OCI Logging not configured - logs will not be sent to OCI",
                log_group_id=self.log_group_id,
                log_id=self.log_id,
            )

    def _init_oci_client(self) -> None:
        """Initialize OCI Logging Ingestion client with regional endpoint."""
        try:
            import oci
            from oci.loggingingestion import LoggingClient

            config = oci.config.from_file(profile_name=self.profile)

            # Use region-specific endpoint for Logging Ingestion
            region = settings.oci_logging_region
            service_endpoint = f"https://ingestion.logging.{region}.oci.oraclecloud.com"

            self._loggingingestion_client = LoggingClient(
                config,
                service_endpoint=service_endpoint,
            )

            logger.info(
                "OCI Logging client initialized",
                region=region,
                endpoint=service_endpoint,
                log_group_id=self.log_group_id[:30] + "..." if self.log_group_id else None,
            )
        except Exception as e:
            logger.error("Failed to initialize OCI Logging client", error=str(e))
            self._loggingingestion_client = None

    def _start_flush_thread(self) -> None:
        """Start background thread for batch flushing."""
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="oci-logging-flush",
        )
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background loop that flushes logs periodically."""
        while not self._shutdown.is_set():
            try:
                self._flush_batch()
            except Exception as e:
                logger.error("Error in flush loop", error=str(e))

            self._shutdown.wait(FLUSH_INTERVAL_SECONDS)

        # Final flush on shutdown
        self._flush_batch()

    def _flush_batch(self) -> None:
        """Flush queued log entries to OCI Logging."""
        if not self._loggingingestion_client:
            # Drain queue if no client
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            return

        entries = []
        while len(entries) < BATCH_SIZE and not self._queue.empty():
            try:
                entries.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not entries:
            return

        try:
            from oci.loggingingestion.models import LogEntry, LogEntryBatch, PutLogsDetails

            log_entries = [
                LogEntry(
                    data=json.dumps(entry["data"])[:MAX_MESSAGE_SIZE],
                    id=entry["id"],
                    time=entry["time"],
                )
                for entry in entries
            ]

            batch = LogEntryBatch(
                entries=log_entries,
                source="oci-database-observatory",
                type="mcp-server",
                subject=settings.otel_service_name,
                defaultlogentrytime=datetime.now(timezone.utc).isoformat(),
            )

            put_logs_details = PutLogsDetails(
                specversion="1.0",
                log_entry_batches=[batch],
            )

            self._loggingingestion_client.put_logs(
                log_id=self.log_id,
                put_logs_details=put_logs_details,
            )

            logger.debug("Flushed logs to OCI", count=len(entries))

        except Exception as e:
            logger.error("Failed to send logs to OCI", error=str(e), count=len(entries))

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the OCI queue.

        Injects trace context from OpenTelemetry for APM correlation.
        """
        try:
            # Get trace context
            span = trace.get_current_span()
            span_context = span.get_span_context() if span else None

            # Build structured log entry
            log_data: dict[str, Any] = {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "component": getattr(record, "component", None),
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
            }

            # Add APM trace correlation
            if span_context and span_context.is_valid:
                log_data["trace_id"] = format(span_context.trace_id, "032x")
                log_data["span_id"] = format(span_context.span_id, "016x")
                log_data["trace_flags"] = span_context.trace_flags

            # Add exception info if present
            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)

            # Add any extra fields from structlog
            for key in ["event", "tool", "server", "duration_ms", "success"]:
                if hasattr(record, key):
                    log_data[key] = getattr(record, key)

            entry = {
                "id": f"{record.created}-{id(record)}",
                "time": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "data": log_data,
            }

            # Non-blocking queue put
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                # Drop oldest entries if queue is full
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(entry)
                except queue.Empty:
                    pass

        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Shutdown the handler and flush remaining logs."""
        self._shutdown.set()
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=10.0)
        super().close()


# Global handler instance
_oci_handler: OCILoggingHandler | None = None


def init_oci_logging(profile: str = "DEFAULT") -> OCILoggingHandler | None:
    """Initialize OCI Logging handler and attach to root logger.

    Args:
        profile: OCI config profile to use

    Returns:
        Handler instance or None if disabled
    """
    global _oci_handler

    if not settings.oci_logging_enabled:
        logger.info("OCI Logging disabled by configuration")
        return None

    if not settings.oci_log_group_id or not settings.oci_log_id:
        logger.warning(
            "OCI Logging OCIDs not configured",
            help="Set OCI_LOG_GROUP_ID and OCI_LOG_ID environment variables",
        )
        return None

    _oci_handler = OCILoggingHandler(profile=profile)

    # Attach to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(_oci_handler)

    logger.info(
        "OCI Logging initialized",
        log_group_id=settings.oci_log_group_id[:30] + "..." if settings.oci_log_group_id else None,
        log_id=settings.oci_log_id[:30] + "..." if settings.oci_log_id else None,
    )

    return _oci_handler


def shutdown_oci_logging() -> None:
    """Shutdown OCI Logging handler."""
    global _oci_handler

    if _oci_handler:
        _oci_handler.close()

        # Remove from root logger
        root_logger = logging.getLogger()
        root_logger.removeHandler(_oci_handler)

        _oci_handler = None
        logger.info("OCI Logging shutdown complete")


def get_trace_id() -> str | None:
    """Get current trace ID for log correlation.

    Returns:
        Hex-encoded trace ID or None
    """
    span = trace.get_current_span()
    if span:
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    return None
