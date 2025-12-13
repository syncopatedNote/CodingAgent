#!/usr/bin/env python3
"""
Refactored LangGraph Coding Agent with modular components
"""

import asyncio
from typing import Dict, List, Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langchain_core.messages import HumanMessage, AIMessage
from framework_base.llm_base import LLMFactory
from settings import settings

from .components import (
    JiraHandler,
    ConfluenceHandler,
    CodeGenerator,
    GitLabHandler
)


# State definition for maintaining workflow context
class AgentState(TypedDict):
    messages: Annotated[List, "Messages in the conversation"]
    jira_ticket_key: Optional[str]
    jira_ticket_data: Optional[Dict]
    confluence_design_link: Optional[str]
    confluence_design_content: Optional[str]
    development_rules: Optional[str]
    generated_code: Optional[str]
    branch_name: Optional[str]
    gitlab_project_id: Optional[str]
    error_message: Optional[str]
    user_input_required: Optional[str]
    enhanced_context: Optional[str]
    workflow_status: Optional[str]
    reflection_feedback: Optional[str]
    reflection_count: Optional[int]


class CodingAgent:
    def __init__(
        self,
        gitlab_project_id: str,
        development_rules_path: str = "./development_rules.md",
        development_rules_branch: str = "main",
    ):
        """Initialize the refactored coding agent with modular components"""

        # Initialize LLM using settings
        llm_kwargs = {"temperature": 0.5}

        # Add base_url for ollama if provider is ollama
        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        self.gitlab_project_id = gitlab_project_id

        # Initialize component handlers
        self.jira_handler = JiraHandler()
        self.confluence_handler = ConfluenceHandler()
        self.code_generator = CodeGenerator(self.llm)
        self.gitlab_handler = GitLabHandler(
            gitlab_project_id, development_rules_path, development_rules_branch
        )

        # Build the graph
        self.graph = self._build_graph()
        # print(self.graph.draw_mermaid())

    def _build_graph(self):
        """Build the LangGraph workflow using modular components"""
        workflow = StateGraph(AgentState)

        # Add nodes using component methods
        workflow.add_node("fetch_jira_ticket", self.jira_handler.fetch_ticket)
        workflow.add_node(
            "extract_confluence_link",
            self.confluence_handler.extract_confluence_link
        )
        workflow.add_node(
            "fetch_confluence_design",
            self.confluence_handler.fetch_design_content
        )
        workflow.add_node(
            "load_development_rules",
            self.gitlab_handler.load_development_rules
        )
        workflow.add_node(
            "generate_code",
            self.code_generator.generate_code
        )
        workflow.add_node(
            "reflect_code",
            self.code_generator.reflect_code
        )
        workflow.add_node(
            "create_gitlab_branch",
            self.gitlab_handler.create_branch_and_commit
        )
        workflow.add_node(
            "commit_code",
            self.gitlab_handler.commit_code
        )
        workflow.add_node(
            "handle_error",
            self._handle_error
        )

        workflow.set_entry_point("fetch_jira_ticket")
        return workflow.compile()

    async def _handle_error(self, state: AgentState) -> Command:
        """Handle errors in the workflow and end with error state"""
        error_msg = state.get("error_message", "Unknown error occurred")

        return Command(
            goto=END,
            update={
                "workflow_status": "error",
                "messages": state["messages"]
                + [AIMessage(content=f"Error: {error_msg}")],
            },
        )

    async def run(
        self,
        jira_ticket_key: str,
        confluence_link: Optional[str] = None,
        enhanced_context: Optional[str] = None,
    ) -> Dict:
        """Run the coding agent workflow"""
        initial_message = f"Process Jira ticket: {jira_ticket_key}"
        if enhanced_context:
            initial_message += f"\nEnhanced context: {enhanced_context}"

        initial_state = AgentState(
            messages=[HumanMessage(content=initial_message)],
            jira_ticket_key=jira_ticket_key,
            confluence_design_link=confluence_link,
            gitlab_project_id=self.gitlab_project_id,
            jira_ticket_data=None,
            confluence_design_content=None,
            development_rules=None,
            generated_code=None,
            branch_name=None,
            error_message=None,
            user_input_required=None,
            enhanced_context=initial_message,
            workflow_status="initialized",
            reflection_feedback=None,
            reflection_count=0,  # Initialize to 0 instead of None
        )

        try:
            final_state = await self.graph.ainvoke(initial_state)

            return {
                "success": final_state.get("workflow_status")
                not in ["error", "user_input_required"],
                "workflow_status": final_state.get("workflow_status", "unknown"),
                "state": dict(final_state),
                "messages": final_state.get("messages", []),
                "final_response": self._get_final_response(final_state),
                "error": (
                    final_state.get("error_message")
                    if final_state.get("workflow_status") == "error"
                    else None
                ),
            }

        except Exception as e:
            return {
                "success": False,
                "workflow_status": "error",
                "error": str(e),
                "final_response": f"Error running coding agent: {str(e)}",
                "state": dict(initial_state),
                "messages": initial_state.get("messages", []),
            }

    def _get_final_response(self, state: AgentState) -> str:
        """Generate a final response based on the workflow status"""
        status = state.get("workflow_status", "unknown")
        reflection_count = state.get("reflection_count", 0)

        if status == "completed":
            return f"""
                ✅ Successfully completed coding workflow for:
                {state.get('jira_ticket_key', 'ticket')}!

                Summary:
                - Jira ticket: ✓ Fetched
                - Confluence design: ✓ Fetched  
                - Development rules: ✓ Loaded
                - Code generation: ✓ Completed
                - Code reflection: ✓ Completed ({reflection_count} reflection cycles)
                - GitLab branch: ✓ Created ({state.get('branch_name', 'N/A')})
                - Code commit: ✓ Ready

                The generated code has been refined through
                {reflection_count} reflection cycles and is ready for review.
                """
        elif status == "reflection_completed":
            return f"""
                ✅ Code generation and reflection cycle completed for:
                {state.get('jira_ticket_key', 'ticket')}!

                Summary:
                - Code generation: ✓ Completed (4 iterations)
                - Code reflection: ✓ Completed (3 reflection cycles)
                - Ready for GitLab commit

                The code has been iteratively improved through the reflection process
                and is ready for commit.
                """
        elif (
            status == "awaiting_confluence_link"
            or state.get("user_input_required") == "confluence_link"
        ):
            return "⏸️ Workflow paused - waiting for Confluence design link."
        elif status == "user_input_required":
            return "⏸️ Workflow paused - user input required."
        elif status == "error":
            return f"❌ Workflow failed with error: {state.get('error_message', 'Unknown error')}"
        else:
            return f"🔄 Workflow in progress - Status: {status} (Reflection count: {reflection_count})"


# Example usage
if __name__ == "__main__":

    async def main():
        agent = CodingAgent(
            gitlab_project_id=settings.gitlab_project_id,
            development_rules_path=settings.development_rules_path,
            development_rules_branch=settings.development_rules_branch,
        )

        result = await agent.run(jira_ticket_key="CBP-8446")
        print("Final Response:")
        print(result["final_response"])
        print(f"\nWorkflow Status: {result['workflow_status']}")
        print(f"Success: {result['success']}")

    asyncio.run(main())
