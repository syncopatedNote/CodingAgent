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
    AIMessage,
    BaseMessage,
    ToolMessage,
)
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.llm_base import LLMFactory
from framework_base.multi_server_mcp_client import multi_server_mcp_client
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

        workflow.add_node("execute_search", self._execute_search)
        workflow.add_node("format_response", self._format_response)
        workflow.add_node("handle_error", self._handle_error)

        # Set entry point
        workflow.set_entry_point("execute_search")

        # Simple routing
        workflow.add_conditional_edges(
            "execute_search",
            self._route_after_search,
            {"format": "format_response", "error": "handle_error"},
        )

        # End nodes
        workflow.add_edge("format_response", END)
        workflow.add_edge("handle_error", END)

        return workflow.compile()

    async def _load_mcp_tools(self):
        """Load all available MCP tools from Atlassian server"""
        try:
            async with multi_server_mcp_client.session("github") as session:
                tools = await load_mcp_tools(session)
                logger.info(f"Loaded {len(tools)} MCP tools for search agent")
                return tools
        except Exception as e:
            logger.error(f"Failed to load MCP tools: {str(e)}")
            return []

    async def _execute_search(self, state: SearchState) -> SearchState:
        """
        Execute search using LLM with tool calling.
        The LLM decides which tools to call based on the query.
        """
        try:
            # Load available MCP tools
            tools = await self._load_mcp_tools()

            if not tools:
                state["error_message"] = (
                    "No MCP tools available. Please check MCP server connection."
                )
                return state

            # Bind tools to LLM
            llm_with_tools = self.llm.bind_tools(tools)

            # Build the prompt for the LLM
            search_prompt = f"""
                You are a search assistant with access to Confluence and Jira tools.
                User Query: {state['query']}

                Your task:
                1. Analyze what the user is looking for
                2. Use the appropriate tools to find the information
                3. You can call multiple tools if needed

                Available tool capabilities:
                - confluence_search: Search Confluence pages/documentation
                - jira_get_issue: Get details of a specific Jira ticket (use
                  when ticket ID mentioned like PROJ-123)

                Think about what the user needs and call the appropriate tool(s).
            """

            # Add the search prompt to messages
            messages = state["messages"] + [HumanMessage(content=search_prompt)]

            # Let LLM make tool calls
            response = await llm_with_tools.ainvoke(messages)

            # Check if LLM made tool calls
            if hasattr(response, "tool_calls") and response.tool_calls:
                logger.info(f"LLM made {len(response.tool_calls)} tool call(s)")
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
                            tool_results.append(
                                {
                                    "tool_name": tool_name,
                                    "error": "Tool not found",
                                }
                            )

                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {str(e)}")
                        tool_results.append(
                            {
                                "tool_name": tool_name,
                                "error": str(e),
                            }
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

            format_prompt = f"""
                Based on the search results below, provide a clear, helpful
                response to the user's question.

                Original Query: {state['query']}

                Search Results:
                {chr(10).join(results_summary)}

                Instructions:
                1. Summarize the key findings in a natural, conversational way
                2. If searching Jira tickets, include: ticket ID, summary,
                   status, and key details.
                3. If searching Confluence, include: page titles, relevant
                   excerpts, and links if available.
                4. If no useful results, say so clearly
                5. Format nicely with markdown (headers, bullet points, etc.)

                Provide your response now:"""

            # Get formatted response from LLM
            messages = state["messages"] + [HumanMessage(content=format_prompt)]
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

    async def search(
        self, query: str, conversation_history: List[BaseMessage] = None
    ) -> Dict:
        """
        Perform a search based on the query using LLM function calling.

        Args:
            query: The search query
            conversation_history: Previous conversation messages (for context)

        Returns:
            Search results and formatted response
        """
        initial_state = SearchState(
            messages=conversation_history or [],
            query=query,
            tool_results=[],
            final_response=None,
            error_message=None,
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
