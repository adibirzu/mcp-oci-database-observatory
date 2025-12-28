# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**OCI Database Observatory** - A Python-based, multi-agent framework for Oracle, MySQL, and PostgreSQL observability built on Oracle GenAI Agent platform with full OCI APM/OTEL integration.

**Stack:** Python 3.11+, FastAPI, LangChain/LangGraph, MCP SDK, OpenTelemetry

---

## Architecture Philosophy: Black Box Design

This project follows **Eskil Steenberg's Black Box Architecture** for building maintainable systems.

### Core Principles

1. **Module Independence**: Each module is self-contained with clear inputs/outputs
2. **Interface Contracts**: Communication through well-defined interfaces only
3. **No Hidden Dependencies**: All dependencies are explicit
4. **Single Responsibility**: Each file does exactly one thing
5. **Testability First**: Every module can be tested in isolation

### Black Box Checklist

```
┌─────────────────────────────────────────────────────────────────┐
│  BLACK BOX ARCHITECTURE CHECKLIST                               │
├─────────────────────────────────────────────────────────────────┤
│  [ ] Module has single, clear purpose                           │
│  [ ] All inputs come through function parameters                │
│  [ ] All outputs return through function returns                │
│  [ ] No global state mutations                                  │
│  [ ] Dependencies injected, not imported directly               │
│  [ ] Can be tested without mocking other modules                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Secure Environment Variable Enforcement

### Core Principles

- **Zero Hardcoding**: No sensitive data in source code
- **Variable Sourcing**: `.env.local` (dev) or **OCI Vault** (prod)
- **Git Safety**: `.env.local` must be in `.gitignore`

### Implementation Standards

1. **Reference via os.getenv()**: Never hardcode values
2. **Documentation**: Use `[Link to Secure Variable: VAR_NAME]` placeholder
3. **OCI Integration**: Production uses OCI Vault secret injection

### Validation Checklist

```
┌─────────────────────────────────────────────────────────────────┐
│  SECURITY VALIDATION CHECKLIST                                  │
├─────────────────────────────────────────────────────────────────┤
│  [ ] Variable defined in `.env.local`?                          │
│  [ ] `.env.local` in `.gitignore`?                              │
│  [ ] Code uses variable name, not literal value?                │
│  [ ] Variable documented as secure link placeholder?            │
│  [ ] Production: OCI Vault integration configured?              │
└─────────────────────────────────────────────────────────────────┘
```

---

## OCI APM / OpenTelemetry Integration

### Service Naming Convention

Each component has a unique OTEL service name sharing the same APM project:

| Component | Service Name | Description |
|-----------|--------------|-------------|
| **Coordinator** | `oci-obs-coordinator` | Main orchestrator agent |
| **Oracle Agent** | `oci-obs-agent-oracle` | Oracle database specialist |
| **MySQL Agent** | `oci-obs-agent-mysql` | MySQL database specialist |
| **Postgres Agent** | `oci-obs-agent-postgres` | PostgreSQL specialist |
| **MCP Executor** | `oci-obs-mcp-executor` | MCP tool execution |
| **LLM Router** | `oci-obs-llm-router` | LLM provider routing |
| **API Server** | `oci-obs-api` | FastAPI REST endpoints |

### Trace Propagation

```python
# All components share trace context via W3C Trace Context headers
# Traces flow: API → Coordinator → Agent → MCP Executor → MCP Server
```

### Key Spans

- `agent.query` - End-to-end query processing
- `agent.classify_intent` - Intent classification
- `agent.route` - Agent routing decision
- `agent.execute` - Agent task execution
- `mcp.tool.call` - MCP tool invocation
- `llm.request` - LLM provider request
- `cache.lookup` - Cache hit/miss

---

## Critical Guidelines

### Design Principles

- **Max 200 lines per file** - Split larger files
- **Single responsibility** - Each file does one thing
- **Direct tool execution** - Agents call MCP tools directly
- **Cache-first** - Check cache before MCP calls
- **Parallel by default** - Execute independent tools concurrently
- **Structured logging** - Use structlog, not print()

### DO NOT MODIFY

- **OTEL instrumentation** - Tracing chain carefully designed
- **LLM Router configuration** - Task-based routing is intentional
- **Cache TTL definitions** - Tuned for data volatility
- **MCP transport layer** - Stable implementations

### ALWAYS USE

- `.env.local` for ALL environment variables
- `~/.oci/config` for OCI credentials
- Namespaced MCP tool names: `server__tool`
- structlog for logging
- Pydantic for validation

---

## Development Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Development
uvicorn src.main:app --reload --port 3001

# Testing
pytest                    # All tests
pytest tests/unit         # Unit tests
pytest --cov=src          # With coverage

# Quality
ruff check src            # Linting
ruff format src           # Formatting
mypy src                  # Type checking

# MCP Servers
./scripts/start-mcp-servers.sh start
./scripts/start-mcp-servers.sh status
```

