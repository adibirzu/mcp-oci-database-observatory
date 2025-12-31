#!/usr/bin/env python3
"""Test MCP Server with OCI Observability.

This script:
1. Initializes observability (APM + Logging)
2. Creates an MCP server with tools
3. Executes several tools
4. Verifies traces and logs are sent to OCI
"""

import asyncio
import os
import sys
import time

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(".env.local")


async def main():
    """Run MCP observability test."""
    from src.core import get_logger, settings
    from src.observability import (
        init_tracing,
        shutdown_tracing,
        create_span,
        get_trace_id,
        record_tool_execution,
    )
    from src.observability.oci_logging import init_oci_logging, shutdown_oci_logging

    print("=" * 70)
    print("MCP Server Observability Test")
    print("=" * 70)

    # Step 1: Initialize observability
    print("\n🔧 Initializing observability...")
    init_tracing(component="mcp_executor")
    init_oci_logging(profile="DEFAULT")
    logger = get_logger("mcp.test")
    print("  ✓ OCI APM + OCI Logging initialized")

    # Step 2: Initialize MCP server
    print("\n🔧 Initializing MCP server...")
    from mcp.server.fastmcp import FastMCP
    from src.mcp_server.tools import register_all_tools

    mcp = FastMCP(name="oci-database-observatory-test")
    register_all_tools(mcp)
    print("  ✓ MCP server initialized with tools")

    # Step 3: Simulate tool executions with tracing
    print("\n🧪 Simulating tool executions...")

    trace_ids = []

    # Test 1: Simulate get_fleet_summary
    with create_span("mcp.tool.execute", component="mcp_executor") as span:
        span.set_attribute("mcp.tool.name", "get_fleet_summary")
        span.set_attribute("mcp.server.id", "oci-opsi")

        trace_id = get_trace_id()
        trace_ids.append(trace_id)

        start_time = time.time()
        logger.info("Executing tool", tool="get_fleet_summary", trace_id=trace_id)

        # Simulate work
        await asyncio.sleep(0.2)

        duration_ms = int((time.time() - start_time) * 1000)
        record_tool_execution("get_fleet_summary", "oci-opsi", duration_ms, True, False)

        logger.info(
            "Tool executed successfully",
            tool="get_fleet_summary",
            duration_ms=duration_ms,
            trace_id=trace_id,
        )
        print(f"  📊 get_fleet_summary - Trace ID: {trace_id}")

    # Test 2: Simulate search_databases
    with create_span("mcp.tool.execute", component="mcp_executor") as span:
        span.set_attribute("mcp.tool.name", "search_databases")
        span.set_attribute("mcp.server.id", "oci-opsi")
        span.set_attribute("mcp.tool.query", "prod")

        trace_id = get_trace_id()
        trace_ids.append(trace_id)

        start_time = time.time()
        logger.info("Executing tool", tool="search_databases", query="prod", trace_id=trace_id)

        await asyncio.sleep(0.15)

        duration_ms = int((time.time() - start_time) * 1000)
        record_tool_execution("search_databases", "oci-opsi", duration_ms, True, True)

        logger.info(
            "Tool executed from cache",
            tool="search_databases",
            duration_ms=duration_ms,
            cached=True,
            trace_id=trace_id,
        )
        print(f"  📊 search_databases - Trace ID: {trace_id}")

    # Test 3: Simulate list_oci_profiles
    with create_span("mcp.tool.execute", component="mcp_executor") as span:
        span.set_attribute("mcp.tool.name", "list_oci_profiles")
        span.set_attribute("mcp.server.id", "tenancy")

        trace_id = get_trace_id()
        trace_ids.append(trace_id)

        start_time = time.time()
        logger.info("Executing tool", tool="list_oci_profiles", trace_id=trace_id)

        await asyncio.sleep(0.1)

        duration_ms = int((time.time() - start_time) * 1000)
        record_tool_execution("list_oci_profiles", "tenancy", duration_ms, True, True)

        logger.info(
            "Tool executed successfully",
            tool="list_oci_profiles",
            duration_ms=duration_ms,
            profiles=["DEFAULT", "PRODUCTION"],
            trace_id=trace_id,
        )
        print(f"  📊 list_oci_profiles - Trace ID: {trace_id}")

    # Test 4: Simulate error handling
    with create_span("mcp.tool.execute", component="mcp_executor") as span:
        span.set_attribute("mcp.tool.name", "connect")
        span.set_attribute("mcp.server.id", "sqlcl")

        trace_id = get_trace_id()
        trace_ids.append(trace_id)

        start_time = time.time()
        logger.info("Executing tool", tool="connect", trace_id=trace_id)

        await asyncio.sleep(0.3)

        duration_ms = int((time.time() - start_time) * 1000)
        record_tool_execution("connect", "sqlcl", duration_ms, False, False)

        logger.warning(
            "Tool execution failed (simulated)",
            tool="connect",
            duration_ms=duration_ms,
            error="Connection timeout",
            trace_id=trace_id,
        )
        print(f"  📊 connect (failed) - Trace ID: {trace_id}")

    print("  ✓ Tool executions complete")

    # Step 4: Flush and shutdown
    print("\n🔄 Flushing logs (waiting 6 seconds)...")
    await asyncio.sleep(6)

    shutdown_oci_logging()
    shutdown_tracing()
    print("  ✓ Observability shutdown complete")

    # Summary
    print("\n" + "=" * 70)
    print("✅ Test Complete!")
    print("=" * 70)

    print("\n📋 Verification Steps:")
    print("\n1. Check OCI APM Trace Explorer:")
    print(f"   Service: oci-obs-mcp-executor")
    print("   Trace IDs:")
    for tid in trace_ids:
        print(f"     - {tid}")

    print("\n2. Check OCI Logging Console:")
    print("   Log Group: oci-database-observatory")
    print("   Search filter: data.tool = \"get_fleet_summary\"")

    print("\n3. Trace-Log Correlation:")
    print(f"   Search: data.trace_id = \"{trace_ids[0]}\"")

    print("\n🔗 Quick Links:")
    print(f"   APM: https://cloud.oracle.com/apm/traces?region={settings.oci_logging_region}")
    print(f"   Logging: https://cloud.oracle.com/logging/search?region={settings.oci_logging_region}")


if __name__ == "__main__":
    asyncio.run(main())
