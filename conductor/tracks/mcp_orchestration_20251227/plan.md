# Track Plan: MCP Client & Coordinator Orchestration

## Phase 1: Foundation - MCP Client & Configuration

- [x] Task: Create MCP Configuration Manager [de382a4]
    - [ ] Subtask: Write tests for loading `config/mcp-servers.json` and validating schema.
    - [ ] Subtask: Implement `McpServerConfig` and configuration loading logic in `src/core/config.py` or `src/mcp/config.py`.
    - [ ] Subtask: Refactor to ensure type safety.

- [x] Task: Implement MCP Client with Stdio Transport [f7c563c]
    - [x] Subtask: Write tests mocking `subprocess` to verify Stdio communication (JSON-RPC).
    - [x] Subtask: Implement `McpClient` in `src/mcp/client.py` using the Python MCP SDK (or custom implementation if SDK is not yet stable) to connect to a server process.
    - [x] Subtask: Ensure `initialize` handshake works correctly.

- [x] Task: Implement Tool Discovery & Registry [822647c]
    - [x] Subtask: Write tests for fetching tools list from a mock MCP server and converting to LangChain/LLM format.
    - [x] Subtask: Implement `list_tools` method in `McpClient`.
    - [x] Subtask: Create `ToolRegistry` in `src/mcp/registry.py` to aggregate tools from multiple clients.

- [ ] Task: Conductor - User Manual Verification 'Phase 1: Foundation - MCP Client & Configuration' (Protocol in workflow.md)

## Phase 2: Coordinator Agent Implementation

- [x] Task: Initialize LangGraph Coordinator [db1f90c]
    - [x] Subtask: Write tests for the basic graph structure (nodes: `input`, `agent`, `action`, `output`).
    - [x] Subtask: Implement the basic StateGraph in `src/agents/coordinator/graph.py`.

- [x] Task: Bind MCP Tools to Coordinator LLM [503c61e]
    - [x] Subtask: Write tests to verify that tools from `ToolRegistry` are correctly passed to the LLM's `bind_tools` method.
    - [x] Subtask: Update coordinator to load tools from registry at startup.

- [ ] Task: Implement Tool Execution Node
    - [ ] Subtask: Write tests for the `action` node: receiving a tool call, executing it via `McpClient`, and returning output.
    - [ ] Subtask: Implement `call_tool` method in `McpClient` and connect it to the graph's execution node.

- [ ] Task: Conductor - User Manual Verification 'Phase 2: Coordinator Agent Implementation' (Protocol in workflow.md)

## Phase 3: Database MCP Server Integration

- [ ] Task: Configure & Test Oracle (SQLcl) MCP Connection
    - [ ] Subtask: Update `config/mcp-servers.json` with actual paths to SQLcl MCP.
    - [ ] Subtask: Write an integration test that starts the real SQLcl MCP server and pings it (or lists tools).

- [ ] Task: Configure & Test MySQL/Postgres MCP Connections
    - [ ] Subtask: Update `config/mcp-servers.json` with paths to the other MCP servers in `/Users/abirzu/dev/MCP`.
    - [ ] Subtask: Write integration tests for connectivity.

- [ ] Task: Conductor - User Manual Verification 'Phase 3: Database MCP Server Integration' (Protocol in workflow.md)

## Phase 4: End-to-End Orchestration & Verification

- [ ] Task: End-to-End Flow: Natural Language to SQL
    - [ ] Subtask: Write an E2E test: "Show me the tables in the users schema" -> Agent -> MCP Tool (SQLcl) -> DB -> Result -> Agent -> "Here are the tables...".
    - [ ] Subtask: Refactor and polish the prompt engineering for the Coordinator to ensure correct tool selection.

- [ ] Task: Conductor - User Manual Verification 'Phase 4: End-to-End Orchestration & Verification' (Protocol in workflow.md)
