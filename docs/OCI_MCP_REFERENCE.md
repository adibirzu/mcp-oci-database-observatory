# OCI Database Observatory MCP Server - Tool Reference

Version: 0.2.0
Last Updated: December 2025

Complete reference for all tools provided by the OCI Database Observatory MCP server.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    AI Agent (Claude, etc.)                    │
└──────────────────────────┬───────────────────────────────────┘
                           │ JSON-RPC (stdio)
┌──────────────────────────▼───────────────────────────────────┐
│              MCP Server (oci-database-observatory)            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────────┐   │
│  │  OPSI   │ │  SQLcl  │ │  Logan  │ │     Tenancy      │   │
│  │ 15 tools│ │ 7 tools │ │13 tools │ │     8 tools      │   │
│  └────┬────┘ └────┬────┘ └────┬────┘ └───────┬──────────┘   │
│       │           │           │               │              │
│  ┌────▼───────────▼───────────▼───────────────▼────────┐    │
│  │              Response Cache (TTL-based)              │    │
│  └──────────────────────────┬──────────────────────────┘    │
│                             │                                │
│  ┌──────────────────────────▼──────────────────────────┐    │
│  │         OCI APM Tracing (OpenTelemetry/Zipkin)       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ OCI OPSI │     │ OCI Logan│     │  SQLcl   │
   │   API    │     │   API    │     │  (local) │
   └──────────┘     └──────────┘     └──────────┘
```

## Quick Reference

| Category | Tool Count | Cache Tier | Typical Response |
|----------|------------|------------|------------------|
| OPSI | 15 | Tier 1-2 | <100ms - 5s |
| SQLcl | 7 | Real-time | 100ms - 30s |
| Logan | 13 | Tier 2 | 1-5s |
| Tenancy | 8 | Tier 1 | <100ms |

**Total: 43 tools**

## Naming Conventions

All MCP tool names use **snake_case** (e.g., `get_fleet_summary`, `list_oci_profiles`). This matches Python function naming conventions and ensures consistency across the codebase.

When using tools from AI agents, reference them directly by name:
```python
# Correct
await mcp.call_tool("get_fleet_summary", {"profile": "DEFAULT"})

# For tools with hyphens in external servers (SQLcl native)
await mcp.call_tool("execute_sql", {"sql": "SELECT 1 FROM DUAL"})
```

## Caching Strategy

### Cache Tiers by TTL

| Category | TTL | Examples |
|----------|-----|----------|
| **Static** | 1 hour | `list_oci_profiles`, `list_parsers` |
| **Stable** | 30 min | `list_compartments`, `list_entities`, `list_log_sources`, `get_profile_info` |
| **Infrastructure** | 10-15 min | `get_fleet_summary`, `search_databases`, `list_connections` |
| **Analysis** | 2 min | `analyze_cpu_usage`, `execute_logan_query` |
| **Real-time** | 0 (no cache) | `ping`, `execute_sql`, `health_check` |

### Cache Management Tools

```python
# Check cache status
await mcp.call_tool("cache_status", {})

# Clear all cached data
await mcp.call_tool("clear_cache", {})

# Refresh if stale
await mcp.call_tool("refresh_cache_if_needed", {"max_age_hours": 1})
```

---

## Observability

All tool executions are automatically traced to OCI APM via OpenTelemetry (Zipkin format).

### Trace Attributes

Each tool execution creates a span with:
- `mcp.tool.name` - Tool name
- `mcp.server.id` - Server identifier ("oci-database-observatory")
- `mcp.tool.args` - Truncated arguments
- `mcp.tool.success` - Boolean success status
- `mcp.tool.duration_ms` - Execution time in milliseconds
- `mcp.tool.error` - Error message (if failed)

### APM Configuration

Set these environment variables for tracing:
```bash
OCI_APM_DATA_UPLOAD_ENDPOINT=https://<apm-endpoint>.apm-agt.<region>.oci.oraclecloud.com
OCI_APM_PUBLIC_DATA_KEY=<your-public-data-key>
OTEL_TRACING_ENABLED=true  # default: true
```

---

## OPSI Tools (Operations Insights)

### Discovery & Summary Tools

#### `get_fleet_summary`
Get overview of all databases across the fleet.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `profile` | string | No | DEFAULT | OCI profile name |
| `use_cache` | bool | No | true | Use cached data if available |

**Response:**
```json
{
  "success": true,
  "summary": {
    "total_databases": 42,
    "autonomous_databases": 15,
    "exadata_databases": 8,
    "external_databases": 19
  },
  "by_status": {
    "healthy": 38,
    "warning": 3,
    "critical": 1
  },
  "cache_age_seconds": 120
}
```

#### `search_databases`
Search for databases by name, compartment, or type.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | No | Database name pattern (case-insensitive) |
| `compartment_id` | string | No | Filter by compartment OCID |
| `database_type` | string | No | autonomous, exadata, external |
| `profile` | string | No | OCI profile name |

**Response:**
```json
{
  "success": true,
  "databases": [
    {
      "id": "ocid1.autonomousdatabase.oc1...",
      "name": "PRODDB01",
      "database_type": "autonomous",
      "compartment_id": "ocid1.compartment...",
      "status": "AVAILABLE"
    }
  ],
  "total": 1
}
```

#### `get_cached_database`
Get detailed info for a specific database from cache.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_id` | string | Yes | Database OCID |
| `profile` | string | No | OCI profile |

