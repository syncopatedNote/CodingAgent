"""
AG-UI Middleware
================

A clean protocol layer between the FastAPI backend and the
AG-UI client SDK.  Encapsulates event encoding, text
streaming, and the interrupt-aware run lifecycle.

Quick start
-----------

.. code-block:: python

    from ag_ui_middleware import AgUIMiddleware, AgentResult

    middleware = AgUIMiddleware()

    async def my_agent(user_input, history, context):
        answer = await do_work(user_input)
        return AgentResult(
            response=answer,
            metadata={"task_type": "general"},
        )

    @app.post("/api/agent")
    async def agent_endpoint(
        input_data: RunAgentInput, request: Request
    ):
        return middleware.create_response(
            input_data, request, agent_fn=my_agent
        )

Interrupt example
-----------------

.. code-block:: python

    from ag_ui_middleware import (
        AgentResult,
        InterruptData,
        InterruptReason,
    )

    async def my_agent(user_input, history, context):
        if context.is_resume:
            approved = context.resume_data.payload.get(
                "approved"
            )
            if approved:
                result = execute_action(
                    context.saved_state
                )
                return AgentResult(response=result)

        if needs_approval(user_input):
            return AgentResult(
                interrupt=InterruptData(
                    id="int-" + uuid4().hex[:8],
                    reason=InterruptReason.HUMAN_APPROVAL,
                    payload={"action": "delete rows"},
                ),
                state_to_save={"query": user_input},
            )

        return AgentResult(response="done")
"""

from .events import EventFactory
from .interrupt import InterruptManager
from .middleware import AgUIMiddleware
from .types import (
    AgentResult,
    InterruptData,
    InterruptReason,
    InterruptState,
    ResumeData,
    RunContext,
    StepInfo,
)

__all__ = [
    # Core
    "AgUIMiddleware",
    "EventFactory",
    "InterruptManager",
    # Types
    "AgentResult",
    "InterruptData",
    "InterruptReason",
    "InterruptState",
    "ResumeData",
    "RunContext",
    "StepInfo",
]
