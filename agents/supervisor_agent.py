#!/usr/bin/env python3
"""
Supervisor Agent
Has only two main responsibilities:
1. Route to coding agent for code generation tasks
2. Route to search agent for all search operations
3. Support general chit chat
"""

import re
from typing import Dict, List, Optional, TypedDict, Annotated
from enum import Enum

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from framework_base.llm_base import LLMFactory
from settings import settings
from logger import setup_logger

# Import agents
from .search_agent import SearchAgent
from .coding_agent.langgraph_coding_agent import LangGraphCodingAgent
from .question_enhancer_agent import enhance_question
from .general_chat_agent import GeneralChatAgent
from agents.prompts.main_supervisor.classify_task import (
    SUPERVISOR_CLASSIFY_PROMPT,
)

logger = setup_logger(__name__)


class TaskType(Enum):
    """Types of tasks the supervisor can handle"""

    CODE_GENERATION = "code_generation"
    SEARCH_OPERATION = "search_operation"
    GENERAL_CHAT = "general_chat"


class SupervisorState(TypedDict):
    """Simplified state for the supervisor agent"""

    messages: Annotated[List[BaseMessage], "Conversation messages"]
    user_input: str
    enhanced_question: Optional[str]
    task_type: Optional[TaskType]
    confidence: float
    extracted_jira_tickets: List[str]
    search_agent_result: Optional[Dict]
    coding_agent_result: Optional[Dict]
    final_response: Optional[str]
    error_message: Optional[str]
    requires_user_input: bool
    pending_action: Optional[str]


