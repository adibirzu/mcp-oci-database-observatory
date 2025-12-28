"""Structured logging configuration using structlog."""

import logging
import sys

import structlog

from .config import settings


def configure_logging() -> None:
    """Configure structlog for structured JSON logging."""

    # Determine if we should use pretty printing (dev) or JSON (prod)
    is_dev = settings.environment == "development"

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if is_dev:
        processors.extend([
            structlog.dev.ConsoleRenderer(colors=True),
        ])
    else:
        processors.extend([
            structlog.processors.JSONRenderer(),
        ])

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
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