#### `get_cached_statistics`
Get cache statistics and performance metrics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

#### `build_database_cache`
Build or rebuild the database metadata cache.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `compartment_id` | string | No | Limit to compartment |
| `profile` | string | No | OCI profile |

#### `refresh_cache_if_needed`
Check cache age and refresh if stale.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `max_age_hours` | int | No | Max cache age (default: 24) |
| `profile` | string | No | OCI profile |

### Performance Analysis Tools

#### `analyze_cpu_usage`
Analyze CPU utilization patterns with recommendations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_id` | string | Yes | Database OCID |
| `hours_back` | int | No | Hours to analyze (default: 24) |
| `profile` | string | No | OCI profile |

**Response:**
```json
{
  "success": true,
  "database_id": "ocid1...",
  "metrics": {
    "avg_cpu_percent": 45.2,
    "max_cpu_percent": 92.1,
    "min_cpu_percent": 12.3,
    "samples": 288
  },
  "trend": "increasing",
  "recommendations": [
    {
      "severity": "warning",
      "finding": "CPU approaching threshold",
      "action": "Consider scaling OCPU count"
    }
  ]
}
```

#### `analyze_memory_usage`
Analyze memory utilization and buffer cache efficiency.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_id` | string | Yes | Database OCID |
| `hours_back` | int | No | Hours to analyze |
| `profile` | string | No | OCI profile |

#### `analyze_io_performance`
Analyze I/O throughput and latency metrics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_id` | string | Yes | Database OCID |
| `hours_back` | int | No | Hours to analyze |
| `profile` | string | No | OCI profile |

#### `get_performance_summary`
Get comprehensive performance summary across all metrics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_id` | string | Yes | Database OCID |
| `profile` | string | No | OCI profile |

### Cost Optimization Tools

#### `find_cost_opportunities`
Identify cost optimization opportunities.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

**Response:**
```json
{
  "success": true,
  "opportunities": [
    {
      "database_id": "ocid1...",
      "database_name": "DEVDB01",
      "opportunity_type": "rightsizing",
      "current_monthly_cost": 500,
      "estimated_savings": 200,
      "recommendation": "Reduce OCPU from 4 to 2 based on utilization"
    }
  ],
  "total_potential_savings": 450
}
```

#### `get_savings_summary`
Get aggregated savings recommendations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

### AI Agent Support Tools

#### `list_opsi_skills`
List available OPSI skills for AI agent tool selection.

**Response:**
```json
{
  "success": true,
  "skills": [
    {
      "name": "get_fleet_summary",
      "category": "discovery",
      "tier": 1,
      "description": "Fast database fleet overview",
      "use_when": ["list databases", "how many databases", "fleet status"],
      "estimated_tokens": 200
    },
    {
      "name": "analyze_cpu_usage",
      "category": "performance",
      "tier": 2,
      "description": "CPU utilization analysis with recommendations",
      "use_when": ["cpu high", "performance issues", "slow database"],
      "estimated_tokens": 500
    }
  ]
}
```

#### `get_skill_recommendations`
Get tool recommendations based on user query.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | Yes | User's natural language query |
| `max_recommendations` | int | No | Max results (default: 3) |

**Response:**
```json
{
  "query": "which databases are using too much CPU?",
  "recommendations": [
    {
      "skill": "analyze_cpu_usage",
      "confidence": 0.95,
      "reason": "Query mentions CPU usage analysis"
    },
    {
      "skill": "get_fleet_summary",
      "confidence": 0.6,
      "reason": "Might need fleet overview first"
    }
  ]
}
```

