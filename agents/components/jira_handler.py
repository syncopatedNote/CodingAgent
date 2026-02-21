#!/usr/bin/env python3
"""
Jira integration component for agent workflows
"""

import json
from typing import Dict
from langgraph.types import Command
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from .base_state import BaseState


class JiraHandler:
    """Handles Jira ticket operations for agent workflows"""

    @staticmethod
    async def fetch_ticket(state: BaseState) -> Command:
        """Fetch Jira ticket details using MCP tools"""
        try:
            ticket_key = state["jira_ticket_key"]

            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                jira_tool = next(
                    (tool for tool in tools if "jira_get_issue" in tool.name), None
                )

                if not jira_tool:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "Jira get issue tool not available",
                            "workflow_status": "error",
                        },
                    )

                ticket_data = await jira_tool.ainvoke(
                    {
                        "issue_key": ticket_key,
                        "fields": "summary,description,comment",
                        "comment_limit": 50,
                    }
                )

                if ticket_data:
                    if isinstance(ticket_data, str):
                        ticket_data = json.loads(ticket_data)

                    return Command(
                        goto="extract_confluence_link",
                        update={
                            "jira_ticket_data": ticket_data,
                            "workflow_status": "jira_fetched",
                            "messages": state["messages"]
                            + [
                                AIMessage(
                                    content=f"Successfully fetched Jira ticket: {ticket_key}"
                                )
                            ],
                        },
                    )
                else:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": f"Failed to fetch Jira ticket: {ticket_key}",
                            "workflow_status": "error",
                        },
                    )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error fetching Jira ticket: {str(e)}",
                    "workflow_status": "error",
                },
            )

    @staticmethod
    def extract_ticket_info(state: BaseState) -> Dict[str, str]:
        """Extract ticket summary and description from state"""
        ticket_data = state.get("jira_ticket_data", {})
        fields = ticket_data.get("fields", {})

        return {
            "summary": fields.get("summary", "summary not available"),
            "description": fields.get("description", "description not available"),
        }
