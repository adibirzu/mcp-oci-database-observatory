"""Custom metrics for observatory monitoring."""

from typing import Any

from .spans import add_event, get_current_span, set_attribute


def record_tool_execution(
    tool_name: str,
    server_id: str,
    duration_ms: int,
    success: bool,
    cached: bool = False,
) -> None:
    """Record metrics for MCP tool execution.

    Args:
        tool_name: Name of the tool executed
        server_id: MCP server identifier
        duration_ms: Execution duration in milliseconds
        success: Whether execution succeeded
        cached: Whether result was from cache
    """
    span = get_current_span()
    if span and span.is_recording():
        span.set_attribute("mcp.tool.name", tool_name)
        span.set_attribute("mcp.server.id", server_id)
        span.set_attribute("mcp.tool.duration_ms", duration_ms)
        span.set_attribute("mcp.tool.success", success)
        span.set_attribute("mcp.tool.cached", cached)

        add_event(
            "mcp.tool.executed",
            {
                "tool": tool_name,
                "server": server_id,
                "duration_ms": duration_ms,
                "success": success,
                "cached": cached,
            },
        )


def record_llm_request(
    provider: str,
    model: str,
    duration_ms: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    success: bool = True,
) -> None:
    """Record metrics for LLM request.

    Args:
        provider: LLM provider name
        model: Model identifier
        duration_ms: Request duration in milliseconds
        input_tokens: Number of input tokens (if available)
        output_tokens: Number of output tokens (if available)
        success: Whether request succeeded
    """
    span = get_current_span()
    if span and span.is_recording():
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.request.duration_ms", duration_ms)
        span.set_attribute("llm.request.success", success)

        if input_tokens is not None:
            span.set_attribute("llm.tokens.input", input_tokens)
        if output_tokens is not None:
            span.set_attribute("llm.tokens.output", output_tokens)

        add_event(
            "llm.request.completed",
            {
                "provider": provider,
                "model": model,
                "duration_ms": duration_ms,
                "input_tokens": input_tokens or 0,
                "output_tokens": output_tokens or 0,
                "success": success,
            },
        )


def record_cache_hit(
    cache_type: str,
    key: str,
    hit: bool,
    ttl_remaining_ms: int | None = None,
) -> None:
    """Record cache lookup metrics.

    Args:
        cache_type: Type of cache (tool_result, semantic, etc.)
        key: Cache key (truncated)
        hit: Whether cache hit occurred
        ttl_remaining_ms: Remaining TTL if hit
    """
    span = get_current_span()
    if span and span.is_recording():
        span.set_attribute("cache.type", cache_type)
        span.set_attribute("cache.hit", hit)

        if ttl_remaining_ms is not None:
            span.set_attribute("cache.ttl_remaining_ms", ttl_remaining_ms)

        add_event(
            "cache.lookup",
            {
                "type": cache_type,
                "key": key[:50],  # Truncate key
                "hit": hit,
            },
        )


def record_agent_execution(
    agent_type: str,
    task_id: str,
    duration_ms: int,
    tools_used: list[str],
    findings_count: int,
    success: bool,
) -> None:
    """Record metrics for agent task execution.

    Args:
        agent_type: Type of agent (oracle, mysql, postgres)
        task_id: Task identifier
        duration_ms: Execution duration in milliseconds
        tools_used: List of tools used
        findings_count: Number of findings
        success: Whether execution succeeded
    """
    span = get_current_span()
    if span and span.is_recording():
        span.set_attribute("agent.type", agent_type)
        span.set_attribute("agent.task.id", task_id)
        span.set_attribute("agent.task.duration_ms", duration_ms)
        span.set_attribute("agent.task.tools_count", len(tools_used))
        span.set_attribute("agent.task.findings_count", findings_count)
        span.set_attribute("agent.task.success", success)

        add_event(
            "agent.task.completed",
            {
                "agent_type": agent_type,
                "task_id": task_id,
                "duration_ms": duration_ms,
                "tools": tools_used[:10],  # Limit list size
                "findings_count": findings_count,
                "success": success,
            },
        )


def record_query_processing(
    query: str,
    intent: str,
    database_type: str,
    agents_invoked: list[str],
    total_duration_ms: int,
) -> None:
    """Record metrics for end-to-end query processing.

    Args:
        query: User query (truncated)
        intent: Detected intent
        database_type: Target database type
        agents_invoked: List of agents that processed the query
        total_duration_ms: Total processing time
    """
    set_attribute("query.text", query[:100])  # Truncate
    set_attribute("query.intent", intent)
    set_attribute("query.database_type", database_type)
    set_attribute("query.agents_count", len(agents_invoked))
    set_attribute("query.total_duration_ms", total_duration_ms)

    add_event(
        "query.completed",
        {
            "intent": intent,
            "database_type": database_type,
            "agents": agents_invoked,
            "duration_ms": total_duration_ms,
        },
    )
