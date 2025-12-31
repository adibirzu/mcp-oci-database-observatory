"""Structured logging configuration using structlog."""

import logging
import os
import sys

import structlog

from .config import settings


def configure_logging() -> None:
    """Configure structlog for structured JSON logging.

    IMPORTANT: For MCP stdio transport compatibility, all logs MUST go to stderr.
    stdout is reserved exclusively for JSON-RPC protocol messages.
    """

    # Determine if we should use pretty printing (dev) or JSON (prod)
    is_dev = settings.environment == "development"

    # Check if running in MCP mode (stdio transport)
    is_mcp_stdio = os.getenv("MCP_TRANSPORT", "").lower() == "stdio"

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if is_dev and not is_mcp_stdio:
        processors.extend([
            structlog.dev.ConsoleRenderer(colors=True),
        ])
    else:
        # Use JSON in production or when in MCP stdio mode
        processors.extend([
            structlog.processors.JSONRenderer(),
        ])

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        # CRITICAL: Use stderr for MCP stdio compatibility
        # stdout is reserved for JSON-RPC messages
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance with optional name binding."""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(component=name)
    return logger


# Configure on import
configure_logging()
