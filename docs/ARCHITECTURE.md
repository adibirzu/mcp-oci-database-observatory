# MCP OCI Database Observatory - Architecture

## Overview

The MCP OCI Database Observatory is a multi-tenancy Model Context Protocol (MCP) server that provides Oracle Cloud Infrastructure database observability tools for AI agents and LLMs.

```
                                    +------------------+
                                    |   AI Agent/LLM   |
                                    |  (Claude, GPT,   |
                                    |   Gemini, OCA)   |
                                    +--------+---------+
                                             |
                                             | MCP Protocol
                                             | (JSON-RPC 2.0)
                                             v
+-----------------------------------------------------------------------------------+
|                           MCP OCI Database Observatory                             |
|                                                                                    |
|  +-------------+  +-------------+  +-------------+  +-------------+               |
|  |   OPSI      |  |   SQLcl     |  |   Logan     |  |  Tenancy    |               |
|  |   Tools     |  |   Tools     |  |   Tools     |  |   Tools     |               |
|  +------+------+  +------+------+  +------+------+  +------+------+               |
|         |                |                |                |                       |
|         +--------+-------+--------+-------+--------+-------+                       |
|                  |                |                |                               |
|  +---------------v----------------v----------------v--------------+               |
|  |                     Response Cache (File + Redis)              |               |
|  |                     - Tiered TTL (Static/Stable/RT)            |               |
|  +----------------------------------------------------------------+               |
|                                                                                    |
|  +----------------------------------------------------------------+               |
|  |                     OCI Client Manager                          |               |
|  |                     - Multi-profile support                     |               |
|  |                     - Region auto-detection                     |               |
|  +----------------------------------------------------------------+               |
|                                                                                    |
|  +----------------+  +------------------+  +-------------------+                   |
|  | OCI APM        |  | OCI Logging      |  | Tenancy Manager   |                  |
|  | (OTEL Traces)  |  | (Log Ingestion)  |  | (Profile Mgmt)    |                  |
|  +----------------+  +------------------+  +-------------------+                   |
+-----------------------------------------------------------------------------------+
                    |                |                |
                    v                v                v
          +--------+---------+  +---+----+  +--------+--------+
          |  OCI Operations  |  |  OCI   |  |   OCI Logging   |
          |    Insights      |  |  APM   |  |    Analytics    |
          +------------------+  +--------+  +-----------------+
```

## Key Components

### 1. Tool Modules (`src/mcp_server/tools/`)

| Module | Purpose | Tools |
|--------|---------|-------|
| `opsi.py` | Database performance monitoring | Fleet summary, search, CPU/memory/IO analysis, cost optimization |
| `sqlcl.py` | Direct database operations | Connect, run SQL, schema info, disconnect |
| `logan.py` | Log analytics | Query execution, log source discovery, parser listing |
| `tenancy.py` | Multi-tenancy management | Profile listing, switching, info retrieval |

### 2. Cache Layer (`src/mcp_server/cache.py`)

**Tiered TTL Strategy:**

| Tier | TTL | Use Case |
|------|-----|----------|
| STATIC | 1 hour | OCI profiles, parsers, regions |
| STABLE | 30 min | Compartments, log sources, entities |
| INFRASTRUCTURE | 10 min | Fleet summary, database list |
| ANALYSIS | 2 min | Performance metrics, queries |
| REAL_TIME | 0 | Health check, ping |

### 3. OCI Client Manager (`src/mcp_server/clients.py`)

- Lazy initialization of OCI SDK clients
- Per-profile client caching
- Region auto-detection from OCIDs
- Support for OPSI, Logging Analytics, and Database clients

### 4. Tenancy Manager (`src/mcp_server/config.py`)

- Auto-discovery of OCI profiles from `~/.oci/config`
- Profile switching during runtime
- Compartment ID resolution
- Multi-region support

## Data Flow

### Tool Execution Flow

```
1. AI Agent calls tool via MCP
2. FastMCP routes to registered tool function
3. Tool checks cache (ResponseCache)
   - Cache HIT: Return cached result (<100ms)
   - Cache MISS: Continue to step 4
4. Get OCI client for profile (OCIClientManager)
5. Execute OCI API call
6. Cache result with tier-appropriate TTL
7. Return result to AI Agent
8. Log to OCI Logging with trace ID
```

### Multi-Tenancy Flow

```
1. AI Agent calls list_oci_profiles
2. TenancyManager returns available profiles
3. AI Agent calls tool with profile="PROD"
4. Tool resolves profile to OCI config
5. OCIClientManager creates/retrieves client
6. API call executes in target tenancy
```

## Observability Stack

### OCI APM (Application Performance Monitoring)

- **Protocol**: OTLP HTTP
- **Service Names**: Per-component (oci-obs-api, oci-obs-agent-oracle, etc.)
- **Instrumentation**: Automatic for HTTP clients, manual for tool execution

### OCI Logging

- **Transport**: OCI Logging Ingestion API
- **Batching**: 50 entries per batch, 5-second flush interval
- **Correlation**: APM trace ID injected into every log entry

### Trace-Log Correlation

```json
{
  "level": "INFO",
  "message": "Tool executed",
  "trace_id": "abc123def456...",
  "span_id": "789xyz...",
  "tool": "get_fleet_summary",
  "duration_ms": 250,
  "cached": false
}
```

## Security Model

### Authentication

- OCI SDK authentication via `~/.oci/config`
- Profile-based credential isolation
- No credential storage in code

### Authorization

Required IAM policies:
```
Allow group <group> to read operations-insights-family in tenancy
Allow group <group> to read logging-analytics-family in tenancy
Allow group <group> to read database-management-family in tenancy
Allow group <group> to read compartments in tenancy
```

### Data Protection

- Sensitive data masked in logs (OCIDs truncated)
- No credential logging
- Cache entries scoped to profile
- File-based cache uses secure permissions

## Performance Characteristics

### Response Times by Tier

| Operation | Expected Time |
|-----------|---------------|
| Tier 1 (Cached) | <100ms |
| Tier 2 (API) | 1-5s |
| Tier 3 (Complex) | 5-30s |

### AI Agent Optimization

The server includes skill metadata for AI agent tool selection:

```python
SKILL_METADATA = {
    "skill_discover_databases": {
        "tier": 1,
        "tokens": 150,
        "use_when": ["list databases", "find databases"]
    }
}
```

AI agents can call `get_skill_recommendations(query)` to get optimal tool suggestions.

## Deployment Models

### Development (stdio)

```bash
python -m src.mcp_server
```

### Production (HTTP)

```bash
MCP_TRANSPORT=http MCP_HTTP_PORT=8000 python -m src.mcp_server
```

### Docker

```dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install -e .
EXPOSE 8000
CMD ["python", "-m", "src.mcp_server"]
```

## Extension Points

### Adding New Tools

1. Create tool module in `src/mcp_server/tools/`
2. Implement `register_tools(mcp: FastMCP)` function
3. Add cache tier mapping in `src/mcp_server/cache.py`
4. Register in `src/mcp_server/tools/__init__.py`

### Adding New OCI Services

1. Add client factory in `src/mcp_server/clients.py`
2. Create tool module for service
3. Add IAM policy requirements to documentation
