"""OCI Logging handler with APM trace correlation."""

import asyncio
import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from src.core import settings

# Standard library logger for bootstrap (before our logger is available)
_bootstrap_logger = logging.getLogger("oci.logging.handler")


class OCILoggingHandler(logging.Handler):
    """Logging handler that sends logs to OCI Logging with APM correlation."""

    def __init__(
        self,
        log_id: str,
        service_name: str = "oci-database-observatory",
        batch_size: int = 50,
        flush_interval: float = 5.0,
    ) -> None:
        """Initialize OCI Logging handler.

        Args:
            log_id: OCI Log OCID
            service_name: Service name for APM correlation
            batch_size: Number of logs to batch before sending
            flush_interval: Seconds between flushes
        """
        super().__init__()
        self.log_id = log_id
        self.service_name = service_name
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._buffer: queue.Queue = queue.Queue()
        self._loggingingestion_client = None
        self._shutdown = False
        self._flush_thread: threading.Thread | None = None

        # Start background flush thread
        self._start_flush_thread()

    @property
    def loggingingestion_client(self):
        """Lazy-load OCI Logging Ingestion client."""
        if self._loggingingestion_client is None:
            try:
                import oci
                config = oci.config.from_file(
                    file_location=settings.oci_config_file,
                    profile_name=settings.oci_profile,
                )
                self._loggingingestion_client = oci.loggingingestion.LoggingClient(config)
            except Exception as e:
                _bootstrap_logger.error(f"Failed to create OCI Logging Ingestion client: {e}")
        return self._loggingingestion_client

    def _start_flush_thread(self) -> None:
        """Start the background flush thread."""
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="oci-logging-flush",
        )
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background loop that flushes logs periodically."""
        while not self._shutdown:
            try:
                time.sleep(self.flush_interval)
                self._flush()
            except Exception as e:
                _bootstrap_logger.error(f"Error in flush loop: {e}")

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the buffer.

        Args:
            record: Log record
        """
        try:
            log_entry = self._format_log_entry(record)
            self._buffer.put(log_entry)

            # Flush if buffer is full
            if self._buffer.qsize() >= self.batch_size:
                self._flush()
        except Exception:
            self.handleError(record)

    def _format_log_entry(self, record: logging.LogRecord) -> dict[str, Any]:
        """Format a log record for OCI Logging.

        Args:
            record: Log record

        Returns:
            Formatted log entry with APM correlation
        """
        # Get current trace context
        span = trace.get_current_span()
        span_context = span.get_span_context()

        # Build log entry
        entry = {
            "datetime": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "logContent": {
                "message": self.format(record),
                "level": record.levelname,
                "logger": record.name,
                "service": self.service_name,
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            },
        }

        # Add APM correlation if trace is active
        if span_context.is_valid:
            entry["logContent"]["traceId"] = format(span_context.trace_id, "032x")
            entry["logContent"]["spanId"] = format(span_context.span_id, "016x")
            entry["logContent"]["traceFlags"] = span_context.trace_flags

        # Add extra fields if present
        if hasattr(record, "extra") and record.extra:
            entry["logContent"]["extra"] = record.extra

        return entry

    def _flush(self) -> None:
        """Flush buffered logs to OCI Logging."""
        if self._buffer.empty():
            return

        # Collect entries from buffer
        entries = []
        while not self._buffer.empty() and len(entries) < self.batch_size:
            try:
                entries.append(self._buffer.get_nowait())
            except queue.Empty:
                break

        if not entries:
            return

        # Send to OCI Logging
        try:
            self._send_logs(entries)
        except Exception as e:
            _bootstrap_logger.error(f"Failed to send logs to OCI: {e}")
            # Re-queue failed entries
            for entry in entries:
                self._buffer.put(entry)

    def _send_logs(self, entries: list[dict]) -> None:
        """Send log entries to OCI Logging.

        Args:
            entries: Log entries to send
        """
        if not self.loggingingestion_client:
            return

        try:
            import oci.loggingingestion.models as models

            log_entries = [
                models.LogEntry(
                    data=json.dumps(entry["logContent"]),
                    id=f"{entry['datetime']}-{hash(entry['logContent']['message']) % 10000:04d}",
                    time=entry["datetime"],
                )
                for entry in entries
            ]

            put_logs_details = models.PutLogsDetails(
                specversion="1.0",
                log_entry_batches=[
                    models.LogEntryBatch(
                        entries=log_entries,
                        source=self.service_name,
                        type="com.oraclecloud.logging.custom.oci-database-observatory",
                        defaultlogentrytime=datetime.now(timezone.utc).isoformat(),
                    )
                ],
            )

            self.loggingingestion_client.put_logs(
                log_id=self.log_id,
                put_logs_details=put_logs_details,
            )

            _bootstrap_logger.debug(f"Sent {len(entries)} logs to OCI Logging")

        except Exception as e:
            _bootstrap_logger.error(f"Error sending logs to OCI: {e}")
            raise

    def close(self) -> None:
        """Close the handler and flush remaining logs."""
        self._shutdown = True
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
        self._flush()
        super().close()


def create_oci_logging_handler(
    log_id: str,
    service_name: str = "oci-database-observatory",
) -> OCILoggingHandler:
    """Create and configure an OCI Logging handler.

    Args:
        log_id: OCI Log OCID
        service_name: Service name for APM correlation

    Returns:
        Configured handler
    """
    handler = OCILoggingHandler(
        log_id=log_id,
        service_name=service_name,
    )
    handler.setLevel(logging.INFO)

    # JSON formatter for structured logs
    formatter = logging.Formatter(
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
        '"logger": "%(name)s", "message": "%(message)s"}'
    )
    handler.setFormatter(formatter)

    return handler
