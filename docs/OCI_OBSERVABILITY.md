# OCI Observability Setup Guide

This guide covers setting up OCI Application Performance Monitoring (APM) and OCI Logging for the MCP Database Observatory server.

## Overview

The observability stack provides:
- **Distributed Tracing**: Via OCI APM using Zipkin format
- **Centralized Logging**: Via OCI Logging with trace correlation
- **Metrics**: Tool execution, LLM calls, cache hits/misses

## Prerequisites

1. OCI tenancy with APM and Logging services enabled
2. IAM policies for APM and Logging access
3. OCI CLI configured with valid credentials

## Part 1: OCI APM Setup

### Important: OCI APM Uses Zipkin Format

OCI APM does **not** support the standard OTLP (OpenTelemetry Protocol) format. Instead, it requires **Zipkin v2 JSON format** for trace ingestion. This implementation uses a custom `OCIAPMExporter` that:
- Converts OpenTelemetry spans to Zipkin v2 format
- Uses the correct OCI APM authorization header format
- Posts to the observations endpoint with proper query parameters

### Step 1: Create APM Domain

```bash
# Using OCI CLI
oci apm-synthetics domain create \
  --compartment-id <compartment-ocid> \
  --display-name "database-observatory" \
  --is-free-tier false
```

Or via OCI Console:
1. Navigate to **Observability & Management > Application Performance Monitoring > Administration**
2. Click **Create APM Domain**
3. Name: `database-observatory`
4. Compartment: Select your compartment
5. Click **Create**

### Step 2: Get APM Data Keys

After domain creation:
1. Click on your APM domain
2. Go to **Data Keys** section
3. Copy **Private Data Key** (for server-side ingestion)
4. Copy **Public Data Key** (recommended for external services)

### Step 3: Get APM Data Upload Endpoint

The data upload endpoint base URL format is:
```
https://<domain-id>.apm-agt.{region}.oci.oraclecloud.com
```

Find your domain's endpoint in the APM domain details page.

The actual trace ingestion endpoint (built automatically by the exporter):
```
https://<domain-id>.apm-agt.{region}.oci.oraclecloud.com/20200101/observations/public-span?dataFormat=zipkin&dataFormatVersion=2
```

### Step 4: Configure Environment Variables

Add to your `.env.local`:

```bash
# OCI APM Configuration (Frankfurt region example)
# Base URL (without path - the path is added automatically)
OCI_APM_DATA_UPLOAD_ENDPOINT=https://aaaadfjywjb7saaaaaaaaacvse.apm-agt.eu-frankfurt-1.oci.oraclecloud.com

# Data keys (public key is preferred for Zipkin ingestion)
OCI_APM_PUBLIC_DATA_KEY=MFLDJCUZFX2UATCDWA3TQO4TODDR5MDQ
OCI_APM_PRIVATE_DATA_KEY=REDACTED_APM_DATAKEY

# Enable tracing
OTEL_TRACING_ENABLED=true
OTEL_SERVICE_NAME=oci-obs-mcp-server
```

**Note**: The public key is preferred for Zipkin format ingestion. The implementation will use the public key if available, otherwise falls back to the private key.

## Part 2: OCI Logging Setup

### Step 1: Create Log Group

```bash
oci logging log-group create \
  --compartment-id <compartment-ocid> \
  --display-name "oci-database-observatory"
```

Or via OCI Console:
1. Navigate to **Observability & Management > Logging > Log Groups**
2. Click **Create Log Group**
3. Name: `oci-database-observatory`
4. Description: MCP Server application logs
5. Click **Create**

### Step 2: Create Custom Log

```bash
oci logging log create \
  --log-group-id <log-group-ocid> \
  --display-name "mcp-server-logs" \
  --log-type "CUSTOM" \
  --is-enabled true
```

Or via OCI Console:
1. Click on your log group
2. Click **Create Custom Log**
3. Name: `mcp-server-logs`
4. Click **Create Custom Log**
5. Skip agent configuration (we use direct ingestion)

### Step 3: Configure Environment Variables

Add to your `.env.local`:

