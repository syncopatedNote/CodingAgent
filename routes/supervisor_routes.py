"""
Supervisor Agent Routes
Endpoints for interacting with the supervisor agent.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from ag_ui.core import RunAgentInput
from ag_ui_middleware import (
    AgUIMiddleware,
    AgentResult,
    InterruptData,
    InterruptReason,
    RunContext,
)
from agents.supervisor_agent import SupervisorAgent, TaskType
from logger import setup_logger

logger = setup_logger(__name__)

# ==================== Global Agent Instance ====================

supervisor_agent: Optional[SupervisorAgent] = None
ag_ui = AgUIMiddleware()


def initialize_agent():
    """Initialize the supervisor agent on startup"""
    global supervisor_agent
    try:
        supervisor_agent = SupervisorAgent()
        logger.info("Supervisor agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize supervisor agent: {str(e)}")
        raise


def get_supervisor_agent() -> Optional[SupervisorAgent]:
    """Return the current supervisor agent instance (live reference)."""
    return supervisor_agent


# ==================== Pydantic Models ====================


class MessageDTO(BaseModel):
    """Data Transfer Object for messages"""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class SupervisorRequest(BaseModel):
    """Request model for supervisor agent queries"""

    user_input: str = Field(..., description="The user's question or request")
    conversation_history: Optional[List[MessageDTO]] = Field(
        default=None, description="Previous conversation messages for context"
    )
    session_id: Optional[str] = Field(
        default=None, description="Optional session ID for tracking conversations"
    )


class TaskAnalysis(BaseModel):
    """Task analysis information"""

    task_type: Optional[str] = Field(None, description="Detected task type")
    confidence: float = Field(..., description="Confidence score of classification")
    extracted_jira_tickets: List[str] = Field(
        default_factory=list, description="Jira tickets extracted from the input"
    )


class SupervisorResponse(BaseModel):
    """Response model from supervisor agent"""

    session_id: Optional[str] = Field(None, description="Session ID for tracking")
    task_analysis: TaskAnalysis = Field(..., description="Analysis of the task")
    response: str = Field(..., description="Final response from the supervisor")
    search_results: Optional[Dict[str, Any]] = Field(
        None, description="Results from search agent if applicable"
    )
    coding_results: Optional[Dict[str, Any]] = Field(
        None, description="Results from coding agent if applicable"
    )
    error: Optional[str] = Field(None, description="Error message if any")
    requires_user_input: bool = Field(
        False, description="Whether the workflow requires user input"
    )
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ==================== Utility Functions ====================


def convert_messages_to_langchain(messages: List[MessageDTO]) -> List[BaseMessage]:
    """Convert DTOs to LangChain message objects"""
    langchain_messages = []
    for msg in messages:
        if msg.role.lower() == "user":
            langchain_messages.append(HumanMessage(content=msg.content))
        elif msg.role.lower() == "assistant":
            langchain_messages.append(AIMessage(content=msg.content))
    return langchain_messages


def extract_response_data(
    state: Dict[str, Any], session_id: Optional[str] = None
) -> SupervisorResponse:
    """Extract structured response from supervisor agent state"""
    task_type = state.get("task_type")
    task_type_str = (
        task_type.value if isinstance(task_type, TaskType) else str(task_type)
    )

    final_response = state.get("final_response")
    if final_response is None:
        error_msg = state.get("error_message")
        if error_msg:
            final_response = f"I encountered an error: {error_msg}"
        else:
            final_response = (
                "I'm sorry, I couldn't generate a response. "
                "Please try rephrasing your question."
            )

    return SupervisorResponse(
        session_id=session_id,
        task_analysis=TaskAnalysis(
            task_type=task_type_str,
            confidence=state.get("confidence", 0.0),
            extracted_jira_tickets=state.get("extracted_jira_tickets", []),
        ),
        response=final_response,
        search_results=state.get("search_agent_result"),
        coding_results=state.get("coding_agent_result"),
        error=state.get("error_message"),
        requires_user_input=state.get("requires_user_input", False),
    )


# ==================== Router ====================

router = APIRouter(prefix="/api/supervisor", tags=["Supervisor"])


@router.post("/chat", response_model=SupervisorResponse)
async def supervisor_chat(request: SupervisorRequest) -> SupervisorResponse:
    """
    Send a query to the supervisor agent for intelligent routing and response.

    The supervisor agent will:
    1. Enhance the question with conversation context
    2. Classify the task type (search, code generation, or general chat)
    3. Route to the appropriate agent (search or coding)
    4. Return a structured response
    """
    if not supervisor_agent:
        raise HTTPException(
            status_code=503,
            detail="Supervisor agent not initialized. Please try again later.",
        )

    try:
        conversation_history = []
        if request.conversation_history:
            conversation_history = convert_messages_to_langchain(
                request.conversation_history
            )

        logger.info(f"Processing user input: {request.user_input[:100]}...")
        final_state = await supervisor_agent.run(
            user_input=request.user_input, conversation_history=conversation_history
        )

        logger.info(f"Final state keys: {final_state.keys()}")
        logger.info(f"final_response value: {final_state.get('final_response')}")
        logger.info(f"error_message value: {final_state.get('error_message')}")

        response = extract_response_data(final_state, session_id=request.session_id)
        response.session_id = request.session_id

        logger.info(
            "Successfully processed request. "
            f"Task type: {response.task_analysis.task_type}"
        )
        return response

    except Exception as e:
        logger.error(f"Error processing supervisor request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@router.post("/agent")
async def supervisor_agent_endpoint(input_data: RunAgentInput, request: Request):
    """
    AG-UI protocol endpoint for the supervisor agent.

    Delegates the entire event lifecycle (including
    interrupt-aware resume) to :class:`AgUIMiddleware`.
    """
    if not supervisor_agent:
        raise HTTPException(
            status_code=503,
            detail="Supervisor agent not initialized.",
        )

    async def _agent_fn(
        user_input: str,
        conversation_history: list[BaseMessage],
        context: RunContext,
    ) -> AgentResult:
        if context.is_resume:
            saved = context.saved_state or {}
            coding_thread_id = saved.get("coding_thread_id")
            answer = (
                context.resume_data.payload.get("answer", "")
                if context.resume_data
                else ""
            )

            result = await supervisor_agent.coding_agent.run(
                user_input=user_input,
                thread_id=coding_thread_id,
                resume_value=answer,
            )

            if result.get("interrupt"):
                return AgentResult(
                    interrupt=InterruptData(
                        id=f"int-{result['thread_id'][:8]}",
                        reason=InterruptReason.INFO_REQUIRED,
                        payload=result["interrupt"],
                    ),
                    state_to_save={"coding_thread_id": result["thread_id"]},
                )

            return AgentResult(
                response=result.get("response", ""),
                metadata={"task_type": "code_generation"},
            )

        final_state = await supervisor_agent.run(
            user_input=user_input,
            conversation_history=conversation_history,
        )

        coding_result = final_state.get("coding_agent_result")
        if coding_result and coding_result.get("interrupt"):
            return AgentResult(
                interrupt=InterruptData(
                    id=f"int-{coding_result['thread_id'][:8]}",
                    reason=InterruptReason.INFO_REQUIRED,
                    payload=coding_result["interrupt"],
                ),
                state_to_save={"coding_thread_id": coding_result["thread_id"]},
            )

        response_data = extract_response_data(final_state)
        return AgentResult(
            response=response_data.response,
            metadata={
                "task_type": response_data.task_analysis.task_type,
                "confidence": response_data.task_analysis.confidence,
                "extracted_jira_tickets": (
                    response_data.task_analysis.extracted_jira_tickets
                ),
            },
        )

    return ag_ui.create_response(input_data, request, agent_fn=_agent_fn)