---

## Project Structure

```
oci-database-observatory/
├── pyproject.toml              # Python project config
├── .env.local                  # Environment (gitignored)
├── .env.example                # Template
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry (<50 lines)
│   │
│   ├── core/                   # Shared infrastructure
│   │   ├── config.py           # Pydantic settings (<80 lines)
│   │   ├── types.py            # Type definitions (<100 lines)
│   │   ├── errors.py           # Custom exceptions (<50 lines)
│   │   └── logging.py          # Structlog setup (<40 lines)
│   │
│   ├── observability/          # OCI APM / OTEL
│   │   ├── tracing.py          # OTEL setup (<100 lines)
│   │   ├── spans.py            # Span helpers (<80 lines)
│   │   └── metrics.py          # Custom metrics (<60 lines)
│   │
│   ├── agents/                 # Agent implementations
│   │   ├── base/
│   │   │   ├── agent.py        # BaseAgent (<150 lines)
│   │   │   ├── context.py      # AgentContext (<80 lines)
│   │   │   └── capabilities.py # Capability defs (<60 lines)
│   │   │
│   │   ├── coordinator/
│   │   │   ├── coordinator.py  # Main orchestrator (<200 lines)
│   │   │   ├── intent.py       # Intent classifier (<120 lines)
│   │   │   ├── router.py       # Agent router (<100 lines)
│   │   │   └── aggregator.py   # Response aggregator (<80 lines)
│   │   │
│   │   ├── oracle/
│   │   │   ├── agent.py        # Oracle specialist (<180 lines)
│   │   │   ├── tools.py        # Tool definitions (<100 lines)
│   │   │   ├── prompts.py      # System prompts (<80 lines)
│   │   │   └── runbooks/       # Diagnostic playbooks
│   │   │
│   │   ├── mysql/              # MySQL specialist
│   │   └── postgres/           # PostgreSQL specialist
│   │
│   ├── mcp/                    # MCP client infrastructure
│   │   ├── client/
│   │   │   ├── client.py       # MCPClient (<150 lines)
│   │   │   ├── stdio.py        # Stdio transport (<80 lines)
│   │   │   └── http.py         # HTTP transport (<100 lines)
│   │   │
│   │   ├── registry/
│   │   │   ├── registry.py     # ServerRegistry (<120 lines)
│   │   │   ├── catalog.py      # ToolCatalog (<150 lines)
│   │   │   └── config.py       # Config store (<80 lines)
│   │   │
│   │   └── executor/
│   │       ├── executor.py     # ToolExecutor (<100 lines)
│   │       └── parallel.py     # ParallelExecutor (<120 lines)
│   │
│   ├── llm/                    # LLM provider layer
│   │   ├── router/
│   │   │   ├── router.py       # LLMRouter (<150 lines)
│   │   │   └── optimizer.py    # Cost/latency optimizer (<80 lines)
│   │   │
│   │   └── providers/
│   │       ├── base.py         # BaseProvider (<80 lines)
│   │       ├── oca.py          # Oracle Code Assist (<200 lines)
│   │       ├── anthropic.py    # Claude (<100 lines)
│   │       ├── openai.py       # GPT (<100 lines)
│   │       └── gemini.py       # Gemini (<100 lines)
│   │
│   ├── cache/
│   │   ├── tool_cache.py       # Tool result cache (<120 lines)
│   │   ├── semantic.py         # Semantic cache (<100 lines)
│   │   └── ttl.py              # TTL config (<50 lines)
│   │
│   ├── integrations/
│   │   ├── slack/              # Slack bot
│   │   ├── teams/              # Teams bot
│   │   └── oci/
│   │       ├── auth.py         # OCI authentication (<80 lines)
│   │       └── profiles.py     # Profile management (<60 lines)
│   │
│   └── api/
│       ├── server.py           # FastAPI setup (<80 lines)
│       ├── routes/
│       │   ├── health.py       # Health endpoints (<50 lines)
│       │   ├── agents.py       # Agent endpoints (<80 lines)
│       │   ├── mcp.py          # MCP management (<80 lines)
│       │   ├── oca.py          # OCA OAuth routes (<150 lines)
│       │   └── observability.py # Metrics/traces (<80 lines)
│       │
│       └── middleware/
│           ├── auth.py         # Authentication (<60 lines)
│           ├── tracing.py      # OTEL middleware (<40 lines)
│           └── errors.py       # Error handling (<50 lines)
│
├── config/
│   ├── mcp-servers.json        # MCP server definitions
│   ├── llm-routing.yaml        # LLM routing rules
│   └── databases/              # Database runbooks
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── scripts/
│   └── start-mcp-servers.sh
│
└── docs/
    └── IMPLEMENTATION_PLAN.md
```

