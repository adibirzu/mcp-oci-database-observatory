# OCI Database Observatory

Multi-agent framework for Oracle, MySQL, and PostgreSQL observability on Oracle Cloud Infrastructure.

## Features

- **Multi-Agent Architecture**: Coordinator orchestrates specialist database agents
- **Database Support**: Oracle (via SQLcl), MySQL, PostgreSQL
- **MCP Integration**: Model Context Protocol for tool execution
- **LLM Routing**: Task-based routing with OCA, Anthropic, OpenAI support
- **OCI APM**: OpenTelemetry tracing with OCI Application Performance Monitoring
- **OCI Logging**: Structured logging with APM trace correlation

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -e .

# Run development server
observatory-dev
```

## Environment Configuration

Create from the template:

```bash
cp .env.example .env.local
# Edit .env.local with your credentials
```

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `OCI_CONFIG_FILE` | Path to OCI config (default: `~/.oci/config`) |
| `OCI_CLI_PROFILE` | OCI profile name (default: `DEFAULT`) |
| `OCI_COMPARTMENT_ID` | OCI compartment OCID |
| `OCI_APM_ENDPOINT` | OCI APM domain endpoint |
| `OCI_APM_PRIVATE_DATA_KEY` | APM private data key |
| `ANTHROPIC_API_KEY` | Anthropic API key (optional) |
| `OPSI_HTTP_URL` | OCI OPSI MCP server URL |
| `SQLCL_PATH` | Path to SQLcl binary |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `POST /agents/query` | Query coordinator |
| `POST /agents/oracle/query` | Direct Oracle agent |
| `POST /agents/mysql/query` | Direct MySQL agent |
| `POST /agents/postgres/query` | Direct PostgreSQL agent |
| `GET /mcp/tools` | List MCP tools |
| `POST /mcp/tools/execute` | Execute MCP tool |
| `GET /llm/providers` | List LLM providers |

## Architecture

```
src/
├── api/          # FastAPI server & routes
├── agents/       # Multi-agent system (coordinator, oracle, mysql, postgres)
├── llm/          # LLM router with task-based provider selection
├── mcp/          # MCP client infrastructure (registry, executor, converter)
├── mcp_server/   # FastMCP server (OPSI, SQLcl, Logan, DB Management, Tenancy)
├── observability/# OCI APM/OTEL + OCI Logging with trace correlation
├── logging/      # Structured logging with correlation IDs
├── cache/        # Redis + in-memory caching with TTL tiers
└── core/         # Config, types, errors, logging setup
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System architecture and data flow |
| [OCI Observability](docs/OCI_OBSERVABILITY.md) | APM and Logging setup guide |
| [MCP Tool Reference](docs/OCI_MCP_REFERENCE.md) | Complete tool API documentation |

## MCP Server Tools

The MCP server provides 53 tools across 5 categories:

| Category | Tools | Description |
|----------|-------|-------------|
| **OPSI** | 15 | Database monitoring, performance analysis, cost optimization, skills |
| **Logan** | 13 | Log analytics queries, security analysis, anomaly detection, entity logs |
| **SQLcl** | 10 | SQL execution, schema, connections, async jobs, network check |
| **Tenancy** | 8 | Profile management, compartments, health check, cache, ping |
| **DB Management** | 7 | Managed databases, AWR snapshots/reports, fleet health, search |

### Key Features

- **Tiered Caching**: Static (1h), Stable (30m), Infrastructure (10m), Analysis (2m), Real-time (0)
- **Multi-Tenancy**: Profile-based OCI credential isolation
- **AI Agent Support**: Skill recommendations and token-optimized responses
- **OCI APM**: Distributed tracing with OpenTelemetry
- **OCI Logging**: Structured logs with APM trace correlation

## License

MIT
