# Technology Stack

## Core Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI (Asynchronous web framework for high-performance API development)
- **Runtime**: Uvicorn (ASGI server)

## AI & Agent Orchestration
- **Framework**: LangGraph (For building complex, stateful multi-agent workflows)
- **Library**: LangChain (For LLM integration, prompt management, and tool abstraction)
- **Protocol**: MCP (Model Context Protocol) SDK (For standardized tool execution and database connectivity)

## LLM Providers
- **Primary Providers**: Anthropic (Claude), OpenAI (GPT), and OCA (Oracle Cloud AI)
- **Routing**: Task-based routing with automated fallback capabilities

## Database Connectivity & Management
- **Oracle Database**: Integration via SQLcl
- **Open Source Databases**: Native support for PostgreSQL and MySQL
- **Interactions**: Standardized through MCP servers and tools

## Infrastructure & Cloud Services
- **Cloud Provider**: Oracle Cloud Infrastructure (OCI)
- **SDK**: OCI Python SDK
- **Identity**: OCI IAM for RBAC and access control
- **Secrets**: OCI Vault for secure credential management

## Observability & Logging
- **Distributed Tracing**: OpenTelemetry (OTel)
- **APM**: OCI Application Performance Monitoring
- **Logging**: Structured logging via `structlog` with APM trace correlation
- **Metrics**: OTel-native metrics exported to OCI monitoring

## Development & Operations
- **Dependency Management**: Hatchling
- **Caching**: Redis (For tool results and agent state persistence)
- **Task Automation**: Tenacity (For robust retry logic)
- **Linting & Formatting**: Ruff, MyPy
- **Testing**: Pytest with Asyncio support and coverage reporting