```bash
# OCI Logging Configuration (Frankfurt region example)
OCI_LOGGING_ENABLED=true
OCI_LOG_GROUP_ID=ocid1.loggroup.oc1..example
OCI_LOG_ID=ocid1.log.oc1..example
OCI_LOGGING_REGION=eu-frankfurt-1
```

The logging endpoint is automatically derived from the region:
```
https://ingestion.logging.{region}.oci.oraclecloud.com
```

### Step 4: Required IAM Policies

For the OCI user/group running the MCP server:

```
Allow group <your-group> to use log-groups in compartment <compartment>
Allow group <your-group> to use logs in compartment <compartment>
Allow group <your-group> to use apm-domains in compartment <compartment>
```

## Part 3: Verification

### Test APM Connection

```python
from src.observability import init_tracing, create_span, shutdown_tracing

# Initialize tracing
init_tracing(component="api")

# Create a test span
with create_span("test.verification") as span:
    span.set_attribute("test.key", "test.value")
    trace_id = format(span.get_span_context().trace_id, '032x')
    print(f"Trace ID: {trace_id}")

# Flush pending spans
shutdown_tracing()
```

After running, check OCI APM Console:
1. Navigate to **Trace Explorer**
2. Filter by service name: `oci-obs-api`
3. Look for `test.verification` spans
4. Verify attributes are present

### Test OCI Logging Connection

```python
from src.observability.oci_logging import init_oci_logging, shutdown_oci_logging
from src.core import get_logger

# Initialize OCI Logging
init_oci_logging()

# Log a test message
logger = get_logger("test")
logger.info("Test log message", test_key="test_value")

# Flush logs
shutdown_oci_logging()
```

After running, check OCI Logging Console:
1. Navigate to **Logs** under your log group
2. Click **Explore with Log Search**
3. Look for your test message

### Test Trace-Log Correlation

```python
from src.observability import init_tracing, create_span, get_trace_id, shutdown_tracing
from src.observability.oci_logging import init_oci_logging, shutdown_oci_logging
from src.core import get_logger

# Initialize both (tracing first!)
init_tracing(component="api")
init_oci_logging()

logger = get_logger("test")

with create_span("test.correlation") as span:
    trace_id = get_trace_id()
    logger.info("Log with trace correlation", trace_id=trace_id)

# Shutdown
shutdown_oci_logging()
shutdown_tracing()
```

In OCI Logging, search for logs with the trace ID:
```
data.trace_id = "<your-trace-id>"
```

### Run Full Integration Test

```bash
# From the project root
PYTHONPATH=. python scripts/test_mcp_observability.py
```

This test:
1. Initializes both APM and Logging
2. Simulates tool executions with traces
3. Verifies logs are correlated with trace IDs
4. Outputs trace IDs for verification in OCI Console

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `OCI_APM_DATA_UPLOAD_ENDPOINT` | Yes (for APM) | APM domain base URL (without path) |
| `OCI_APM_PUBLIC_DATA_KEY` | Recommended | APM public data key (preferred for Zipkin) |
| `OCI_APM_PRIVATE_DATA_KEY` | Yes (if no public) | APM private data key |
| `OCI_APM_DOMAIN_ID` | No | APM domain OCID |
| `OTEL_TRACING_ENABLED` | No | Enable/disable tracing (default: true) |
| `OTEL_SERVICE_NAME` | No | Service name for traces (default: oci-obs-api) |
| `OCI_LOGGING_ENABLED` | No | Enable/disable logging (default: true) |
| `OCI_LOG_GROUP_ID` | Yes (for Logging) | Log Group OCID |
| `OCI_LOG_ID` | Yes (for Logging) | Custom Log OCID |
| `OCI_LOGGING_REGION` | Yes (for Logging) | OCI region for logging endpoint |

## Architecture: Custom OCI APM Exporter

The `OCIAPMExporter` class in `src/observability/tracing.py` implements a custom OpenTelemetry `SpanExporter` that:

1. **Converts spans to Zipkin format**: OpenTelemetry uses a different internal span format. The exporter converts each span to Zipkin v2 JSON.

2. **Uses correct authorization**: OCI APM requires `Authorization: dataKey <key>` header format.

3. **Posts to correct endpoint**: Builds the full endpoint URL with required query parameters:
   ```
   {base_url}/20200101/observations/{public|private}-span?dataFormat=zipkin&dataFormatVersion=2
   ```

