#!/usr/bin/env python3
"""
GitLab integration component for agent workflows
"""

import re
import json
from typing import Dict, Any
from langgraph.types import Command
from langgraph.graph import END
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from .base_state import BaseState
from logger import setup_logger

logger = setup_logger(__name__)


class GitLabHandler:
    """Handles GitLab operations for agent workflows"""

    def __init__(self, project_id: str, dev_rules_path: str, dev_rules_branch: str):
        self.project_id = project_id
        self.dev_rules_path = dev_rules_path
        self.dev_rules_branch = dev_rules_branch

    async def load_development_rules(self, state: BaseState) -> Command:
        """Load all .md development rules files from GitLab directory"""
        try:
            async with multi_server_mcp_client.session("gitlab") as session:
                tools = await load_mcp_tools(session)
                get_tree_tool = next(
                    (tool for tool in tools if "get_repository_tree" in tool.name), None
                )
                get_file_tool = next(
                    (tool for tool in tools if "get_file_contents" in tool.name), None
                )

                if not get_tree_tool or not get_file_tool:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "GitLab repository tree or file contents tools not available",
                            "workflow_status": "error",
                        },
                    )

                clean_path = self.dev_rules_path.strip("/")

                tree_response = await get_tree_tool.ainvoke(
                    {
                        "project_id": self.project_id,
                        "path": clean_path,
                        "ref": self.dev_rules_branch,
                        "recursive": True,
                    }
                )

                tree_items = self._extract_tree_items(tree_response)
                md_files_content = {}

                for item in tree_items:
                    if self._is_md_file(item):
                        item_path = item.get("path", "")

                        try:
                            file_content = await get_file_tool.ainvoke(
                                {
                                    "project_id": self.project_id,
                                    "file_path": item_path,
                                    "ref": self.dev_rules_branch,
                                }
                            )

                            content = self._extract_file_content(file_content)
                            if content.strip():
                                md_files_content[item_path] = content

                        except Exception:
                            logger.exception(
                                "Exception occurred while extracting development rules."
                            )

                if md_files_content:
                    combined_rules = self._combine_md_files_content(md_files_content)

                    return Command(
                        goto="generate_code",
                        update={
                            "development_rules": combined_rules,
                            "workflow_status": "rules_loaded",
                            "messages": state["messages"]
                            + [
                                AIMessage(
                                    content=f"Successfully loaded development rules from {len(md_files_content)} .md files"
                                )
                            ],
                        },
                    )
                else:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": f"No .md files found in GitLab directory: {self.dev_rules_path}",
                            "workflow_status": "error",
                        },
                    )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error loading development rules from GitLab: {str(e)}",
                    "workflow_status": "error",
                },
            )

    @staticmethod
    async def create_branch_and_commit(state: BaseState) -> Command:
        """Create GitLab branch and commit generated code"""
        try:
            ticket_key = state["jira_ticket_key"]

            # Try to get Confluence design page title first for more contextual branch name
            feature_desc = (
                await GitLabHandler._extract_feature_description_from_confluence(state)
            )

            # If no Confluence title available, fall back to Jira ticket summary
            if not feature_desc:
                feature_desc = GitLabHandler._extract_feature_description_from_jira(
                    state
                )

            # Create branch name: feature/TICKET-word1-word2-word3-word4
            branch_name = f"feature/{ticket_key}-{feature_desc}"

            return Command(
                goto="commit_code",
                update={
                    "branch_name": branch_name,
                    "workflow_status": "branch_created",
                    "messages": state["messages"]
                    + [AIMessage(content=f"Prepared branch name: {branch_name}")],
                },
            )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error creating GitLab branch: {str(e)}",
                    "workflow_status": "error",
                },
            )

    @staticmethod
    async def _extract_feature_description_from_confluence(state: BaseState) -> str:
        """Extract feature description from Confluence design page title"""
        try:
            confluence_link = state.get("confluence_design_link")
            if not confluence_link:
                return ""

            async with multi_server_mcp_client.session("atlassian") as session:
                tools = await load_mcp_tools(session)
                confluence_tool = next(
                    (tool for tool in tools if "confluence_get_page" in tool.name), None
                )

                if not confluence_tool:
                    return ""

                page_id_match = re.search(r"/pages/(\d+)/", confluence_link)
                if not page_id_match:
                    return ""

                page_id = page_id_match.group(1)

                # Fetch page metadata to get the title
                page_data = await confluence_tool.ainvoke(
                    {
                        "page_id": page_id,
                        "convert_to_markdown": False,
                        "include_metadata": True,
                    }
                )

                if page_data:
                    # Extract title from page data
                    title = ""
                    if isinstance(page_data, dict):
                        title = page_data.get("title", "")
                    elif isinstance(page_data, str):
                        try:
                            parsed_data = json.loads(page_data)
                            title = parsed_data.get("title", "")
                        except json.JSONDecodeError:
                            # If it's not JSON, try to extract title from string
                            title_match = re.search(r'"title":\s*"([^"]*)"', page_data)
                            if title_match:
                                title = title_match.group(1)

                    if title:
                        # Clean and format the title for branch name
                        return GitLabHandler._format_title_for_branch(title)

        except Exception:
            logger.exception(
                "error while extracting feature description from confluence"
            )

        return ""

    @staticmethod
    def _extract_feature_description_from_jira(state: BaseState) -> str:
        """Extract feature description from Jira ticket summary as fallback"""
        ticket_summary = state["jira_ticket_data"].get("fields", {}).get("summary", "")

        if ticket_summary:
            return GitLabHandler._format_title_for_branch(ticket_summary)
        else:
            return "feature-implementation-task-update"

    @staticmethod
    def _format_title_for_branch(title: str) -> str:
        """Format title/summary for use in branch name"""
        if not title:
            return "feature-implementation-task-update"

        # Remove all non-alphanumeric characters except spaces, convert to lowercase
        clean_title = re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())

        # Split into words, filter out empty strings and common stop words
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
        }
        words = [
            word
            for word in clean_title.split()
            if word.strip() and word not in stop_words
        ]

        # Take first 4 meaningful words and join with hyphens
        if len(words) >= 4:
            feature_desc = "-".join(words[:4])
        elif len(words) > 0:
            # If less than 4 words, use what we have
            feature_desc = "-".join(words)
        else:
            feature_desc = "feature-implementation-task-update"

        return feature_desc

    async def commit_code(self, state: BaseState) -> Command:
        """Commit generated code to GitLab branch"""
        try:
            async with multi_server_mcp_client.session("gitlab") as session:
                tools = await load_mcp_tools(session)

                create_branch_tool = next(
                    (tool for tool in tools if "create_branch" in tool.name), None
                )
                create_file_tool = next(
                    (tool for tool in tools if "create_or_update_file" in tool.name),
                    None,
                )

                if not create_branch_tool or not create_file_tool:
                    return Command(
                        goto="handle_error",
                        update={
                            "error_message": "GitLab branch creation or file creation tools not available",
                            "workflow_status": "error",
                        },
                    )

                # Create branch from main
                await create_branch_tool.ainvoke(
                    {
                        "project_id": state["gitlab_project_id"],
                        "branch": state["branch_name"],
                        "ref": self.dev_rules_branch,
                    }
                )

                # Commit generated code to file
                commit_message = f"feat: {state['jira_ticket_key']} - Generated code from design requirements"

                await create_file_tool.ainvoke(
                    {
                        "project_id": state["gitlab_project_id"],
                        "file_path": "new_file.py",
                        "branch": state["branch_name"],
                        "content": state["generated_code"],
                        "commit_message": commit_message,
                    }
                )

            return Command(
                goto=END,
                update={
                    "workflow_status": "completed",
                    "messages": state["messages"]
                    + [
                        AIMessage(
                            content=f"Successfully committed code to branch: {state['branch_name']}"
                        )
                    ],
                },
            )

        except Exception as e:
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error committing code: {str(e)}",
                    "workflow_status": "error",
                },
            )

    def _extract_tree_items(self, tree_response):
        """Extract tree items from GitLab API response"""
        if isinstance(tree_response, list):
            return tree_response
        elif isinstance(tree_response, dict):
            return tree_response.get("tree", tree_response.get("items", []))
        elif isinstance(tree_response, str):
            try:
                parsed = json.loads(tree_response)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict):
                    return parsed.get("tree", parsed.get("items", []))
            except json.JSONDecodeError:
                pass
        return []

    def _is_md_file(self, item):
        """Check if item is a markdown file"""
        if isinstance(item, dict):
            item_type = item.get("type", "")
            item_path = item.get("path", "")
            return (
                item_type == "blob" or item_type == "file"
            ) and item_path.lower().endswith(".md")
        return False

    def _extract_file_content(self, file_content):
        """Extract content from GitLab file response"""
        if isinstance(file_content, str):
            return file_content
        elif isinstance(file_content, dict):
            return file_content.get("content", str(file_content))
        else:
            return str(file_content)

    def _combine_md_files_content(self, md_files_content: Dict[str, str]) -> str:
        """Combine content from multiple .md development rules files"""
        if not md_files_content:
            return ""

        combined_content = []
        combined_content.append("# Development Rules and Guidelines")
        combined_content.append("=" * 50)
        combined_content.append("")

        for file_path, content in md_files_content.items():
            combined_content.append(f"## File: {file_path}")
            combined_content.append("-" * 40)
            combined_content.append(content.strip())
            combined_content.append("")
            combined_content.append("=" * 50)
            combined_content.append("")

        return "\n".join(combined_content)