#### `list_database_insights`
List available database insights.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

---

## SQLcl Tools (Database Operations)

### `execute_sql`
Execute SQL query against connected database.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `sql` | string | Yes | SQL statement to execute |
| `connection_name` | string | No | Connection to use |
| `max_rows` | int | No | Row limit (default: 1000) |

**Response:**
```json
{
  "success": true,
  "columns": ["OWNER", "TABLE_NAME", "NUM_ROWS"],
  "rows": [
    ["HR", "EMPLOYEES", 107],
    ["HR", "DEPARTMENTS", 27]
  ],
  "row_count": 2,
  "execution_time_ms": 45
}
```

### `get_schema_info`
Get database schema metadata.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `schema_name` | string | No | Schema name (default: current) |
| `object_type` | string | No | TABLE, VIEW, INDEX, PROCEDURE |
| `object_name` | string | No | Specific object name |

### `list_connections`
List saved database connections.

**Response:**
```json
{
  "success": true,
  "connections": [
    {
      "name": "PRODDB_ADW",
      "type": "cloud-wallet",
      "status": "available"
    }
  ]
}
```

### `database_status`
Get current database connection status and info.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `connection_name` | string | No | Connection to check |

### `sqlcl_disconnect`
Disconnect from current database.

### `check_network_access`
Check network connectivity to database endpoints.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | string | Yes | Hostname or IP |
| `port` | int | No | Port number (default: 1521) |

### `get_my_ip`
Get the current public IP address (useful for ACL configuration).

---

## Logan Tools (Logging Analytics)

### Query Tools

#### `execute_logan_query`
Execute Logging Analytics query.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | Yes | LA query string |
| `time_start` | string | No | Start time (ISO format) |
| `time_end` | string | No | End time (ISO format) |
| `max_results` | int | No | Max results (default: 100) |
| `profile` | string | No | OCI profile |

**Example Query:**
```
'Log Source' = 'Oracle Database Alert Log' and 'Problem Key' != null
| stats count as problems by 'Problem Key'
| sort -problems
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "time": "2025-01-15T14:30:00Z",
      "message": "ORA-01555: snapshot too old",
      "source": "PRODDB01",
      "severity": "ERROR"
    }
  ],
  "total_count": 1,
  "query_time_ms": 1250
}
```

#### `suggest_query`
Get query suggestions based on natural language intent.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `intent` | string | Yes | Natural language intent |
| `profile` | string | No | OCI profile |

**Example:**
```python
await mcp.call_tool("suggest_query", {
    "intent": "find all failed login attempts in the last hour"
})
```

**Response:**
```json
{
  "success": true,
  "suggestions": [
    {
      "query": "'Log Source' = 'Oracle Database Audit Log' and Action = 'LOGON' and Status != 0 | timestats count",
      "description": "Count failed login attempts over time",
      "confidence": 0.85
    }
  ]
}
```

### Security Analysis Tools

#### `run_security_query`
Run predefined security analysis queries.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query_type` | string | Yes | failed_logins, privilege_escalation, suspicious_activity, data_exfiltration |
| `hours_back` | int | No | Hours to analyze (default: 24) |
| `profile` | string | No | OCI profile |

**Available Query Types:**
- `failed_logins` - Failed authentication attempts
- `privilege_escalation` - Privilege grants and changes
- `suspicious_activity` - Unusual database activity
- `data_exfiltration` - Large data exports or suspicious queries

**Response:**
```json
{
  "success": true,
  "query_type": "failed_logins",
  "time_range_hours": 24,
  "findings": [
    {
      "time": "2025-01-15T14:30:00Z",
      "user": "UNKNOWN_USER",
      "source_ip": "192.168.1.100",
      "attempt_count": 15,
      "severity": "high"
    }
  ],
  "summary": {
    "total_findings": 1,
    "high_severity": 1,
    "medium_severity": 0
  }
}
```

#### `detect_anomalies`
Detect anomalies in log volume and patterns.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `log_source` | string | No | Specific log source |
| `hours_back` | int | No | Hours to analyze (default: 24) |
| `sensitivity` | string | No | low, medium, high (default: medium) |
| `profile` | string | No | OCI profile |

**Response:**
```json
{
  "success": true,
  "anomalies": [
    {
      "time": "2025-01-15T14:00:00Z",
      "log_source": "Oracle Database Alert Log",
      "type": "volume_spike",
      "expected_count": 100,
      "actual_count": 1500,
      "deviation_percent": 1400,
      "severity": "high"
    }
  ],
  "baseline": {
    "avg_hourly_count": 95,
    "std_deviation": 20
  }
}
```

### Discovery Tools

#### `list_log_sources`
List available log sources.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name_filter` | string | No | Filter by name pattern |
| `source_type` | string | No | Filter by type |
| `profile` | string | No | OCI profile |