### Zipkin Span Format

Each span is converted to this format:
```json
{
  "traceId": "32-character-hex",
  "id": "16-character-hex",
  "parentId": "16-character-hex (optional)",
  "name": "span.name",
  "timestamp": 1704067200000000,
  "duration": 100000,
  "localEndpoint": {
    "serviceName": "oci-obs-mcp-executor"
  },
  "tags": {
    "attribute.key": "attribute.value"
  },
  "kind": "SERVER"
}
```

## Troubleshooting

### No Traces in APM

1. Verify `OCI_APM_DATA_UPLOAD_ENDPOINT` is correct (base URL without path)
2. Check `OCI_APM_PUBLIC_DATA_KEY` or `OCI_APM_PRIVATE_DATA_KEY` is valid
3. Ensure `OTEL_TRACING_ENABLED=true`
4. Check application logs for "OCI APM export failed" messages
5. Verify network connectivity to APM endpoint
6. Test with curl:
   ```bash
   curl -X POST \
     "https://your-domain.apm-agt.region.oci.oraclecloud.com/20200101/observations/public-span?dataFormat=zipkin&dataFormatVersion=2" \
     -H "Content-Type: application/json" \
     -H "Authorization: dataKey YOUR_PUBLIC_KEY" \
     -d '[{"traceId":"test123","id":"span456","name":"test","timestamp":1704067200000000,"duration":1000}]'
   ```
   Expected: HTTP 200 or 202

### OTLP 404 Error

If you see `Failed to export span batch code: 404`:
- This means the standard OTLP exporter is being used instead of the custom Zipkin exporter
- OCI APM does NOT support OTLP protocol
- Verify `OCI_APM_DATA_UPLOAD_ENDPOINT` is set (triggers Zipkin exporter)
- Check that `tracing.py` is using `OCIAPMExporter`

### No Logs in OCI Logging

1. Verify `OCI_LOG_GROUP_ID` and `OCI_LOG_ID` are correct
2. Check IAM policies allow log ingestion
3. Wait for flush interval (5 seconds)
4. Check application console for OCI Logging errors
5. Verify `OCI_LOGGING_REGION` matches your log group region

### Trace-Log Correlation Not Working

1. Ensure tracing is initialized BEFORE OCI Logging
2. Verify logs are generated within a span context
3. Check `trace_id` field in log entries
4. Use `get_trace_id()` to get current trace ID

## Best Practices

### Production Configuration

```bash
# Production .env
NODE_ENV=production
LOG_LEVEL=info

# APM - use dedicated domain for production
OCI_APM_DATA_UPLOAD_ENDPOINT=https://prod.apm-agt.us-ashburn-1.oci.oraclecloud.com
OCI_APM_PUBLIC_DATA_KEY=<prod-key>

# Logging - use dedicated log group
OCI_LOG_GROUP_ID=ocid1.loggroup.oc1..prod...
OCI_LOG_ID=ocid1.log.oc1..prod...
OCI_LOGGING_REGION=us-ashburn-1
```

### Sampling for High Volume

For high-throughput environments, consider implementing sampling:

```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

# Sample 10% of traces
sampler = TraceIdRatioBased(0.1)
```

### Log Retention

Configure log retention in OCI Console:
1. Navigate to your Log Group
2. Edit settings
3. Set retention period (30, 60, 90, 180 days)

### Cost Optimization

- Use appropriate sampling rates for traces
- Set log retention based on compliance needs
- Use log archiving for long-term storage
- Monitor APM domain usage in OCI Console
- Use public key (preferred) to avoid private key exposure

## Service Names

The following service names are used for different components:

| Component | Service Name |
|-----------|--------------|
| API Server | `oci-obs-api` |
| Coordinator | `oci-obs-coordinator` |
| Oracle Agent | `oci-obs-agent-oracle` |
| MySQL Agent | `oci-obs-agent-mysql` |
| PostgreSQL Agent | `oci-obs-agent-postgres` |
| MCP Executor | `oci-obs-mcp-executor` |
| LLM Router | `oci-obs-llm-router` |

These are defined in `src/observability/tracing.py:SERVICE_NAMES`.