---

## LangGraph Coordinator

### StateGraph Architecture

The coordinator uses LangGraph's StateGraph for stateful multi-agent orchestration:

```
input -> agent -> (action -> agent)* -> output
          │            │
          └──── tool calls? ────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| `CoordinatorState` | `graph.py` | Immutable state with messages, tool calls |
| `LangGraphCoordinator` | `graph.py` | StateGraph with checkpointing |
| `ToolConverter` | `tools/converter.py` | MCP to LangChain tool format |
| `ToolExecutor` | `executor/executor.py` | Direct MCP tool execution |

### Usage

```python
from src.agents.coordinator.graph import LangGraphCoordinator
from src.mcp.registry.catalog import ToolCatalog

# Initialize with LLM and tool catalog
coordinator = LangGraphCoordinator(
    llm=claude_llm,
    tool_catalog=catalog,
    max_iterations=10,
)

# Load tools from MCP servers
await coordinator.initialize_with_tools()

# Process queries
result = await coordinator.invoke("What tables are in the users schema?")
```

### Nodes

- **input**: Prepares state for processing
- **agent**: LLM reasoning with tool calling
- **action**: MCP tool execution via ToolExecutor
- **output**: Final response preparation

---

## Agent System

### Agent Types

| Agent | Service Name | Purpose | MCP Servers |
|-------|--------------|---------|-------------|
| **Coordinator** | `oci-obs-coordinator` | Orchestration | - |
| **OracleAgent** | `oci-obs-agent-oracle` | AWR, ASH, OPSI | oci-opsi, sqlcl |
| **MySQLAgent** | `oci-obs-agent-mysql` | Perf Schema, InnoDB | mysql-mcp |
| **PostgresAgent** | `oci-obs-agent-postgres` | pg_stat, Vacuum | postgres-mcp |

### Creating a New Agent

1. Create directory: `src/agents/<database>/`
2. Implement files:
   - `agent.py` - Extends BaseAgent (<180 lines)
   - `tools.py` - Tool definitions (<100 lines)
   - `prompts.py` - System prompts (<80 lines)
   - `runbooks/` - Diagnostic playbooks
3. Register in `src/agents/coordinator/router.py`
4. Add OTEL service name in `src/observability/tracing.py`

---

## MCP Tool Naming

```python
# Format: server__tool (double underscore separator)
SQLCL_RUN_SQL = "sqlcl__run-sql"
OPSI_CPU = "oci-opsi__skill_analyze_cpu_usage"
MYSQL_PERF = "mysql-mcp__query_performance_schema"
POSTGRES_STAT = "postgres-mcp__pg_stat_statements"
```

---

## LLM Router

### Task-Based Routing

```python
provider = await router.select_provider(
    task_type="analysis",       # classification | analysis | synthesis | code_generation
    complexity="high",          # low | medium | high
    latency_requirement="fast", # realtime | fast | batch
    cost_sensitivity="medium"   # low | medium | high
)
```

### Provider Priority

| Task Type | Primary | Secondary | Fallback |
|-----------|---------|-----------|----------|
| Classification | OCA | Gemini Flash | Claude Haiku |
| Analysis | Claude Sonnet | OCA | GPT-4 Turbo |
| Code Generation | OCA | Claude Sonnet | - |

---

## Cache Strategy

### TTL Tiers

| Tier | TTL | Example Tools |
|------|-----|---------------|
| Static | 1h | list_profiles, schema-info |
| Stable | 30m | list_compartments, fleet_summary |
| Infra | 10m | list_databases, connections |
| Analysis | 2m | analyze_cpu, queries |
| Realtime | 0 | run-sql, connect |

---

## Iteration Guardrails

| Guardrail | Limit | Purpose |
|-----------|-------|---------|
| Max iterations | 12 | Prevent runaway loops |
| Tool calls per iteration | 10 | Limit API costs |
| Response timeout | 60s | Ensure responsiveness |
| Repetition detection | 3 | Detect agent loops |

---

## Quick Reference

### Adding a New MCP Server

1. Add config to `config/mcp-servers.json`
2. Define tools in `src/agents/<db>/tools.py`
3. Register in `src/mcp/registry/registry.py`
4. Add TTL mappings in `src/cache/ttl.py`

### Adding a New LLM Provider

1. Create `src/llm/providers/<provider>.py` extending `BaseProvider`
2. Add to `src/llm/router/router.py`
3. Update `config/llm-routing.yaml`
4. Add environment variables to `.env.local`

---

## Test Coverage

### Running Tests

```bash
pytest                           # All tests
pytest tests/unit                # Unit tests only
pytest -v --tb=short             # Verbose with short traceback
pytest --cov=src                 # With coverage
```

### Test Structure

```
tests/
├── conftest.py                  # Shared fixtures (mock_redis, etc.)
├── test_agents.py               # Agent system tests
├── test_cache.py                # Cache behavior tests
├── test_config.py               # Configuration tests
├── test_llm_router.py           # LLM routing tests
├── test_types.py                # Type definition tests
└── unit/
    ├── agents/
    │   └── test_graph.py        # LangGraph coordinator tests
    └── mcp/
        ├── client/
        │   ├── test_stdio.py    # Stdio transport tests
        │   └── test_client.py   # MCPClient tests
        ├── registry/
        │   ├── test_catalog.py  # Tool catalog tests
        │   └── test_registry.py # Server registry tests
        ├── executor/
        │   └── test_executor.py # Tool executor tests
        └── tools/
            └── test_converter.py # Tool conversion tests
```

### Current Coverage (151 tests)

| Module | Tests | Coverage |
|--------|-------|----------|
| MCP Client/Transport | 26 | Stdio, HTTP, JSON-RPC |
| Tool Registry/Catalog | 39 | Discovery, namespacing, TTL |
| LangGraph Coordinator | 33 | Nodes, routing, tool binding |
| Tool Executor | 13 | Caching, execution |
| Agents | 7 | Coordinator, intent |
| LLM Router | 3 | Task classification |
| Cache | 6 | Set, get, TTL |
| Config/Types | 7 | Settings, types |
| Tool Converter | 17 | LangChain format |
