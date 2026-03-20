"""LangGraph-based coordinator for MCP tool orchestration.

This module implements a StateGraph that:
1. Receives user queries
2. Routes to LLM for reasoning
3. Executes MCP tools when requested
4. Returns final response
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from src.core import get_logger
from src.observability import create_span
from src.mcp.tools.converter import ToolConverter

logger = get_logger("agents.coordinator.graph")


class NodeType(str, Enum):
    """Graph node types."""

    INPUT = "input"
    AGENT = "agent"
    ACTION = "action"
    OUTPUT = "output"


@dataclass
class CoordinatorState:
    """State maintained through the graph execution.

    Attributes:
        messages: Conversation history with agent messages
        tool_calls: Pending tool calls from the agent
        tool_results: Results from executed tools
        iteration: Current iteration count (for loop prevention)
        max_iterations: Maximum allowed iterations
        error: Any error that occurred
    """

    messages: Annotated[Sequence[BaseMessage], add_messages] = field(
        default_factory=list
    )
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 10
    error: str | None = None


class LangGraphCoordinator:
    """LangGraph-based coordinator for MCP tool orchestration.

    Uses a StateGraph to manage the flow:
    input -> agent -> (action -> agent)* -> output
    """

    def __init__(
        self,
        llm: Any = None,
        tool_catalog: Any = None,
        max_iterations: int = 10,
    ) -> None:
        """Initialize the coordinator.

        Args:
            llm: LangChain LLM with bound tools
            tool_catalog: MCP ToolCatalog for tool execution
            max_iterations: Maximum tool calling iterations
        """
        self.llm = llm
        self.tool_catalog = tool_catalog
        self.max_iterations = max_iterations
        self._checkpointer = MemorySaver()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph.

        Returns:
            Compiled StateGraph
        """
        # Create the graph with our state type
        graph = StateGraph(CoordinatorState)

        # Add nodes
        graph.add_node(NodeType.INPUT.value, self._input_node)
        graph.add_node(NodeType.AGENT.value, self._agent_node)
        graph.add_node(NodeType.ACTION.value, self._action_node)
        graph.add_node(NodeType.OUTPUT.value, self._output_node)

        # Set entry point
        graph.set_entry_point(NodeType.INPUT.value)

        # Add edges
        graph.add_edge(NodeType.INPUT.value, NodeType.AGENT.value)
        graph.add_conditional_edges(
            NodeType.AGENT.value,
            self._should_continue,
            {
                "continue": NodeType.ACTION.value,
                "end": NodeType.OUTPUT.value,
            },
        )
        graph.add_edge(NodeType.ACTION.value, NodeType.AGENT.value)
        graph.add_edge(NodeType.OUTPUT.value, END)

        return graph.compile(checkpointer=self._checkpointer)

    def _input_node(self, state: CoordinatorState) -> dict:
        """Process input and prepare for agent.

        Args:
            state: Current state

        Returns:
            Updated state fields
        """
        logger.debug("Processing input node", message_count=len(state.messages))
        return {"iteration": 0}

    def _agent_node(self, state: CoordinatorState) -> dict:
        """Invoke LLM to reason about the query.

        Args:
            state: Current state

        Returns:
            Updated state with agent response
        """
        with create_span(
            "langgraph.agent_node",
            component="coordinator",
            attributes={"iteration": state.iteration},
        ):
            if not self.llm:
                logger.warning("No LLM configured, returning empty response")
                return {
                    "messages": [
                        AIMessage(content="No LLM configured for processing")
                    ],
                    "tool_calls": [],
                }

            # Get last few messages for context
            messages = list(state.messages)

            # Add tool results as messages if any
            for result in state.tool_results:
                messages.append(
                    ToolMessage(
                        content=str(result.get("result", "")),
                        tool_call_id=result.get("tool_call_id", ""),
                    )
                )

            try:
                response = self.llm.invoke(messages)
                logger.debug(
                    "Agent response",
                    has_tool_calls=bool(
                        hasattr(response, "tool_calls") and response.tool_calls
                    ),
                )

                # Extract tool calls if any
                tool_calls = []
                if hasattr(response, "tool_calls") and response.tool_calls:
                    tool_calls = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "name": tc.get("name", ""),
                            "arguments": tc.get("args", {}),
                        }
                        for i, tc in enumerate(response.tool_calls)
                    ]

                return {
                    "messages": [response],
                    "tool_calls": tool_calls,
                    "tool_results": [],  # Clear previous results
                    "iteration": state.iteration + 1,
                }

            except Exception as e:
                logger.error("Agent invocation failed", error=str(e))
                return {
                    "error": str(e),
                    "messages": [
                        AIMessage(content=f"Error processing request: {e}")
                    ],
                    "tool_calls": [],
                }

    async def _action_node(self, state: CoordinatorState) -> dict:
        """Execute pending tool calls via MCP clients.

        Args:
            state: Current state

        Returns:
            Updated state with tool results
        """
        with create_span(
            "langgraph.action_node",
            component="coordinator",
            attributes={"tool_count": len(state.tool_calls)},
        ):
            if not self.tool_catalog:
                logger.warning("No tool catalog configured")
                return {"tool_results": []}

            results = []
            for tool_call in state.tool_calls:
                tool_name = tool_call.get("name", "")
                arguments = tool_call.get("arguments", {})
                tool_call_id = tool_call.get("id", "")

                logger.debug("Executing tool", tool=tool_name)

                try:
                    tool_def = self.tool_catalog.get_tool(tool_name)
                    if not tool_def:
                        results.append({
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "result": f"Tool not found: {tool_name}",
                            "success": False,
                        })
                        continue

                    client = self.tool_catalog.registry.get_client(tool_def.server_id)
                    if not client:
                        results.append({
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "result": f"Server not available: {tool_def.server_id}",
                            "success": False,
                        })
                        continue

                    result = await client.call_tool(tool_def.original_name, arguments)
                    results.append({
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "result": str(result),
                        "success": True,
                    })

                except Exception as e:
                    logger.error(
                        "Tool execution failed",
                        tool=tool_name,
                        error=str(e),
                    )
                    results.append({
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "result": str(e),
                        "success": False,
                    })

            return {
                "tool_results": results,
                "tool_calls": [],  # Clear after processing
            }

    def _output_node(self, state: CoordinatorState) -> dict:
        """Prepare final output.

        Args:
            state: Current state

        Returns:
            Final state (no changes)
        """
        logger.debug("Output node reached", iterations=state.iteration)
        return {}

    def _should_continue(self, state: CoordinatorState) -> str:
        """Determine if we should continue to action or end.

        Args:
            state: Current state

        Returns:
            "continue" if tool calls pending, "end" otherwise
        """
        # Check for errors
        if state.error:
            return "end"

        # Check iteration limit
        if state.iteration >= state.max_iterations:
            logger.warning("Max iterations reached", max=state.max_iterations)
            return "end"

        # Check for pending tool calls
        if state.tool_calls:
            return "continue"

        return "end"

    async def invoke(
        self,
        query: str,
        thread_id: str | None = None,
    ) -> dict:
        """Process a query through the graph.

        Args:
            query: User query
            thread_id: Optional thread ID for conversation history

        Returns:
            Result dictionary
        """
        import uuid

        initial_state = CoordinatorState(
            messages=[HumanMessage(content=query)],
            max_iterations=self.max_iterations,
        )

        # Always provide thread_id for checkpointer
        effective_thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": effective_thread_id}}

        with create_span(
            "langgraph.invoke",
            component="coordinator",
            attributes={"query_length": len(query)},
        ):
            result = await self._graph.ainvoke(initial_state, config)

            # Extract final message
            messages = result.get("messages", [])
            last_message = messages[-1] if messages else None
            content = (
                last_message.content
                if last_message and hasattr(last_message, "content")
                else ""
            )

            return {
                "success": result.get("error") is None,
                "response": content,
                "iterations": result.get("iteration", 0),
                "error": result.get("error"),
            }

    def get_graph(self) -> StateGraph:
        """Get the compiled graph for inspection.

        Returns:
            Compiled StateGraph
        """
        return self._graph

    def bind_tools(self, llm: Any = None) -> Any:
        """Bind MCP tools to an LLM.

        Converts tools from the catalog to LangChain format and binds
        them to the provided LLM.

        Args:
            llm: LLM to bind tools to. Uses self.llm if not provided.

        Returns:
            LLM with tools bound

        Raises:
            ValueError: If no LLM or tool catalog available
        """
        target_llm = llm or self.llm
        if not target_llm:
            raise ValueError("No LLM provided for tool binding")

        if not self.tool_catalog:
            logger.warning("No tool catalog available for binding")
            return target_llm

        # Convert MCP tools to LangChain format
        converter = ToolConverter(
            self.tool_catalog,
            executor=self._execute_tool,
        )
        tools = converter.to_langchain_tools()

        if not tools:
            logger.warning("No tools available in catalog")
            return target_llm

        logger.info("Binding tools to LLM", tool_count=len(tools))

        # Bind tools to LLM
        bound_llm = target_llm.bind_tools(tools)
        self.llm = bound_llm
        return bound_llm

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool asynchronously via MCP client.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Returns:
            Tool result as string
        """
        if not self.tool_catalog:
            return "Error: No tool catalog configured"

        tool_def = self.tool_catalog.get_tool(tool_name)
        if not tool_def:
            return f"Error: Tool not found: {tool_name}"

        client = self.tool_catalog.registry.get_client(tool_def.server_id)
        if not client:
            return f"Error: Server not available: {tool_def.server_id}"

        try:
            result = await client.call_tool(tool_def.original_name, arguments)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    async def initialize_with_tools(self) -> None:
        """Initialize the coordinator with tools from the catalog.

        This method connects to MCP servers, refreshes the tool catalog,
        and binds tools to the LLM.
        """
        if not self.tool_catalog:
            logger.warning("No tool catalog configured")
            return

        # Refresh the catalog
        await self.tool_catalog.refresh()

        # Bind tools if LLM is configured
        if self.llm:
            self.bind_tools()
