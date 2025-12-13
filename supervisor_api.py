#!/usr/bin/env python3
"""
Supervisor Agent API Service
Exposes the supervisor agent as a REST API service for
external frontend integrations.
Built with FastAPI and Uvicorn.

Usage:
    uvicorn supervisor_api:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from agents.supervisor_agent import SupervisorAgent, TaskType
from logger import setup_logger

logger = setup_logger(__name__)

# ==================== Global Agent Instance ====================

supervisor_agent: Optional[SupervisorAgent] = None


def initialize_agent():
    """Initialize the supervisor agent on startup"""
    global supervisor_agent
    try:
        supervisor_agent = SupervisorAgent()
        logger.info("Supervisor agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize supervisor agent: {str(e)}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    initialize_agent()
    logger.info("Supervisor API service started")
    yield
    # Shutdown
    logger.info("Supervisor API service shutting down")

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
        default=None,
        description="Optional session ID for tracking conversations"
    )


class TaskAnalysis(BaseModel):
    """Task analysis information"""

    task_type: Optional[str] = Field(None, description="Detected task type")
    confidence: float = Field(
        ...,
        description="Confidence score of classification"
    )
    extracted_jira_tickets: List[str] = Field(
        default_factory=list,
        description="Jira tickets extracted from the input"
    )


class SupervisorResponse(BaseModel):
    """Response model from supervisor agent"""

    session_id: Optional[str] = Field(None,
                                      description="Session ID for tracking")
    task_analysis: TaskAnalysis = Field(...,
                                        description="Analysis of the task")
    response: str = Field(...,
                          description="Final response from the supervisor")
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


class HealthCheckResponse(BaseModel):
    """Health check response"""

    status: str = Field(..., description="Service status")
    message: str = Field(..., description="Status message")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ==================== FastAPI Setup ====================

app = FastAPI(
    title="Supervisor Agent API",
    description="REST API for the Supervisor Agent",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware to allow requests from other frontend projects
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        state: Dict[str, Any],
        session_id: Optional[str] = None
) -> SupervisorResponse:
    """Extract structured response from supervisor agent state"""
    task_type = state.get("task_type")
    task_type_str = (
        task_type.value if isinstance(task_type, TaskType) else str(task_type)
    )

    # Get final response or use error message as fallback
    final_response = state.get("final_response")
    if final_response is None:
        error_msg = state.get("error_message")
        if error_msg:
            final_response = f"I encountered an error: {error_msg}"
        else:
            final_response = "I'm sorry, I couldn't generate a response." \
                "Please try rephrasing your question."

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


# ==================== API Endpoints ====================


@app.get("/api/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify API is running

    Returns:
        HealthCheckResponse with status information
    """
    return HealthCheckResponse(
        status="healthy" if supervisor_agent else "initializing",
        message=(
            "Supervisor API is running"
            if supervisor_agent
            else "Agent is initializing"
        ),
    )


@app.post(
    "/api/supervisor/chat",
    response_model=SupervisorResponse, tags=["Supervisor"]
)
async def supervisor_chat(request: SupervisorRequest) -> SupervisorResponse:
    """
    Send a query to the supervisor agent for intelligent routing and response.

    The supervisor agent will:
    1. Enhance the question with conversation context
    2. Classify the task type (search, code generation, or general chat)
    3. Route to the appropriate agent (search or coding)
    4. Return a structured response

    Args:
        request: SupervisorRequest containing user input and optional
        conversation history

    Returns:
        SupervisorResponse with task analysis and final response

    Raises:
        HTTPException: If the supervisor agent is not initialized
        or encounters an error
    """
    if not supervisor_agent:
        raise HTTPException(
            status_code=503,
            detail="Supervisor agent not initialized. Please try again later.",
        )

    try:
        # Convert conversation history to LangChain format
        conversation_history = []
        if request.conversation_history:
            conversation_history = convert_messages_to_langchain(
                request.conversation_history
            )

        # Run the supervisor agent
        logger.info(f"Processing user input: {request.user_input[:100]}...")
        final_state = await supervisor_agent.run(
            user_input=request.user_input,
            conversation_history=conversation_history
        )

        # Debug logging
        logger.info(f"Final state keys: {final_state.keys()}")
        logger.info(f"final_response value: {final_state.get('final_response')}")
        logger.info(f"error_message value: {final_state.get('error_message')}")

        # Extract and structure the response
        response = extract_response_data(final_state,
                                         session_id=request.session_id)
        response.session_id = request.session_id

        logger.info(
            "Successfully processed request."
            f"Task type: {response.task_analysis.task_type}"
        )
        return response

    except Exception as e:
        logger.error(f"Error processing supervisor request: {str(e)}",
                     exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@app.post("/api/supervisor/chat-stream", tags=["Supervisor"])
async def supervisor_chat_stream(request: SupervisorRequest):
    """
    Send a query to the supervisor agent with streaming response.

    This endpoint streams the response as it's being generated,
    useful for real-time UI updates.

    Args:
        request: SupervisorRequest containing user input and
        optional conversation history

    Yields:
        JSON chunks with intermediate results and final response
    """
    if not supervisor_agent:
        raise HTTPException(
            status_code=503,
            detail="Supervisor agent not initialized. Please try again later.",
        )

    async def event_generator():
        try:
            # Convert conversation history
            conversation_history = []
            if request.conversation_history:
                conversation_history = convert_messages_to_langchain(
                    request.conversation_history
                )

            # Send processing started event
            yield f"data: {{'status': 'processing', 'message': 'Processing your request...'}}\n\n"

            # Run the supervisor agent
            final_state = await supervisor_agent.run(
                user_input=request.user_input,
                conversation_history=conversation_history
            )

            # Extract response
            response = extract_response_data(final_state,
                                             session_id=request.session_id)

            # Send final response
            yield f"data: {response.model_dump_json()}\n\n"

        except Exception as e:
            logger.error(f"Error in streaming response: {str(e)}", exc_info=True)
            yield f"data: {{'status': 'error', 'message': '{str(e)}'}}\n\n"

    return JSONResponse(
        content=None,
        status_code=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ==================== Error Handlers ====================


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler for HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Custom handler for general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


# ==================== Root Endpoint ====================


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information and links to documentation
    """
    return {
        "name": "Supervisor Agent API",
        "version": "1.0.0",
        "documentation": "/api/docs",
        "redoc": "/api/redoc",
        "endpoints": {
            "health": "/api/health",
            "supervisor_chat": "/api/supervisor/chat",
            "supervisor_chat_stream": "/api/supervisor/chat-stream"
        },
    }


# ==================== Entry Point ====================

if __name__ == "__main__":
    import uvicorn

    # Run the API server
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", reload=True)