#### `list_active_log_sources`
List log sources with recent activity.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `hours_back` | int | No | Hours to check (default: 24) |
| `min_count` | int | No | Minimum log count |
| `profile` | string | No | OCI profile |

#### `list_entities`
List Logging Analytics entities.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `entity_type` | string | No | Filter by type |
| `name_filter` | string | No | Filter by name |
| `profile` | string | No | OCI profile |

#### `get_entity_logs`
Get logs for a specific entity.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `entity_id` | string | Yes | Entity OCID |
| `hours_back` | int | No | Hours to retrieve |
| `max_results` | int | No | Maximum results |
| `profile` | string | No | OCI profile |

#### `list_parsers`
List available log parsers.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

#### `list_labels`
List available log labels.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

#### `list_log_groups`
List log groups.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | No | OCI profile |

### Summary Tools

#### `get_log_summary`
Get comprehensive log summary with statistics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `hours_back` | int | No | Hours to analyze (default: 24) |
| `profile` | string | No | OCI profile |

**Response:**
```json
{
  "success": true,
  "time_range_hours": 24,
  "summary": {
    "total_logs": 125000,
    "by_severity": {
      "ERROR": 150,
      "WARNING": 1200,
      "INFO": 123650
    },
    "top_sources": [
      {"name": "Oracle Database Alert Log", "count": 45000},
      {"name": "Oracle Database Audit Log", "count": 30000}
    ],
    "error_rate_percent": 0.12
  }
}
```

### AI Support Tools

#### `list_logan_skills`
List available Logan skills for AI agent tool selection.

**Response:**
```json
{
  "success": true,
  "skills": [
    {
      "name": "execute_logan_query",
      "category": "query",
      "description": "Execute custom Logging Analytics queries"
    },
    {
      "name": "run_security_query",
      "category": "security",
      "description": "Run predefined security analysis"
    },
    {
      "name": "detect_anomalies",
      "category": "analytics",
      "description": "Detect log volume anomalies"
    }
  ]
}
```

---

## Tenancy Tools

### Profile Management

#### `list_oci_profiles`
List all available OCI profiles from ~/.oci/config.

**Response:**
```json
{
  "success": true,
  "config_file": "/Users/user/.oci/config",
  "profile_count": 2,
  "profiles": [
    {
      "name": "DEFAULT",
      "region": "eu-frankfurt-1",
      "active": false
    },
    {
      "name": "PROD",
      "region": "us-ashburn-1",
      "active": true
    }
  ]
}
```

#### `get_profile_info`
Get detailed profile information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile_name` | string | No | Profile name (default: active) |

**Response:**
```json
{
  "success": true,
  "profile": {
    "name": "PROD",
    "region": "us-ashburn-1",
    "tenancy_id": "ocid1.tenancy.oc1...",
    "user_id": "ocid1.user.oc1...",
    "fingerprint": "aa:bb:cc:..."
  },
  "is_active": true
}
```

#### `set_active_profile`
Set the active OCI profile for subsequent operations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile_name` | string | Yes | Profile name to activate |

**Note:** This clears the cache since profile change affects all data.

#### `list_compartments`
List compartments in tenancy.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `compartment_id` | string | No | Parent compartment (default: root) |
| `profile` | string | No | OCI profile |

### Server Management

#### `ping`
Simple ping to check if MCP server is responding.

**Response:**
```json
{
  "success": true,
  "message": "pong",
  "timestamp": "2025-01-15T14:30:00Z",
  "server": "oci-database-observatory",
  "version": "0.2.0"
}
```

#### `health_check`
Comprehensive health check of all components.

**Response:**
```json
{
  "success": true,
  "status": "healthy",
  "components": {
    "mcp_server": {"status": "healthy", "version": "0.2.0"},
    "oci_sdk": {"status": "healthy", "version": "2.164.2"},
    "sqlcl": {"status": "available", "path": "/Applications/sqlcl/bin/sql"},
    "cache": {"status": "healthy", "entries": 45, "hit_rate": "78%"}
  },
  "active_profile": "DEFAULT"
}
```

