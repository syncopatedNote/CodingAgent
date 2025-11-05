#!/usr/bin/env python3
"""
Confluence integration component for agent workflows
"""

import re
import json
from typing import Optional
from langgraph.types import Command, interrupt
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from .base_state import BaseState


class ConfluenceHandler:
    """Handles Confluence operations for agent workflows"""
    
    @staticmethod
    def find_confluence_link(text: str) -> Optional[str]:
        """Find Confluence link in text using regex"""
        if not text:
            return None
        
        confluence_pattern = r'https://confluence\.com[^\s\)]*'
        match = re.search(confluence_pattern, text, re.IGNORECASE)
        return match.group(0) if match else None
    
    @staticmethod
    async def extract_confluence_link(state: BaseState) -> Command:
        """Extract Confluence design link from Jira ticket"""
        try:
            ticket_data = state["jira_ticket_data"]
            confluence_link = None

            # Check description first
            description = ticket_data.get("description", "")
            confluence_link = ConfluenceHandler.find_confluence_link(description)

            # If not found in description, check comments
            if not confluence_link:
                comments = ticket_data.get("comments", [])
                for comment in comments:
                    comment_body = comment.get("body", "")
                    confluence_link = ConfluenceHandler.find_confluence_link(comment_body)
                    if confluence_link:
                        break

            if confluence_link:
                return Command(
                    goto="fetch_confluence_design",
                    update={
                        "confluence_design_link": confluence_link,
                        "workflow_status": "confluence_link_found",
                        "messages": state["messages"] + [
                            AIMessage(content=f"Found Confluence design link: {confluence_link}")
                        ]
                    }
                )
            else:
                confluence_link = interrupt({
                    "message": "No Confluence design link found in the Jira ticket. Please provide the Confluence design page link to continue.",
                    "required_input": "confluence_link",
                    "workflow_status": "awaiting_confluence_link"
                })

                return Command(
                    goto="fetch_confluence_design",
                    update={
                        "confluence_design_link": confluence_link,
                        "workflow_status": "confluence_link_provided",
                        "user_input_required": None,
                        "messages": state["messages"] + [
                            AIMessage(content=f"Received Confluence link: {confluence_link}. Proceeding to fetch design content.")
                        ]
                    }
                )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error extracting Confluence link: {str(e)}",
                    "workflow_status": "error"
                }
            )
    
    @staticmethod
    async def fetch_design_content(state: BaseState) -> Command:
        """Fetch Confluence design content using MCP tools"""
        try:
            confluence_link = state.get("confluence_design_link")
            
            if not confluence_link:
                return Command(
                    goto="request_confluence_link",
                    update={
                        "user_input_required": "confluence_link",
                        "workflow_status": "awaiting_confluence_link"
                    }
                )

            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                confluence_tool = next((tool for tool in tools if "confluence_get_page" in tool.name), None)
                
                if not confluence_tool:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "Confluence get page tool not available",
                            "workflow_status": "error"
                        }
                    )

                page_id_match = re.search(r'/pages/(\d+)/', confluence_link)
                
                if not page_id_match:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "Could not extract page ID from Confluence URL",
                            "workflow_status": "error"
                        }
                    )

                page_id = page_id_match.group(1)
                design_content = await confluence_tool.ainvoke({
                    "page_id": page_id,
                    "convert_to_markdown": True,
                    "include_metadata": True
                })

                if design_content:
                    content = design_content
                    if isinstance(design_content, dict):
                        content = design_content.get("content", {})
                        if isinstance(content, dict):
                            content = content.get("value", str(design_content))
                        else:
                            content = str(content)
                    else:
                        content = str(design_content)

                    return Command(
                        goto="load_development_rules",
                        update={
                            "confluence_design_content": content,
                            "workflow_status": "confluence_fetched",
                            "user_input_required": None,
                            "messages": state["messages"] + [
                                AIMessage(content="Successfully fetched Confluence design content")
                            ]
                        }
                    )
                else:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "Failed to fetch Confluence design content",
                            "workflow_status": "error"
                        }
                    )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error fetching Confluence design: {str(e)}",
                    "workflow_status": "error"
                }
            )