class SupervisorAgent:
    def __init__(self):
        """Initialize the supervisor agent"""
        # Prepare kwargs for LLM creation
        llm_kwargs = {"temperature": 0.3}

        # Add base_url for ollama if provider is ollama
        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        # Initialize sub-agents
        self.search_agent = SearchAgent()
        self.general_chat_agent = GeneralChatAgent()

        # Initialize coding agent (uses MCP tools for repo access)
        self.coding_agent = LangGraphCodingAgent()

        # Build the workflow graph
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the supervisor workflow graph"""
        workflow = StateGraph(SupervisorState)

        # Add nodes
        workflow.add_node("enhance_question", self._enhance_question)
        workflow.add_node("classify_task", self._classify_task)
        workflow.add_node("invoke_search_agent", self._invoke_search_agent)
        workflow.add_node("invoke_coding_agent", self._invoke_coding_agent)
        workflow.add_node("handle_general_chat", self._handle_general_chat)
        workflow.add_node("request_user_input", self._request_user_input)
        workflow.add_node("finalize_response", self._finalize_response)
        workflow.add_node("handle_error", self._handle_error)

        # Set entry point
        workflow.set_entry_point("enhance_question")

        # Route from question enhancement to classification
        workflow.add_edge("enhance_question", "classify_task")

        # Add conditional routing from task classification
        workflow.add_conditional_edges(
            "classify_task",
            self._route_after_classification,
            {
                "search": "invoke_search_agent",
                "coding": "invoke_coding_agent",
                "general_chat": "handle_general_chat",
                "error": "handle_error",
            },
        )

        # Routes from agents
        workflow.add_conditional_edges(
            "invoke_search_agent",
            self._route_after_search,
            {"finalize": "finalize_response", "error": "handle_error"},
        )

        workflow.add_conditional_edges(
            "invoke_coding_agent",
            self._route_after_coding,
            {
                "finalize": "finalize_response",
                "request_input": "request_user_input",
                "error": "handle_error",
            },
        )

        # Simple routes to end
        workflow.add_edge("handle_general_chat", "finalize_response")
        workflow.add_edge("finalize_response", END)
        workflow.add_edge(
            "request_user_input", END
        )  # TODO change this. Should not end here.
        workflow.add_edge("handle_error", END)

        return workflow.compile()

    def _enhance_question(self, state: SupervisorState) -> SupervisorState:
        """Enhance the user's question with context before processing"""
        try:
            # Use the question enhancer to improve the question with context
            enhanced_question = enhance_question(state["messages"])
            state["enhanced_question"] = enhanced_question

            # Update user_input to use enhanced question for downstream processing
            state["user_input"] = enhanced_question

        except Exception as e:
            # If enhancement fails, continue with original question
            state["enhanced_question"] = state["user_input"]
            state["error_message"] = (
                f"Question enhancement failed, using original: {str(e)}"
            )

        return state

    async def _classify_task(self, state: SupervisorState) -> SupervisorState:
        """Classify the user's task into one of two main categories"""
        try:
            user_input = state["user_input"]

            # Extract Jira ticket references
            jira_tickets = self._extract_jira_tickets(user_input)
            state["extracted_jira_tickets"] = jira_tickets

            # Simple classification based on keywords and patterns
            task_type, confidence = await self._classify_task_simple(
                user_input, jira_tickets
            )

            state["task_type"] = task_type
            state["confidence"] = confidence

        except Exception as e:
            state["error_message"] = f"Error in task classification: {str(e)}"

        return state

    def _extract_jira_tickets(self, text: str) -> List[str]:
        """Extract Jira ticket references from text"""
        jira_pattern = r"\b[A-Z]+-\d+\b"
        return re.findall(jira_pattern, text)

    async def _classify_task_simple(
        self, user_input: str, jira_tickets: List[str]
    ) -> tuple:
        """Use LLM to intelligently classify the user's intent"""

        jira_context = ""
        if jira_tickets:
            jira_context = f"\n\nDetected Jira tickets: {', '.join(jira_tickets)}"

        classification_prompt = SUPERVISOR_CLASSIFY_PROMPT.format(
            user_input=user_input,
            jira_context=jira_context,
        )

        try:
            response = await self.llm.ainvoke(
                [HumanMessage(content=classification_prompt)]
            )
            result = response.content.strip()

            # Parse the LLM response
            task_type = TaskType.GENERAL_CHAT  # default
            confidence = 0.5  # default

            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("CATEGORY:"):
                    category = line.split(":", 1)[1].strip()
                    if "CODE_GENERATION" in category:
                        task_type = TaskType.CODE_GENERATION
                    elif "SEARCH_OPERATION" in category:
                        task_type = TaskType.SEARCH_OPERATION
                    elif "GENERAL_CHAT" in category:
                        task_type = TaskType.GENERAL_CHAT
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.split(":", 1)[1].strip())
                    except ValueError:
                        confidence = 0.7  # fallback

            return task_type, confidence

        except Exception as e:
            # Fallback to general chat if LLM classification fails
            logger.exception(
                f"LLM classification failed: {e}, falling back to GENERAL_CHAT"
            )
            return TaskType.GENERAL_CHAT, 0.5

    async def _invoke_search_agent(self, state: SupervisorState) -> SupervisorState:
        """Invoke the search agent to handle search operations"""
        try:
            # Call the search agent with enhanced question (now async)
            search_result = await self.search_agent.search(
                query=state["enhanced_question"] or state["user_input"],
            )

            state["search_agent_result"] = search_result

            # Set the final response from search results
            if search_result.get("final_response"):
                state["final_response"] = search_result["final_response"]
            elif search_result.get("error_message"):
                state["error_message"] = search_result["error_message"]
            else:
                state["final_response"] = (
                    "Search completed but no results were formatted."
                )

        except Exception as e:
            state["error_message"] = f"Error invoking search agent: {str(e)}"

        return state

    async def _invoke_coding_agent(self, state: SupervisorState) -> SupervisorState:
        """Invoke the LangGraph coding agent for code generation.

        The coding agent handles its own information gathering via
        ``ask_user`` interrupts, so we simply forward the user's
        request and propagate the result.
        """
        try:
            result = await self.coding_agent.run(
                user_input=state["enhanced_question"] or state["user_input"],
            )
            state["coding_agent_result"] = result

            if result.get("interrupt"):
                # Coding agent paused to ask the user a question
                state["requires_user_input"] = True
                state["pending_action"] = "coding_agent_interrupt"
                state["final_response"] = result["interrupt"].get(
                    "question", "The coding agent needs your input."
                )
            elif result.get("response"):
                state["final_response"] = result["response"]
            else:
                state["error_message"] = "Coding agent returned no response."

        except Exception as e:
            state["error_message"] = f"Error invoking coding agent: {str(e)}"

        return state

    async def _handle_general_chat(self, state: SupervisorState) -> SupervisorState:
        """Delegate general chat to GeneralChatAgent."""
        try:
            user_query = state["enhanced_question"] or state["user_input"]
            state["final_response"] = await self.general_chat_agent.chat(user_query)
        except Exception as e:
            state["error_message"] = f"Error in general chat: {str(e)}"
        return state

    def _request_user_input(self, state: SupervisorState) -> SupervisorState:
        """Handle cases where additional user input is required"""
        # The response is already set in the calling function
        return state

    def _finalize_response(self, state: SupervisorState) -> SupervisorState:
        """Finalize the response and add to messages"""
        if state.get("final_response"):
            state["messages"].append(AIMessage(content=state["final_response"]))
        return state

    def _handle_error(self, state: SupervisorState) -> SupervisorState:
        """Handle errors in the workflow"""
        error_msg = state.get("error_message", "An unknown error occurred")
        state["final_response"] = f"❌ Error: {error_msg}"
        state["messages"].append(AIMessage(content=state["final_response"]))
        return state

    def _format_coding_result(self, result: Dict) -> str:
        """Format coding agent result for display"""
        messages = result.get("messages", [])
        generated_code = result.get("generated_code", "")
        branch_name = result.get("branch_name", "")

        formatted = "## 🚀 Code Generation Results\n\n"

        # Add status messages with proper formatting
        if messages:
            formatted += "### 📋 Process Status:\n\n"
            for msg in messages:
                if hasattr(msg, "content"):
                    # Clean up the message content and add proper bullet points
                    content = msg.content.strip()
                    if content:
                        formatted += f"- ✅ {content}\n"
            formatted += "\n"

        # Add branch information
        if branch_name:
            formatted += f"### 🌿 Branch Information:\n\n"
            formatted += f"**Branch Created:** `{branch_name}`\n\n"

        # Add code preview
        if generated_code:
            formatted += "### 💻 Generated Code:\n\n"
            # Show a preview of the generated code
            code_preview = (
                generated_code[:800] if len(generated_code) > 800 else generated_code
            )
            formatted += f"```python\n{code_preview}"
            if len(generated_code) > 800:
                formatted += "\n\n# ... (code truncated for display)"
            formatted += "\n```\n\n"

        # Add summary
        formatted += "### ✨ Summary:\n\n"
        formatted += "Code generation workflow completed successfully. "
        if branch_name:
            formatted += (
                f"The generated code has been committed to the `{branch_name}` branch."
            )
        else:
            formatted += "The code is ready for deployment."

        return formatted

    # Routing functions
    def _route_after_classification(self, state: SupervisorState) -> str:
        """Route after task classification"""
        if state.get("error_message"):
            return "error"

        task_type = state.get("task_type")
        if task_type == TaskType.SEARCH_OPERATION:
            return "search"
        elif task_type == TaskType.CODE_GENERATION:
            return "coding"
        elif task_type == TaskType.GENERAL_CHAT:
            return "general_chat"
        else:
            return "general_chat"  # Default fallback

    def _route_after_search(self, state: SupervisorState) -> str:
        """Route after search agent invocation"""
        if state.get("error_message"):
            return "error"
        else:
            return "finalize"

    def _route_after_coding(self, state: SupervisorState) -> str:
        """Route after coding agent invocation"""
        if state.get("error_message"):
            return "error"
        elif state.get("requires_user_input"):
            return "request_input"
        else:
            return "finalize"

    async def run(
        self, user_input: str, conversation_history: List[BaseMessage] = None
    ) -> Dict:
        """
        Run the simplified supervisor agent workflow

        Args:
            user_input: The user's input/question
            conversation_history: Previous conversation messages

        Returns:
            Final state with response
        """
        # Ensure we have messages for the question enhancer
        messages = conversation_history or []
        messages.append(HumanMessage(content=user_input))

        initial_state = SupervisorState(
            messages=messages,
            user_input=user_input,
            enhanced_question=None,
            task_type=None,
            confidence=0.0,
            extracted_jira_tickets=[],
            search_agent_result=None,
            coding_agent_result=None,
            final_response=None,
            error_message=None,
            requires_user_input=False,
            pending_action=None,
        )

        final_state = await self.graph.ainvoke(initial_state)
        return final_state


# Example usage and testing
if __name__ == "__main__":
    import asyncio

    async def main():
        supervisor = SupervisorAgent()

        # Test different types of queries
        test_queries = [
            # "Search for API documentation",           # Search operation
            # "Find ticket PROJ-123",                  # Search operation
            "Generate code for CBP-8446"  # Code generation
            # "Implement the feature in STORY-789",    # Code generation
            # "What can you help me with?",            # General chat
            # "Look for confluence pages about deployment"  # Search operation
        ]

        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")

            result = await supervisor.run(query)
            print(f"Task Type: {result.get('task_type')}")
            print(f"Confidence: {result.get('confidence')}")
            print(f"Jira Tickets: {result.get('extracted_jira_tickets')}")
            print(f"Response:\n{result.get('final_response')}")

            if result.get("requires_user_input"):
                print(f"Requires input: {result.get('pending_action')}")

            if result.get("error_message"):
                print(f"Error: {result.get('error_message')}")

    asyncio.run(main())
