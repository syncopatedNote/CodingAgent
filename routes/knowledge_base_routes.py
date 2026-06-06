"""
Knowledge Base Search Routes
AG-UI protocol endpoint for the knowledge base search agent.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from ag_ui.core import RunAgentInput
from ag_ui_middleware import AgUIMiddleware, AgentResult, RunContext
from agents.kb_search_agent import KnowledgeBaseSearchAgent
from logger import setup_logger

logger = setup_logger(__name__)

# ==================== Global Agent Instance ====================

kb_search_agent: Optional[KnowledgeBaseSearchAgent] = None
ag_ui = AgUIMiddleware()


def initialize_kb_search_agent():
    """Initialize the knowledge base search agent on startup."""
    global kb_search_agent
    try:
        kb_search_agent = KnowledgeBaseSearchAgent()
        logger.info("Knowledge base search agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize knowledge base search agent: {str(e)}")
        raise


def get_kb_search_agent() -> Optional[KnowledgeBaseSearchAgent]:
    """Return the current knowledge base search agent instance."""
    return kb_search_agent


# ==================== Router ====================

router = APIRouter(prefix="/api/knowledge-base", tags=["Knowledge Base Search"])


@router.post("/agent")
async def kb_search_agent_endpoint(input_data: RunAgentInput, request: Request):
    """
    AG-UI protocol endpoint for the knowledge base search agent.

    Retrieves relevant documents from the vector store and returns
    a grounded LLM response. No interrupts — always single-turn.
    """
    if not kb_search_agent:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base search agent not initialized.",
        )

    async def _agent_fn(
        user_input: str,
        conversation_history: list,
        context: RunContext,
    ) -> AgentResult:
        response = await kb_search_agent.search(user_input)
        return AgentResult(
            response=response,
            metadata={"mode": "knowledge_base_search"},
        )

    return ag_ui.create_response(input_data, request, agent_fn=_agent_fn)
