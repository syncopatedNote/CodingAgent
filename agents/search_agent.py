#!/usr/bin/env python3
"""
Search Agent
Handles all search operations across Confluence, Jira, and other systems using MCP tools.
"""

import re
import json
import asyncio
from typing import Dict, List, Optional, TypedDict, Annotated
from enum import Enum

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.llm_base import LLMFactory
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from agents.models.jira_response_model import JiraResponse
from pydantic import ValidationError
from settings import settings


class SearchType(Enum):
    """Types of searches the agent can perform"""

    CONFLUENCE_SEARCH = "confluence_search"
    JIRA_TICKET_LOOKUP = "jira_ticket_lookup"
    JIRA_SEARCH = "jira_search"
    GENERAL_SEARCH = "general_search"


class SearchState(TypedDict):
    """State for the search agent workflow"""

    messages: Annotated[List[BaseMessage], "Conversation messages"]
    search_query: str
    search_type: Optional[SearchType]
    extracted_entities: Dict
    search_results: Optional[List[Dict]]
    formatted_response: Optional[str]
    error_message: Optional[str]


class SearchAgent:
    def __init__(self):
        """Initialize the search agent"""
        # self.llm = LLMFactory.create_llm(
        #     provider="ollama",
        #     model_name="llama3:8b",
        #     model_type="chat",
        #     temperature=0.3
        # )

        # Build the workflow graph
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the search workflow graph"""
        workflow = StateGraph(SearchState)

        # Add nodes
        workflow.add_node("analyze_search_query", self._analyze_search_query)
        workflow.add_node("search_confluence", self._search_confluence)
        workflow.add_node("lookup_jira_ticket", self._lookup_jira_ticket)
        workflow.add_node("search_jira", self._search_jira)
        workflow.add_node("format_results", self._format_results)
        workflow.add_node("handle_error", self._handle_error)

        # Set entry point
        workflow.set_entry_point("analyze_search_query")

        # Add conditional routing from search analysis
        workflow.add_conditional_edges(
            "analyze_search_query",
            self._route_after_analysis,
            {
                "confluence_search": "search_confluence",
                "jira_ticket_lookup": "lookup_jira_ticket",
                "jira_search": "search_jira",
                "error": "handle_error",
            },
        )

        # All search operations route to formatting
        workflow.add_conditional_edges(
            "search_confluence",
            self._route_after_search,
            {"format": "format_results", "error": "handle_error"},
        )

        workflow.add_conditional_edges(
            "lookup_jira_ticket",
            self._route_after_search,
            {"format": "format_results", "error": "handle_error"},
        )

        workflow.add_conditional_edges(
            "search_jira",
            self._route_after_search,
            {"format": "format_results", "error": "handle_error"},
        )

        # End nodes
        workflow.add_edge("format_results", END)
        workflow.add_edge("handle_error", END)

        return workflow.compile()

    def _analyze_search_query(self, state: SearchState) -> SearchState:
        """Analyze the search query to determine search type and extract entities"""
        try:
            search_query = state["search_query"]

            # Extract entities using regex patterns
            entities = self._extract_entities(search_query)
            state["extracted_entities"] = entities

            # Determine search type based on entities and keywords
            search_type = self._determine_search_type(search_query, entities)
            state["search_type"] = search_type

        except Exception as e:
            state["error_message"] = f"Error analyzing search query: {str(e)}"

        return state

    def _extract_entities(self, query: str) -> Dict:
        """Extract entities from the search query"""
        entities = {
            "jira_tickets": [],
            "confluence_keywords": [],
            "search_keywords": [],
            "project_names": [],
        }

        # Extract Jira ticket patterns (e.g., PROJ-123, ABC-456)
        jira_pattern = r"\b[A-Z]+-\d+\b"
        jira_matches = re.findall(jira_pattern, query)
        entities["jira_tickets"] = jira_matches

        # Extract Confluence-specific keywords
        confluence_keywords = [
            "documentation",
            "wiki",
            "page",
            "confluence",
            "design",
            "spec",
        ]
        found_confluence_keywords = [
            kw for kw in confluence_keywords if kw.lower() in query.lower()
        ]
        entities["confluence_keywords"] = found_confluence_keywords

        # Extract general search keywords (words longer than 3 characters)
        words = re.findall(r"\b\w{4,}\b", query.lower())
        # Filter out common words
        stop_words = {
            "with",
            "from",
            "that",
            "this",
            "have",
            "will",
            "been",
            "were",
            "they",
            "there",
        }
        keywords = [word for word in words if word not in stop_words]
        entities["search_keywords"] = keywords[:5]  # Limit to 5 keywords

        # Extract potential project names (uppercase words)
        project_pattern = r"\b[A-Z]{2,10}\b"
        project_matches = re.findall(project_pattern, query)
        # Filter out Jira ticket prefixes
        jira_prefixes = [ticket.split("-")[0] for ticket in jira_matches]
        projects = [proj for proj in project_matches if proj not in jira_prefixes]
        entities["project_names"] = projects

        return entities

    def _determine_search_type(self, query: str, entities: Dict) -> SearchType:
        """Determine the type of search based on query and entities"""
        query_lower = query.lower()

        # If specific Jira ticket is mentioned, do ticket lookup
        if entities["jira_tickets"]:
            return SearchType.JIRA_TICKET_LOOKUP

        # If Confluence-specific keywords are present
        elif entities["confluence_keywords"] or any(
            kw in query_lower
            for kw in ["confluence", "documentation", "wiki", "page", "design"]
        ):
            return SearchType.CONFLUENCE_SEARCH

        # If Jira-specific keywords are present
        elif any(
            kw in query_lower
            for kw in ["jira", "ticket", "issue", "bug", "story", "epic", "task"]
        ):
            return SearchType.JIRA_SEARCH

        # Default to Confluence search for general queries
        else:
            return SearchType.CONFLUENCE_SEARCH

    async def _search_confluence(self, state: SearchState) -> SearchState:
        """Search Confluence using MCP tools"""
        try:
            # Build search query from keywords
            keywords = state["extracted_entities"].get("search_keywords", [])
            confluence_keywords = state["extracted_entities"].get(
                "confluence_keywords", []
            )

            # Combine keywords for search
            all_keywords = keywords + confluence_keywords
            search_terms = (
                " ".join(all_keywords[:3]) if all_keywords else state["search_query"]
            )

            # Call Confluence search MCP tool using the proper session pattern
            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                confluence_search_tool = next(
                    (tool for tool in tools if "confluence_search" in tool.name), None
                )

                if confluence_search_tool:
                    search_result = await confluence_search_tool.ainvoke(
                        {"query": search_terms, "limit": 5}
                    )

                    if search_result:
                        # Parse the results if they're in string format
                        if isinstance(search_result, str):
                            try:
                                results_data = json.loads(search_result)
                            except json.JSONDecodeError:
                                results_data = {"results": []}
                        else:
                            results_data = search_result

                        state["search_results"] = results_data.get(
                            "results",
                            results_data if isinstance(results_data, list) else [],
                        )
                    else:
                        state["search_results"] = []
                else:
                    state["error_message"] = "Confluence search tool not available"

        except Exception as e:
            state["error_message"] = f"Error searching Confluence: {str(e)}"

        return state

    async def _lookup_jira_ticket(self, state: SearchState) -> SearchState:
        """Look up specific Jira ticket(s)"""
        try:
            jira_tickets = state["extracted_entities"].get("jira_tickets", [])

            if not jira_tickets:
                state["error_message"] = "No Jira ticket keys found in query"
                return state

            results = []

            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                jira_get_issue_tool = next(
                    (tool for tool in tools if "jira_get_issue" in tool.name), None
                )

                if not jira_get_issue_tool:
                    state["error_message"] = "Jira get issue tool not available"
                    return state

                for ticket_key in jira_tickets:
                    try:
                        # Get detailed ticket information using MCP tool
                        ticket_result = await jira_get_issue_tool.ainvoke(
                            {
                                "issue_key": ticket_key,
                                "fields": "summary,description,status,assignee,reporter,priority,issuetype,created,updated,labels",
                                "comment_limit": 5,
                            }
                        )

                        if ticket_result:
                            if isinstance(ticket_result, str):
                                try:
                                    ticket_info = json.loads(ticket_result)
                                except json.JSONDecodeError:
                                    ticket_info = {
                                        "error": f"Invalid response format for {ticket_key}"
                                    }
                            else:
                                ticket_info = ticket_result

                            results.append(ticket_info)
                        else:
                            results.append(
                                {"error": f"No data returned for {ticket_key}"}
                            )

                    except Exception as e:
                        # Continue with other tickets if one fails
                        results.append(
                            {"error": f"Failed to fetch {ticket_key}: {str(e)}"}
                        )

            state["search_results"] = results

        except Exception as e:
            state["error_message"] = f"Error looking up Jira tickets: {str(e)}"

        return state

    async def _search_jira(self, state: SearchState) -> SearchState:
        """Search Jira issues using JQL"""
        try:
            # Build JQL query from entities and keywords
            jql_query = self._build_jql_query(state)

            # Call Jira search MCP tool using the proper session pattern
            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                jira_search_tool = next(
                    (tool for tool in tools if "jira_search" in tool.name), None
                )

                if jira_search_tool:
                    search_result = await jira_search_tool.ainvoke(
                        {
                            "jql": jql_query,
                            "limit": 10,
                            "fields": "summary,status,assignee,priority,issuetype,updated,created",
                        }
                    )

                    if search_result:
                        if isinstance(search_result, str):
                            try:
                                results_data = json.loads(search_result)
                            except json.JSONDecodeError:
                                results_data = {"issues": []}
                        else:
                            results_data = search_result

                        state["search_results"] = results_data.get("issues", [])
                    else:
                        state["search_results"] = []
                else:
                    state["error_message"] = "Jira search tool not available"

        except Exception as e:
            state["error_message"] = f"Error searching Jira: {str(e)}"

        return state

    def _build_jql_query(self, state: SearchState) -> str:
        """Build JQL query from extracted entities"""
        entities = state["extracted_entities"]
        query = state["search_query"].lower()

        jql_parts = []

        # Add project filter if available
        projects = entities.get("project_names", [])
        if projects:
            project_filter = " OR ".join([f'project = "{p}"' for p in projects])
            jql_parts.append(f"({project_filter})")

        # Add text search based on keywords
        keywords = entities.get("search_keywords", [])
        if keywords:
            search_terms = " ".join(keywords[:3])
            jql_parts.append(f'text ~ "{search_terms}"')

        # Add status filters based on query content
        if any(word in query for word in ["open", "active", "in progress"]):
            jql_parts.append('status NOT IN ("Done", "Closed", "Resolved")')
        elif any(word in query for word in ["closed", "done", "resolved"]):
            jql_parts.append('status IN ("Done", "Closed", "Resolved")')

        # Add issue type filters
        if "bug" in query:
            jql_parts.append('issuetype = "Bug"')
        elif "story" in query:
            jql_parts.append('issuetype = "Story"')
        elif "epic" in query:
            jql_parts.append('issuetype = "Epic"')

        # Add time-based filters
        if "recent" in query or "latest" in query:
            jql_parts.append("updated >= -7d")

        # Combine parts or use default
        if jql_parts:
            return " AND ".join(jql_parts) + " ORDER BY updated DESC"
        else:
            return "project is not EMPTY ORDER BY updated DESC"

    def _format_results(self, state: SearchState) -> SearchState:
        """Format search results for display"""
        try:
            search_type = state["search_type"]
            results = state["search_results"]

            if not results:
                state["formatted_response"] = "No results found for your search query."
                return state

            if search_type == SearchType.CONFLUENCE_SEARCH:
                state["formatted_response"] = self._format_confluence_results(results)
            elif search_type == SearchType.JIRA_TICKET_LOOKUP:
                state["formatted_response"] = self._format_jira_ticket_details(results)
            elif search_type == SearchType.JIRA_SEARCH:
                state["formatted_response"] = self._format_jira_search_results(results)
            else:
                state["formatted_response"] = (
                    "Search completed but results format not recognized."
                )

        except Exception as e:
            state["error_message"] = f"Error formatting results: {str(e)}"

        return state

    def _format_confluence_results(self, results: List[Dict]) -> str:
        """Format Confluence search results with improved readability"""
        if not results:
            return "No Confluence documents found."

        formatted_parts = []
        formatted_parts.append(f"# 📚 Found {len(results)} Confluence Document(s)")
        formatted_parts.append("")

        for i, result in enumerate(results[:5], 1):
            title = result.get("title", "Untitled")
            space = result.get("space", {}).get("name", "Unknown Space")
            url = result.get("_links", {}).get("webui", "")
            excerpt = result.get("excerpt", "")

            # Create a card-like format for each document
            formatted_parts.append(f"## {i}. 📄 {title}")
            formatted_parts.append("")
            formatted_parts.append(f"**Space:** {space}")

            if excerpt:
                # Clean up excerpt and limit length
                clean_excerpt = " ".join(excerpt.split())
                if len(clean_excerpt) > 200:
                    clean_excerpt = clean_excerpt[:200] + "..."
                formatted_parts.append(f"**Excerpt:** {clean_excerpt}")

            if url:
                formatted_parts.append(f"**Link:** [View Page]({url})")

            formatted_parts.append("")
            formatted_parts.append("---")
            formatted_parts.append("")

        return "\n".join(formatted_parts)

    def _format_jira_ticket_details(self, results: List[Dict]) -> str:
        """
        Format detailed Jira ticket information using Pydantic model
        for validation and parsing.

        Args:
            results: List of raw Jira ticket data from API

        Returns:
            Formatted string representation of ticket details with\
            improved readability
        """
        if not results:
            return "No Jira tickets found."

        formatted_parts = []

        # Add header if multiple tickets
        if len(results) > 1:
            formatted_parts.append(f"# 📋 Found {len(results)} Jira Ticket(s)")
            formatted_parts.append("")

        for i, result in enumerate(results, 1):
            # Handle error responses
            if "error" in result:
                formatted_parts.append(
                    f"❌ **Error for ticket {i}:** {result['error']}"
                )
                formatted_parts.append("")
                continue

            try:
                # Parse the raw result using Pydantic model
                jira_issue = JiraResponse(**result)

                # Add ticket number prefix for multiple tickets
                if len(results) > 1:
                    formatted_parts.append(f"### Ticket {i} of {len(results)}")
                    formatted_parts.append("")

                # Format using the validated Pydantic model
                formatted_ticket = self._format_single_jira_ticket(jira_issue)
                formatted_parts.append(formatted_ticket)

            except ValidationError as e:
                # Handle validation errors gracefully
                key = result.get("key", "Unknown")
                formatted_parts.append(
                    f"❌ **Error parsing ticket {key}:** Invalid data format"
                )
                formatted_parts.append(f"**Validation errors:** {str(e)}")
                formatted_parts.append("")

            except Exception as e:
                # Handle any other parsing errors
                key = result.get("key", "Unknown")
                formatted_parts.append(
                    f"❌ **Error processing ticket {key}:** {str(e)}"
                )
                formatted_parts.append("")

        return "\n".join(formatted_parts)

    def _format_single_jira_ticket(self, jira_issue: JiraResponse) -> str:
        """
        Format a single Jira ticket using the validated Pydantic model
        with improved readability.

        Args:
            jira_issue: Validated JiraResponse instance

        Returns:
            Formatted string for a single ticket with proper structure
            and spacing
        """
        # Create a formatted ticket card with clear sections
        formatted_lines = []

        # Header with ticket key and summary
        formatted_lines.append(f"## 🎫 {jira_issue.key}: {jira_issue.summary}")
        formatted_lines.append("")  # Empty line for spacing

        # Status and Priority section
        status_category = (
            f" ({jira_issue.status.category})" if jira_issue.status.category else ""
        )
        formatted_lines.append(f"**📊 Status & Priority:**")
        formatted_lines.append(
            f"   • Status: `{jira_issue.status.name}`{status_category}"
        )
        formatted_lines.append(f"   • Priority: `{jira_issue.priority.name}`")

        # Add issue type if available
        if hasattr(jira_issue, "issue_type") and jira_issue.issue_type:
            issue_type = (
                jira_issue.issue_type.get("name", "Unknown")
                if isinstance(jira_issue.issue_type, dict)
                else str(jira_issue.issue_type)
            )
            formatted_lines.append(f"   • Type: `{issue_type}`")

        formatted_lines.append("")  # Empty line for spacing

        # People section
        assignee_name = (
            jira_issue.assignee.display_name if jira_issue.assignee else "Unassigned"
        )
        reporter_name = jira_issue.reporter.display_name
        formatted_lines.append(f"**👥 People:**")
        formatted_lines.append(f"   • Assignee: {assignee_name}")
        formatted_lines.append(f"   • Reporter: {reporter_name}")
        formatted_lines.append("")  # Empty line for spacing

        # Dates section
        created_date = (
            jira_issue.created[:10]
            if len(jira_issue.created) >= 10
            else jira_issue.created
        )
        updated_date = (
            jira_issue.updated[:10]
            if len(jira_issue.updated) >= 10
            else jira_issue.updated
        )
        formatted_lines.append(f"**📅 Timeline:**")
        formatted_lines.append(f"   • Created: {created_date}")
        formatted_lines.append(f"   • Updated: {updated_date}")

        # Add due date if available
        if hasattr(jira_issue, "due_date") and jira_issue.due_date:
            due_date = (
                jira_issue.due_date[:10]
                if len(jira_issue.due_date) >= 10
                else jira_issue.due_date
            )
            formatted_lines.append(f"   • Due Date: {due_date}")

        formatted_lines.append("")  # Empty line for spacing

        # Labels section (only if labels exist)
        if jira_issue.labels:
            labels_str = ", ".join([f"`{label}`" for label in jira_issue.labels])
            formatted_lines.append(f"**🏷️ Labels:** {labels_str}")
            formatted_lines.append("")  # Empty line for spacing

        # Additional metadata section
        additional_items = []

        # Add story points if available
        if hasattr(jira_issue, "story_points") and jira_issue.story_points:
            additional_items.append(f"Story Points: {jira_issue.story_points}")

        # Add epic information if available
        if hasattr(jira_issue, "epic_link") and jira_issue.epic_link:
            additional_items.append(f"Epic: {jira_issue.epic_link}")

        # Add resolution information if resolved
        if hasattr(jira_issue, "resolution") and jira_issue.resolution:
            resolution_name = (
                jira_issue.resolution.get("name", "Resolved")
                if isinstance(jira_issue.resolution, dict)
                else str(jira_issue.resolution)
            )
            additional_items.append(f"Resolution: {resolution_name}")

        if additional_items:
            formatted_lines.append(f"**📊 Additional Info:**")
            for item in additional_items:
                formatted_lines.append(f"   • {item}")
            formatted_lines.append("")  # Empty line for spacing

        # Description section
        description = jira_issue.description or "No description provided"

        # Clean up description formatting and handle length
        description = " ".join(description.split())  # Remove excessive whitespace

        formatted_lines.append(f"**📝 Description:**")

        # Handle long descriptions by breaking them into readable chunks
        if len(description) > 500:
            # Split into sentences and group them
            sentences = description.split(". ")
            current_chunk = ""

            for sentence in sentences:
                if len(current_chunk + sentence) < 200:
                    current_chunk += sentence + ". "
                else:
                    if current_chunk:
                        formatted_lines.append(f"   {current_chunk.strip()}")
                        formatted_lines.append("")
                    current_chunk = sentence + ". "

            # Add remaining chunk
            if current_chunk:
                formatted_lines.append(f"   {current_chunk.strip()}")

            # Add truncation notice if still too long
            if len(description) > 800:
                formatted_lines.append("   ...")
                formatted_lines.append("   *(Description truncated for readability)*")
        else:
            # For shorter descriptions, just add them directly
            formatted_lines.append(f"   {description}")

        formatted_lines.append("")  # Empty line for spacing
        formatted_lines.append("---")  # Separator line
        formatted_lines.append("")  # Empty line for spacing

        return "\n".join(formatted_lines)

    def _format_jira_search_results(self, results: List[Dict]) -> str:
        """Format Jira search results with improved readability"""
        if not results:
            return "No Jira issues found."

        formatted_parts = []
        formatted_parts.append(f"# 🔍 Found {len(results)} Jira Issue(s)")
        formatted_parts.append("")

        for i, issue in enumerate(results[:10], 1):
            key = issue.get("key", "")
            fields = issue.get("fields", {})
            summary = fields.get("summary", "No summary")
            status = fields.get("status", {}).get("name", "Unknown")
            priority = fields.get("priority", {}).get("name", "Unknown")
            assignee = fields.get("assignee")
            assignee_name = (
                assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
            )
            updated = fields.get("updated", "")[:10] if fields.get("updated") else ""

            # Create a card-like format for each issue
            formatted_parts.append(f"## {i}. 🎫 {key}: {summary}")
            formatted_parts.append("")
            formatted_parts.append(
                f"**Status:** `{status}` | **Priority:** `{priority}` | **Assignee:** {assignee_name}"
            )

            if updated:
                formatted_parts.append(f"**Last Updated:** {updated}")

            formatted_parts.append("")
            formatted_parts.append("---")
            formatted_parts.append("")

        return "\n".join(formatted_parts)

    def _handle_error(self, state: SearchState) -> SearchState:
        """Handle errors in the search workflow"""
        error_msg = state.get("error_message", "An unknown search error occurred")
        state["formatted_response"] = f"Search Error: {error_msg}"
        return state

    # Routing functions
    def _route_after_analysis(self, state: SearchState) -> str:
        """Route after search query analysis"""
        if state.get("error_message"):
            return "error"

        search_type = state.get("search_type")
        if search_type == SearchType.CONFLUENCE_SEARCH:
            return "confluence_search"
        elif search_type == SearchType.JIRA_TICKET_LOOKUP:
            return "jira_ticket_lookup"
        elif search_type == SearchType.JIRA_SEARCH:
            return "jira_search"
        else:
            return "error"

    def _route_after_search(self, state: SearchState) -> str:
        """Route after search operations"""
        if state.get("error_message"):
            return "error"
        else:
            return "format"

    async def search(
        self, query: str, conversation_history: List[BaseMessage] = None
    ) -> Dict:
        """
        Perform a search based on the query

        Args:
            query: The search query
            conversation_history: Previous conversation messages (for context)

        Returns:
            Search results and formatted response
        """
        initial_state = SearchState(
            messages=conversation_history or [],
            search_query=query,
            search_type=None,
            extracted_entities={},
            search_results=None,
            formatted_response=None,
            error_message=None,
        )

        final_state = await self.graph.ainvoke(initial_state)
        return final_state


# Example usage and testing
if __name__ == "__main__":
    import asyncio

    async def main():
        search_agent = SearchAgent()

        # Test different types of searches
        test_queries = [
            # "Find documentation about API authentication",
            "Show me ticket CBP-8446"
            # "Search for recent bugs in DEV project",
            # "Look for confluence pages about deployment",
            # "Find all open stories assigned to John"
        ]

        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")

            result = await search_agent.search(query)
            print(f"Search Type: {result.get('search_type')}")
            print(f"Entities: {result.get('extracted_entities')}")
            print(f"Response:\n{result.get('formatted_response')}")

            if result.get("error_message"):
                print(f"Error: {result.get('error_message')}")

    asyncio.run(main())
