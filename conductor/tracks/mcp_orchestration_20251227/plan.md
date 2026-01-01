# Track Plan: MCP Client & Coordinator Orchestration

## Phase 1: Foundation - MCP Client & Configuration

- [x] Task: Create MCP Configuration Manager [de382a4]
    - [x] Subtask: Write tests for loading `config/mcp-servers.json` and validating schema.
    - [x] Subtask: Implement `McpServerConfig` and configuration loading logic in `src/mcp/config.py`.
    - [x] Subtask: Refactor to ensure type safety.

- [x] Task: Implement MCP Client with Stdio Transport [f7c563c]
    - [x] Subtask: Write tests mocking `subprocess` to verify Stdio communication (JSON-RPC).
    - [x] Subtask: Implement `McpClient` in `src/mcp/client.py` using the Python MCP SDK.
    - [x] Subtask: Ensure `initialize` handshake works correctly.

- [x] Task: Implement Tool Discovery & Registry [822647c]
    - [x] Subtask: Write tests for fetching tools list from a mock MCP server.
    - [x] Subtask: Implement `list_tools` method in `McpClient`.
    - [x] Subtask: Create `ToolRegistry` in `src/mcp/registry.py`.

- [ ] Task: Conductor - User Manual Verification 'Phase 1: Foundation - MCP Client & Configuration' (Deferred to Phase 5)

## Phase 2: Coordinator Agent Implementation

- [x] Task: Initialize LangGraph Coordinator [db1f90c]
    - [x] Subtask: Write tests for the basic graph structure.
    - [x] Subtask: Implement the basic StateGraph in `src/agents/coordinator/graph.py`.

- [x] Task: Bind MCP Tools to Coordinator LLM [503c61e]
    - [x] Subtask: Write tests to verify tool binding.
    - [x] Subtask: Update coordinator to load tools from registry at startup.

- [x] Task: Implement Tool Execution Node [bc999af]
    - [x] Subtask: Write tests for the `action` node.
    - [x] Subtask: Implement `call_tool` method in `McpClient` and connect it.

- [ ] Task: Conductor - User Manual Verification 'Phase 2: Coordinator Agent Implementation' (Deferred to Phase 5)

## Phase 3: Database MCP Server Integration

- [x] Task: Configure & Test Oracle (SQLcl) MCP Connection [029283c]
    - [x] Subtask: Update `config/mcp-servers.json` with actual paths to SQLcl MCP.
    - [x] Subtask: Write integration test for SQLcl MCP.

- [ ] Task: Configure MySQL/Postgres MCP Connections
    - [ ] Subtask: Review existing MCP servers in `/Users/abirzu/dev/MCP`.
    - [ ] Subtask: Update `config/mcp-servers.json` to point to correct endpoints (HTTP or Stdio).
    - [ ] Subtask: Write integration tests for connectivity.

- [ ] Task: Conductor - User Manual Verification 'Phase 3: Database MCP Server Integration' (Deferred to Phase 5)

## Phase 4: End-to-End Orchestration & Verification

- [x] Task: End-to-End Flow: Natural Language to SQL [4d81456]
    - [x] Subtask: Write an E2E test.
    - [x] Subtask: Refactor prompt engineering for Coordinator.

- [ ] Task: Conductor - User Manual Verification 'Phase 4: End-to-End Orchestration & Verification' (Deferred to Phase 5)

## Phase 5: Comprehensive Verification & Polish

- [ ] Task: Resolve Shell Environment Issues (CRITICAL)
    - [ ] Subtask: Investigate why `run_shell_command` is rejected.
    - [ ] Subtask: Restore ability to run tests and git commands.

- [ ] Task: Execute Deferred Verifications
    - [ ] Subtask: Verify Phase 1 (Client & Config).
    - [ ] Subtask: Verify Phase 2 (Coordinator).
    - [ ] Subtask: Verify Phase 3 (DB Integration).
    - [ ] Subtask: Verify Phase 4 (E2E).

- [ ] Task: Final Checkpoint & Documentation Sync
    - [ ] Subtask: Create final checkpoint commit.
    - [ ] Subtask: Synchronize `product.md` and `tech-stack.md` with final implementation.