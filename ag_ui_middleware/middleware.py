"""
AG-UI Middleware — Core Middleware

Orchestrates the full AG-UI run lifecycle:

1. ``RUN_STARTED``
2. ``STEP_STARTED`` / ``STEP_FINISHED``  (per agent step)
3. ``CUSTOM``        (metadata events)
4. ``TEXT_MESSAGE_*`` (response streaming)
5. ``RUN_FINISHED``  — with ``outcome="success"`` or
   ``outcome="interrupt"``

Interrupt-aware resume flow
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``RunAgentInput`` contains a ``resume`` extra field the
middleware resolves the stored interrupt, and passes
:class:`RunContext` to the agent callable with
``is_resume=True``, the user's ``resume_data``, and the
previously saved ``agent_state``.

Usage in ``supervisor_api.py``::

    middleware = AgUIMiddleware()

    @app.post("/api/supervisor/agent")
    async def agent_endpoint(
        input_data: RunAgentInput, request: Request
    ):
        return middleware.create_response(
            input_data, request, agent_fn=my_agent
        )

Agent callable contract::

    async def my_agent(
        user_input: str,
        conversation_history: list[BaseMessage],
        context: RunContext,
    ) -> AgentResult:
        ...
"""

from __future__ import annotations

import asyncio
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    List,
    Optional,
    Protocol,
)

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from logger import setup_logger

from .events import EventFactory as E
from .interrupt import InterruptManager
from .types import AgentResult, ResumeData, RunContext

logger = setup_logger(__name__)


# ── Agent callable type ────────────────────────────────────────────

AgentCallable = Callable[
    [str, List[BaseMessage], RunContext],
    Awaitable[AgentResult],
]


# ── Middleware ─────────────────────────────────────────────────────


