# Track Specification: MCP Client & Coordinator Orchestration

## Overview
This track focuses on implementing the core "brain" of the OCI Database Observatory: the Coordinator Agent and its integration with the Model Context Protocol (MCP). The goal is to enable the coordinator to dynamically discover tools exposed by MCP servers (Oracle via SQLcl, MySQL, PostgreSQL), route user queries to the appropriate tools, and execute them securely.

## Goals
1.  **Robust MCP Client**: Implement a Python-based MCP client capable of connecting to multiple local or remote MCP servers.
2.  **Tool Discovery**: Automatically list and register tools available from connected MCP servers.
3.  **Coordinator Agent**: Implement the LangGraph-based coordinator agent that can reason about user intent and select the correct MCP tool.
4.  **Database Integration**: Ensure successful connectivity and query execution against Oracle (SQLcl), MySQL, and PostgreSQL via their respective MCP servers.
5.  **Configuration**: flexible configuration for defining MCP server endpoints and environment variables.

## Key Components

### 1. MCP Client Infrastructure (`src/mcp/`)
-   **Client Factory**: A way to create and manage connections to multiple MCP servers defined in configuration.
-   **Stdio Transport**: Support for connecting to local MCP servers (like SQLcl or Node.js based servers) via standard input/output.
-   **Tool Registry**: A centralized registry to aggregate tools from all connected servers into a format the LLM can understand (e.g., OpenAI function schemas).

### 2. Coordinator Agent (`src/agents/coordinator/`)
-   **State Management**: Use LangGraph to manage the conversation state and tool execution loop.
-   **Routing Logic**: The LLM must decide whether to answer directly or call a specific database tool.
-   **Response Synthesis**: Format the raw output from MCP tools into a user-friendly response.

### 3. Configuration (`config/mcp-servers.json`)
-   Define the executables and arguments for:
    -   Oracle Agent (SQLcl)
    -   MySQL Agent (Postgres/MySQL MCP server)
    -   PostgreSQL Agent

## detailed Requirements
-   **Security**: Ensure environment variables (like DB credentials) are passed securely to the MCP subprocesses.
-   **Error Handling**: Gracefully handle MCP server crashes, timeouts, or invalid tool arguments.
-   **Observability**: Trace all MCP tool calls using OpenTelemetry.

## Existing Context
-   Existing MCP servers are located at `/Users/abirzu/dev/MCP`.
-   SQLcl is a key component for Oracle Database interactions.