#### `cache_status`
Get cache statistics.

**Response:**
```json
{
  "success": true,
  "entries": 45,
  "hit_rate_percent": 78.5,
  "memory_usage_mb": 12.3,
  "oldest_entry_age_seconds": 3600
}
```

#### `clear_cache`
Clear all cached data.

---

## Error Responses

All tools return errors in a consistent format:

```json
{
  "success": false,
  "error": "Service unavailable",
  "error_type": "OCI_API_ERROR",
  "details": {
    "status_code": 503,
    "service": "operations-insights",
    "request_id": "abc123..."
  }
}
```

### Error Types

| Type | Description | Suggested Action |
|------|-------------|------------------|
| `OCI_API_ERROR` | OCI API returned an error | Check OCI service status |
| `AUTHENTICATION_ERROR` | Invalid credentials | Verify OCI config |
| `AUTHORIZATION_ERROR` | Insufficient permissions | Check IAM policies |
| `CACHE_ERROR` | Cache operation failed | Clear cache and retry |
| `VALIDATION_ERROR` | Invalid parameters | Check parameter values |
| `CONNECTION_ERROR` | Network/connection issue | Verify connectivity |
| `TIMEOUT_ERROR` | Operation timed out | Retry with longer timeout |
| `NOT_FOUND_ERROR` | Resource not found | Verify resource OCID |

---

## Best Practices for AI Agents

### 1. Use Skill Discovery

Always check available skills before selecting tools:

```python
# Get skills for the tool category you need
opsi_skills = await mcp.call_tool("list_opsi_skills", {})
logan_skills = await mcp.call_tool("list_logan_skills", {})

# Or get recommendations based on user query
recs = await mcp.call_tool("get_skill_recommendations", {
    "query": user_query
})
```

### 2. Prefer Cached Tools (Tier 1 First)

Always try fast cached tools before slower API calls:

```python
# Good: Use fleet summary first
summary = await mcp.call_tool("get_fleet_summary", {"profile": profile})

# Then query specific databases if needed
if summary["success"]:
    for db in summary["summary"]["databases"]:
        # Only analyze if needed
        pass
```

### 3. Handle Multi-Tenancy

```python
# List available profiles first
profiles = await mcp.call_tool("list_oci_profiles", {})

# Query specific tenancy by passing profile parameter
for profile in profiles["profiles"]:
    result = await mcp.call_tool("get_fleet_summary", {
        "profile": profile["name"]
    })
```

### 4. Use Security Queries for Incident Response

```python
# Quick security assessment
security_check = await mcp.call_tool("run_security_query", {
    "query_type": "failed_logins",
    "hours_back": 1
})

# Follow up with anomaly detection
anomalies = await mcp.call_tool("detect_anomalies", {
    "sensitivity": "high",
    "hours_back": 1
})
```

### 5. Token Optimization

Use `estimated_tokens` from skill metadata to stay within context limits:

```python
skills = await mcp.call_tool("list_opsi_skills", {})
for skill in skills["skills"]:
    if skill["estimated_tokens"] < remaining_tokens:
        # Safe to use this skill
        pass
```

### 6. Cache Management

```python
# Check cache freshness before critical operations
cache_status = await mcp.call_tool("cache_status", {})

if cache_status["oldest_entry_age_seconds"] > 3600:
    # Cache is stale, refresh
    await mcp.call_tool("refresh_cache_if_needed", {
        "max_age_hours": 1
    })
```

---

## Environment Variables

```bash
# OCI Configuration
OCI_CONFIG_FILE=~/.oci/config
OCI_CLI_PROFILE=DEFAULT

# SQLcl
SQLCL_PATH=/Applications/sqlcl/bin/sql
JAVA_HOME=/path/to/java

# Observability
OCI_APM_DATA_UPLOAD_ENDPOINT=https://<apm>.apm-agt.<region>.oci.oraclecloud.com
OCI_APM_PUBLIC_DATA_KEY=<key>
OCI_LOG_GROUP_ID=ocid1.loggroup...
OCI_LOG_ID=ocid1.log...

# Server Configuration
MCP_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
MCP_TRANSPORT=stdio  # stdio (for MCP clients)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.2.0 | Dec 2025 | Added Logan security tools, OCI APM tracing, multi-tenancy |
| 0.1.0 | Nov 2025 | Initial release with OPSI, SQLcl, Logan basics |
