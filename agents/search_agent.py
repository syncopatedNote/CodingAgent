#!/usr/bin/env python3
"""
Search Agent - Simplified with LLM Function Calling
Handles all search operations across Confluence, Jira using MCP tools.
The LLM decides which tools to call based on the user's query.
"""

import json
import asyncio
from typing import Dict, List, Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langchain_core.messages import (
    HumanMessage,
    BaseMessage,
    AIMessage,
    ToolMessage,
)
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.llm_base import LLMFactory
from framework_base.multi_server_mcp_client import get_read_only_tools
from framework_base.mcp_servers.registry import get_mcp_registry
from agents.components.search_classifier import classify_search_query, SearchCategory
from agents.prompts.search.tool_calling import SEARCH_TOOL_CALLING_PROMPT
from agents.prompts.search.format_results import SEARCH_FORMAT_RESULTS_PROMPT
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)


class SearchState(TypedDict):
    """Simplified state for the search agent workflow"""

    messages: Annotated[List[BaseMessage], "Conversation messages"]
    query: str
    tool_results: List[Dict]  # Results from tool calls
    final_response: Optional[str]
    error_message: Optional[str]
    search_category: Optional[str]  # Classified SearchCategory value


class SearchAgent:
    def __init__(self):
        """Initialize the search agent with LLM"""
        llm_kwargs = {"temperature": 0.3}

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        # Build the workflow graph
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the simplified search workflow graph"""
        workflow = StateGraph(SearchState)

        workflow.add_node("classify_query", self._classify_and_validate)
        workflow.add_node("execute_search", self._execute_search)
        workflow.add_node("format_response", self._format_response)
        workflow.add_node("handle_error", self._handle_error)

        # Entry: classify first
        workflow.set_entry_point("classify_query")

        # After classification: proceed to search or short-circuit to error
        workflow.add_conditional_edges(
            "classify_query",
            self._route_after_classify,
            {"search": "execute_search", "error": "handle_error"},
        )

        # After search: format or error
        workflow.add_conditional_edges(
            "execute_search",
            self._route_after_search,
            {"format": "format_response", "error": "handle_error"},
        )

        # End nodes
        workflow.add_edge("format_response", END)
        workflow.add_edge("handle_error", END)

        return workflow.compile()

    async def _load_mcp_tools(self, server_name: str):
        """Load read-only MCP tools from a specific server."""
        try:
            tools = await get_read_only_tools(server_name=server_name)
            logger.info(
                f"Loaded {len(tools)} read-only tools from server '{server_name}'"
            )
            return tools
        except Exception as e:
            logger.error(
                f"Failed to load MCP tools from server '{server_name}': {str(e)}"
            )
            return []

    async def _classify_and_validate(self, state: SearchState) -> SearchState:
        """
        Classify the query and verify the required MCP server is enabled.
        Sets error_message and short-circuits if the server is unavailable.
        """
        category = await classify_search_query(state["query"])
        state["search_category"] = category.value
        logger.info(f"Search query classified as: {category.value}")

        if category is SearchCategory.UNKNOWN:
            state["error_message"] = (
                "I couldn't determine which system to search. "
                "Please mention the system explicitly — for example: "
                "Confluence, Jira, GitHub, GitLab, or documentation."
            )
            return state

        # Check that the mapped MCP server is enabled and available
        registry = get_mcp_registry()
        enabled_servers = registry.get_enabled_servers()
        server_name = category.value  # SearchCategory values == server names

        if server_name not in enabled_servers:
            all_servers = registry.get_all_servers()
            server_cfg = all_servers.get(server_name)
            if server_cfg and not server_cfg.enabled:
                reason = "it is disabled"
            elif server_cfg and not server_cfg.is_available():
                reason = "its credentials are not configured"
            else:
                reason = "it is not registered"

            state["error_message"] = (
                f"Cannot perform this search: the '{server_name}' MCP server "
                f"required to handle this request is not available ({reason}). "
                "Please enable and configure the server, or search a different system."
            )
            logger.warning(
                "Rejecting search — required MCP server not available",
                server=server_name,
                reason=reason,
            )

        return state

    def _route_after_classify(self, state: SearchState) -> str:
        """Proceed to search, or short-circuit to error handler."""
        return "error" if state.get("error_message") else "search"

    async def _execute_search(self, state: SearchState) -> SearchState:
        """
        Execute search using LLM with tool calling.
        The LLM decides which tools to call based on the query.
        """
        try:
            # Load tools scoped to the classified server only
            server_name = state.get("search_category", "")
            tools = await self._load_mcp_tools(server_name=server_name)

            if not tools:
                state["error_message"] = (
                    f"No read-only tools are available from the '{server_name}' "
                    "MCP server. The server may be running but exposes no "
                    "read-only tools. Please check the server configuration."
                )
                return state

            # Bind tools to LLM
            llm_with_tools = self.llm.bind_tools(tools)

            # Build the prompt for the LLM
            tool_names = [t.name for t in tools]
            search_prompt = SEARCH_TOOL_CALLING_PROMPT.format(
                server_name=server_name,
                query=state["query"],
                tool_names=", ".join(tool_names),
            )

            messages = [HumanMessage(content=search_prompt)]

            # Let LLM make tool calls
            response = await llm_with_tools.ainvoke(messages)

            # Check if LLM made tool calls
            if hasattr(response, "tool_calls") and response.tool_calls:
                logger.info(f"LLM made {len(response.tool_calls)} tool call(s)")

                # Add the AI response (with tool_calls) to messages BEFORE ToolMessages
                messages.append(response)

                tool_results = []

                # Execute each tool call
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]

                    logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

                    try:
                        # Find the tool and execute it
                        tool = next((t for t in tools if t.name == tool_name), None)

                        if tool:
                            result = await tool.ainvoke(tool_args)

                            # Parse result if it's a string
                            if isinstance(result, str):
                                try:
                                    result = json.loads(result)
                                except json.JSONDecodeError:
                                    pass  # Keep as string

                            tool_results.append(
                                {
                                    "tool_name": tool_name,
                                    "tool_args": tool_args,
                                    "result": result,
                                    "tool_call_id": tool_id,
                                }
                            )

                            # Add tool message to conversation
                            messages.append(
                                ToolMessage(
                                    content=json.dumps(result, default=str),
                                    tool_call_id=tool_id,
                                )
                            )
                        else:
                            logger.error(f"Tool {tool_name} not found")
                            error_msg = "Tool not found"
                            tool_results.append(
                                {
                                    "tool_name": tool_name,
                                    "error": error_msg,
                                }
                            )
                            # Add error as ToolMessage to maintain message sequence
                            messages.append(
                                ToolMessage(
                                    content=f"Error: {error_msg}",
                                    tool_call_id=tool_id,
                                )
                            )

                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {str(e)}")
                        tool_results.append(
                            {
                                "tool_name": tool_name,
                                "error": str(e),
                            }
                        )
                        # Add error as ToolMessage to maintain message sequence
                        messages.append(
                            ToolMessage(
                                content=f"Error: {str(e)}",
                                tool_call_id=tool_id,
                            )
                        )

                state["tool_results"] = tool_results
                state["messages"] = messages
            else:
                # No tool calls made - LLM responded directly
                logger.info("LLM responded without making tool calls")
                state["final_response"] = response.content
                state["tool_results"] = []

        except Exception as e:
            logger.error(f"Error in execute_search: {str(e)}")
            state["error_message"] = f"Search execution failed: {str(e)}"

        return state

    async def _format_response(self, state: SearchState) -> SearchState:
        """
        Format the tool results into a natural language response using LLM.
        """
        try:
            # If we already have a final response (LLM answered without tools), skip
            if state.get("final_response"):
                return state

            tool_results = state.get("tool_results", [])

            if not tool_results:
                state["final_response"] = (
                    "I searched but couldn't find any relevant information."
                )
                return state

            # Build formatting prompt
            results_summary = []
            for result in tool_results:
                tool_name = result.get("tool_name")
                tool_data = result.get("result")
                error = result.get("error")

                if error:
                    results_summary.append(f"- {tool_name}: Error - {error}")
                else:
                    # Truncate large results for the prompt
                    result_str = json.dumps(tool_data, default=str)
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "... (truncated)"
                    results_summary.append(f"- {tool_name}: {result_str}")

            format_prompt = SEARCH_FORMAT_RESULTS_PROMPT.format(
                query=state["query"],
                results_summary="\n".join(results_summary),
            )

            # Get formatted response from LLM using a clean message list —
            # avoids sending toolUse/toolResult blocks to Bedrock without toolConfig
            messages = [HumanMessage(content=format_prompt)]
            response = await self.llm.ainvoke(messages)

            state["final_response"] = response.content

        except Exception as e:
            logger.error(f"Error in format_response: {str(e)}")
            state["error_message"] = f"Failed to format response: {str(e)}"

        return state

    def _handle_error(self, state: SearchState) -> SearchState:
        """Handle errors in the workflow"""
        error_msg = state.get("error_message", "An unknown error occurred")
        state["final_response"] = f"❌ **Search Error**\n\n{error_msg}"
        logger.error(f"Search agent error: {error_msg}")
        return state

    def _route_after_search(self, state: SearchState) -> str:
        """Route after search execution"""
        if state.get("error_message"):
            return "error"
        else:
            return "format"

    async def search(self, query: str) -> Dict:
        """
        Perform a search based on the query using LLM function calling.

        Args:
            query: The search query

        Returns:
            Search results and formatted response
        """
        initial_state = SearchState(
            messages=[],
            query=query,
            tool_results=[],
            final_response=None,
            error_message=None,
            search_category=None,
        )

        final_state = await self.graph.ainvoke(initial_state)
        return final_state


# Example usage and testing
if __name__ == "__main__":

    async def main():
        search_agent = SearchAgent()

        # Test different types of searches
        test_queries = [
            "Find documentation about API authentication",
            "Show me ticket CBP-8446",
            "Search for recent bugs in the project",
        ]

        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")

            result = await search_agent.search(query)
            print(f"Response:\n{result.get('final_response')}")

            if result.get("error_message"):
                print(f"Error: {result.get('error_message')}")

            if result.get("tool_results"):
                print(f"\nTools called: {len(result.get('tool_results'))}")

    asyncio.run(main())
