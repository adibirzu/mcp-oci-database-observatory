# Orchestrator Enhancement Plan

## Scope and goals
- Add a new Orchestrator agent that reads the tool catalog, understands agent capabilities, and routes to the right tool or specialist agent via the existing Coordinator.
- Remove catalog mismatches and duplicate capability definitions.
- Add runtime feedback tools (set_feedback, append_feedback) with prompt steering.
- Use ATP as the persistent backend for shared memory and feedback.
- Improve Slack responsiveness and prevent stuck delegations.
- Align environment variables and catalog naming across agents and MCP servers.

## Research notes (current state)
- Coordinator and routing exist in `mcp-oci-database-observatory/src/agents/coordinator/coordinator.py`, but specialist agents are not registered anywhere in startup or DI.
- `AgentRouter` expects `DatabaseType` while database agents return `str` in `mcp-oci-database-observatory/src/agents/database/base.py`.
- `BaseAgent` expects `AgentCapability` objects, but database agents use `Capability` enum values, which breaks capability scoring.
- `LangGraphCoordinator` exists in `mcp-oci-database-observatory/src/agents/coordinator/graph.py`, but it is not wired into the API flow.
- `config/mcp-servers.json` defines TTL overrides, but `ToolCatalog` hardcodes TTL values and does not read that config.
- Slack integration folder exists in `mcp-oci-database-observatory/src/integrations/slack` but is empty.
- Runtime feedback tools do not exist in the MCP server tool registry.
- ATP-backed shared memory exists in `mcp-oci/src/mcp_server_oci/core/shared_memory.py`, but there is no `MEMORY_PERSISTENT_BACKEND` switch in this repo.

## Step-by-step plan
1. Define orchestration contract and flow.
   - Document the lifecycle: Slack or API request -> Orchestrator -> Coordinator -> Specialist Agents -> MCP Tools -> Aggregated response.
   - Define when Orchestrator calls tools directly vs delegating to specialist agents.

2. Build an Agent Catalog with dedupe.
   - Create `src/agents/catalog.py` to register each agent profile with capability IDs, tool requirements, and task scope.
   - Enforce unique capability IDs and log collisions at startup.
   - Align capability definitions to `AgentCapability` objects from `src/agents/base/capabilities.py`.

3. Align core typing and routing.
   - Update database agents to return `DatabaseType` rather than `str`.
   - Update `AgentRouter` and `AgentTask` to use consistent types and ensure routing works for multi-db intents.
   - Add a startup validation that each agent has required tools in the MCP tool catalog.

4. Wire agent registration into Coordinator.
   - Register Oracle, MySQL, and Postgres agents with `CoordinatorAgent` during dependency initialization.
   - Ensure `CoordinatorAgent.list_agents()` reflects real capabilities from the Agent Catalog.

5. Implement the Orchestrator agent layer.
   - Add `src/agents/orchestrator/agent.py` that reads the tool catalog and the Agent Catalog.
   - Implement routing logic: direct tool call for single-step tasks, delegate to Coordinator for complex or multi-agent tasks.
   - Add loop prevention and iteration limits to avoid stuck flows.

6. Add runtime feedback store and MCP tools.
   - Implement a `FeedbackStore` with ATP backend and in-memory fallback.
   - Add MCP tools: `set_feedback`, `append_feedback`, `get_feedback`.
   - Store feedback scoped by global, tenant, user, and agent.
   - Set `MEMORY_PERSISTENT_BACKEND=atp` and ATP connection settings in `.env.local`.

7. Inject feedback into prompts and confirm steering.
   - Update system prompts for Coordinator and database agents to include latest feedback text.
   - Add a debug log or trace attribute that records feedback version used per request.
   - Validate by calling `set_feedback` and issuing a test query to confirm prompt steering.

8. Improve Slack responsiveness and reliability.
   - Implement Slack Bolt app handlers in `src/integrations/slack`.
   - Ack within 3 seconds, then process asynchronously.
   - Post immediate delegation confirmation, then update the thread with progress and final answer.
   - Add cancel and timeout handling to prevent stuck requests.

9. Align tool catalog and caching across MCP servers.
   - Load TTL overrides from `config/mcp-servers.json`.
   - Add duplicate tool name detection and log collisions.
   - Ensure Redis is the default cache across servers, with consistent env var names.

10. Validation, tests, and rollout.
   - Add unit tests for Agent Catalog, Orchestrator routing, feedback tools, and TTL overrides.
   - Add an integration test that exercises Slack -> Orchestrator -> Coordinator -> MCP tools.
   - Document the new orchestration flow and runtime feedback usage in `docs/`.

## Acceptance criteria
- Orchestrator routes to correct tools and agents with no duplicate capabilities.
- Coordinator shows registered agents and their capabilities.
- set_feedback and append_feedback update runtime behavior without redeploy.
- Slack responses acknowledge quickly and do not stall on long tasks.
- ATP persistence is active when `MEMORY_PERSISTENT_BACKEND=atp`.

## Dependencies and inputs
- ATP credentials and wallet or TNS alias configuration.
- Slack app tokens and signing secrets.
- Updated tool catalog data from MCP servers (opsi, logan, oci-mcp, sqlcl, mysql, postgres).
