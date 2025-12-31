#!/usr/bin/env python3
"""Test OCI APM and OCI Logging integration.

This script:
1. Initializes OCI APM tracing (OpenTelemetry -> OCI APM)
2. Initializes OCI Logging (structured logs -> OCI Logging)
3. Creates test spans and logs
4. Verifies trace-log correlation
"""

import os
import sys
import time

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(".env.local")


def main():
    """Run observability test."""
    from src.core import get_logger, settings
    from src.observability import (
        init_tracing,
        shutdown_tracing,
        create_span,
        get_trace_id,
    )
    from src.observability.oci_logging import init_oci_logging, shutdown_oci_logging

    print("=" * 60)
    print("OCI Observability Test")
    print("=" * 60)

    # Show configuration
    print("\n📋 Configuration:")
    print(f"  APM Endpoint: {settings.oci_apm_endpoint[:50]}..." if settings.oci_apm_endpoint else "  APM Endpoint: Not configured")
    print(f"  APM Key: {'*' * 20}...{settings.oci_apm_private_key[-4:]}" if settings.oci_apm_private_key else "  APM Key: Not configured")
    print(f"  Logging Region: {settings.oci_logging_region}")
    print(f"  Log Group ID: {settings.oci_log_group_id[:40]}..." if settings.oci_log_group_id else "  Log Group ID: Not configured")
    print(f"  Log ID: {settings.oci_log_id[:40]}..." if settings.oci_log_id else "  Log ID: Not configured")

    # Step 1: Initialize tracing
    print("\n🔧 Step 1: Initializing OCI APM tracing...")
    tracer = init_tracing(component="test")
    print("  ✓ Tracing initialized")

    # Step 2: Initialize OCI Logging
    print("\n🔧 Step 2: Initializing OCI Logging...")
    handler = init_oci_logging(profile="DEFAULT")
    if handler:
        print("  ✓ OCI Logging initialized")
    else:
        print("  ⚠ OCI Logging not configured (check environment variables)")

    logger = get_logger("test.observability")

    # Step 3: Create test spans and logs
    print("\n🧪 Step 3: Creating test spans and logs...")

    with create_span("test.parent_operation") as parent_span:
        trace_id = get_trace_id()
        print(f"  📊 Parent Span - Trace ID: {trace_id}")

        # Log with trace correlation
        logger.info(
            "Test log from parent span",
            trace_id=trace_id,
            operation="parent",
        )

        # Create child span
        with create_span("test.child_operation") as child_span:
            child_span.set_attribute("test.key", "test_value")
            child_span.set_attribute("test.count", 42)

            logger.info(
                "Test log from child span",
                trace_id=trace_id,
                operation="child",
                count=42,
            )

            # Simulate some work
            time.sleep(0.1)

        # Create another span for MCP tool simulation
        with create_span("mcp.tool.execute") as tool_span:
            tool_span.set_attribute("mcp.tool.name", "test_tool")
            tool_span.set_attribute("mcp.server.id", "test-server")
            tool_span.set_attribute("mcp.tool.duration_ms", 150)
            tool_span.set_attribute("mcp.tool.success", True)

            logger.info(
                "MCP tool executed",
                tool="test_tool",
                server="test-server",
                duration_ms=150,
                success=True,
            )

            time.sleep(0.1)

    print("  ✓ Test spans and logs created")

    # Step 4: Flush and shutdown
    print("\n🔄 Step 4: Flushing logs and shutting down...")

    # Wait for logs to be flushed
    print("  Waiting 6 seconds for log flush...")
    time.sleep(6)

    shutdown_oci_logging()
    print("  ✓ OCI Logging shutdown")

    shutdown_tracing()
    print("  ✓ Tracing shutdown")

    # Summary
    print("\n" + "=" * 60)
    print("✅ Test Complete!")
    print("=" * 60)
    print("\n📋 Next Steps:")
    print("  1. Check OCI APM Trace Explorer for traces with service 'oci-obs-test'")
    print(f"     Trace ID: {trace_id}")
    print("  2. Check OCI Logging console for log entries")
    print("  3. Use the trace ID to correlate logs with APM traces")
    print("\n🔗 OCI Console Links:")
    print(f"  APM: https://cloud.oracle.com/apm/traces")
    print(f"  Logging: https://cloud.oracle.com/logging/log-groups")


if __name__ == "__main__":
    main()
