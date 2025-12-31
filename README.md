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

Copy the environment file from the oracle-db-autonomous-agent project:

```bash
cp /Users/abirzu/dev/oracle-db-autonomous-agent/.env.local /Users/abirzu/dev/oci-database-observatory/.env.local
```

Or create a new one from the template:

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
├── api/          # FastAPI server
├── agents/       # Multi-agent system
├── llm/          # LLM router with fallback
├── mcp/          # MCP client infrastructure
├── mcp_server/   # FastMCP server (OPSI, SQLcl, Logan, Tenancy tools)
├── observability/# OCI APM/OTEL + OCI Logging
├── cache/        # Redis + file-based caching
└── core/         # Config, types, errors
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System architecture and data flow |
| [OCI Observability](docs/OCI_OBSERVABILITY.md) | APM and Logging setup guide |
| [MCP Tool Reference](docs/OCI_MCP_REFERENCE.md) | Complete tool API documentation |

## MCP Server Tools

The MCP server provides 33+ tools across 4 categories:

| Category | Tools | Description |
|----------|-------|-------------|
| **OPSI** | 15 | Database monitoring, performance analysis, cost optimization |
| **SQLcl** | 6 | Direct database operations, SQL execution |
| **Logan** | 8 | Log analytics queries, source discovery |
| **Tenancy** | 4 | Multi-tenancy profile management |

### Key Features

- **Tiered Caching**: Static (1h), Stable (30m), Infrastructure (10m), Analysis (2m), Real-time (0)
- **Multi-Tenancy**: Profile-based OCI credential isolation
- **AI Agent Support**: Skill recommendations and token-optimized responses
- **OCI APM**: Distributed tracing with OpenTelemetry
- **OCI Logging**: Structured logs with APM trace correlation

## License

MIT
