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
├── observability/# OCI APM/OTEL
├── logging/      # OCI Logging
├── cache/        # Redis caching
└── core/         # Config, types, errors
```

## License

MIT