class AgUIMiddleware:
    """
    Encapsulates the AG-UI protocol so that API endpoints
    remain thin wrappers.

    Parameters
    ----------
    interrupt_manager : InterruptManager, optional
        Shared interrupt store.  A default in-memory instance
        is created if omitted.
    chunk_size : int
        Number of words per ``TEXT_MESSAGE_CONTENT`` event.
    chunk_delay : float
        Seconds to sleep between text chunks (for smooth UX).
    metadata_event_name : str
        ``CUSTOM`` event name used for agent metadata
        (default ``"task_analysis"``).
    """

    def __init__(
        self,
        *,
        interrupt_manager: Optional[InterruptManager] = None,
        chunk_size: int = 3,
        chunk_delay: float = 0.03,
        metadata_event_name: str = "task_analysis",
    ) -> None:
        self.interrupt_manager = interrupt_manager or InterruptManager()
        self.chunk_size = chunk_size
        self.chunk_delay = chunk_delay
        self.metadata_event_name = metadata_event_name

    # ── Public API ─────────────────────────────────────────

    def create_response(
        self,
        input_data: RunAgentInput,
        request: Request,
        *,
        agent_fn: AgentCallable,
    ) -> StreamingResponse:
        """
        Build a :class:`StreamingResponse` that emits the
        full AG-UI event stream for a single run.
        """
        accept = request.headers.get("accept")
        encoder = EventEncoder(accept=accept)

        return StreamingResponse(
            self._run(input_data, agent_fn, encoder),
            media_type=encoder.get_content_type(),
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Core run lifecycle ─────────────────────────────────

    async def _run(
        self,
        input_data: RunAgentInput,
        agent_fn: AgentCallable,
        encoder: EventEncoder,
    ) -> AsyncGenerator[str, None]:
        thread_id = input_data.thread_id
        run_id = input_data.run_id

        try:
            # ── 1. RUN_STARTED ─────────────────────────────
            yield encoder.encode(E.run_started(thread_id, run_id))

            # ── 2. Build RunContext (check for resume) ─────
            context = self._build_context(input_data)

            # ── 3. Extract messages ────────────────────────
            user_input, history = self._extract_messages(input_data)

            # ── 4. Step: processing ────────────────────────
            yield encoder.encode(E.step_started("processing"))

            result: AgentResult = await agent_fn(user_input, history, context)

            yield encoder.encode(E.step_finished("processing"))

            # ── 5. Extra steps reported by agent ───────────
            for step in result.steps:
                yield encoder.encode(E.step_started(step.name))
                yield encoder.encode(E.step_finished(step.name))

            # ── 6. Metadata custom event ───────────────────
            if result.metadata:
                yield encoder.encode(
                    E.custom(
                        self.metadata_event_name,
                        result.metadata,
                    )
                )

            # ── 7. Decide: interrupt vs text response ──────
            if result.interrupt:
                # Save state for future resume
                self.interrupt_manager.create(
                    thread_id=thread_id,
                    run_id=run_id,
                    interrupt=result.interrupt,
                    agent_state=result.state_to_save,
                )
                yield encoder.encode(E.interrupted(thread_id, run_id, result.interrupt))
            else:
                # Stream text response
                async for chunk in self._stream_text(result.response, encoder):
                    yield chunk

                # Normal finish
                yield encoder.encode(E.run_finished(thread_id, run_id))

        except Exception as exc:
            logger.error(
                f"AG-UI run error: {exc}",
                exc_info=True,
            )
            yield encoder.encode(E.run_error(str(exc)))

    # ── Text streaming ─────────────────────────────────────

    async def _stream_text(
        self,
        text: str,
        encoder: EventEncoder,
    ) -> AsyncGenerator[str, None]:
        """Emit TEXT_MESSAGE_START → …CONTENT → …END."""
        message_id = E.new_message_id()

        yield encoder.encode(E.text_start(message_id, "assistant"))

        if text:
            words = text.split(" ")
            for i in range(0, len(words), self.chunk_size):
                batch = words[i : i + self.chunk_size]
                prefix = "" if i == 0 else " "
                delta = prefix + " ".join(batch)
                yield encoder.encode(E.text_content(message_id, delta))
                await asyncio.sleep(self.chunk_delay)

        yield encoder.encode(E.text_end(message_id))

    # ── Message extraction ─────────────────────────────────

    @staticmethod
    def _extract_messages(
        input_data: RunAgentInput,
    ) -> tuple[str, list[BaseMessage]]:
        """
        Pull *user_input* (last message) and
        *conversation_history* from the AG-UI message array.
        """
        msgs = input_data.messages or []
        user_input = ""
        history: list[BaseMessage] = []

        if msgs:
            for msg in msgs[:-1]:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", "") or ""
                if role == "user":
                    history.append(HumanMessage(content=content))
                elif role == "assistant":
                    history.append(AIMessage(content=content))
            user_input = getattr(msgs[-1], "content", "") or ""

        return user_input, history

    # ── Resume / interrupt context ─────────────────────────

    def _build_context(self, input_data: RunAgentInput) -> RunContext:
        """
        Inspect ``input_data`` for resume data.

        Looks in two places (in order of priority):

        1. ``input_data.resume`` — top-level extra field
           (future native AG-UI support).
        2. ``input_data.forwarded_props["resume"]`` — the
           current recommended way using the standard
           ``forwardedProps`` extension point.

        If found **and** a matching pending interrupt exists
        for this thread, build a resume-aware
        :class:`RunContext`.  Otherwise return a fresh context.
        """
        thread_id = input_data.thread_id
        run_id = input_data.run_id

        # Check both locations for resume data
        resume_raw = getattr(input_data, "resume", None)
        if not resume_raw:
            fwd = input_data.forwarded_props
            if isinstance(fwd, dict):
                resume_raw = fwd.get("resume")

        if resume_raw and isinstance(resume_raw, dict):
            resume = ResumeData(**resume_raw)
            interrupt_state = self.interrupt_manager.resolve(
                thread_id, resume.interrupt_id
            )
            if interrupt_state:
                logger.info(
                    f"Resuming from interrupt "
                    f"{resume.interrupt_id} on "
                    f"thread {thread_id}"
                )
                return RunContext(
                    thread_id=thread_id,
                    run_id=run_id,
                    is_resume=True,
                    resume_data=resume,
                    saved_state=interrupt_state.agent_state,
                )
            else:
                logger.warning(
                    f"Resume requested but no matching "
                    f"interrupt found (thread={thread_id}, "
                    f"id={resume.interrupt_id})"
                )

        return RunContext(
            thread_id=thread_id,
            run_id=run_id,
        )
