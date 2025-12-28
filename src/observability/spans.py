"""Span creation helpers for consistent trace instrumentation."""

from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from src.core import get_logger

from .tracing import get_tracer

logger = get_logger("observability.spans")

P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def create_span(
    name: str,
    component: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """Context manager to create a span with consistent naming.

    Args:
        name: Span name (e.g., "agent.execute", "mcp.tool.call")
        component: Component for tracer selection
        kind: Span kind (INTERNAL, CLIENT, SERVER, etc.)
        attributes: Initial span attributes

    Yields:
        Active span instance
    """
    tracer = get_tracer(component)

    with tracer.start_as_current_span(
        name,
        kind=kind,
        attributes=attributes or {},
    ) as span:
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def span(
    name: str | None = None,
    component: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to wrap a function in a span.

    Args:
        name: Span name (defaults to function name)
        component: Component for tracer selection
        kind: Span kind

    Returns:
        Decorated function
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with create_span(span_name, component, kind) as s:
                # Add function arguments as attributes (limited)
                if kwargs:
                    for key, value in list(kwargs.items())[:5]:
                        if isinstance(value, (str, int, float, bool)):
                            s.set_attribute(f"arg.{key}", value)

                result = func(*args, **kwargs)
                return result

        return wrapper

    return decorator


async def async_span(
    name: str | None = None,
    component: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Async decorator to wrap a coroutine in a span.

    Args:
        name: Span name (defaults to function name)
        component: Component for tracer selection
        kind: Span kind

    Returns:
        Decorated async function
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with create_span(span_name, component, kind) as s:
                if kwargs:
                    for key, value in list(kwargs.items())[:5]:
                        if isinstance(value, (str, int, float, bool)):
                            s.set_attribute(f"arg.{key}", value)

                result = await func(*args, **kwargs)
                return result

        return wrapper

    return decorator


def get_current_span() -> Span:
    """Get the current active span."""
    return trace.get_current_span()


def add_event(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Add an event to the current span."""
    span = get_current_span()
    if span and span.is_recording():
        span.add_event(name, attributes or {})


def set_attribute(key: str, value: Any) -> None:
    """Set an attribute on the current span."""
    span = get_current_span()
    if span and span.is_recording():
        span.set_attribute(key, value)
