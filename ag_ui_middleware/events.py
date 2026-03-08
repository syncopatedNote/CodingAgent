"""
AG-UI Middleware — Event Factory

Thin wrappers around ``ag_ui.core`` event classes that reduce
boilerplate and add forward-compatible interrupt fields.

Usage::

    from ag_ui_middleware.events import EventFactory as E

    yield encoder.encode(E.run_started("t1", "r1"))
    yield encoder.encode(E.text_content(msg_id, "hello "))
    yield encoder.encode(E.interrupted("t1", "r1", interrupt_data))
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from ag_ui.core import (
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from .types import InterruptData


class EventFactory:
    """
    Static helpers that construct AG-UI events.

    Each method returns a Pydantic model instance ready to
    be passed to ``EventEncoder.encode()``.
    """

    # ── Run lifecycle ──────────────────────────────────────

    @staticmethod
    def run_started(
        thread_id: str,
        run_id: str,
    ) -> RunStartedEvent:
        return RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=thread_id,
            run_id=run_id,
        )

    @staticmethod
    def run_finished(
        thread_id: str,
        run_id: str,
    ) -> RunFinishedEvent:
        """Normal (successful) run completion."""
        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=thread_id,
            run_id=run_id,
        )

    @staticmethod
    def run_error(message: str) -> RunErrorEvent:
        return RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=message,
        )

    # ── Interrupt-aware finish (draft spec) ────────────────

    @staticmethod
    def interrupted(
        thread_id: str,
        run_id: str,
        interrupt: InterruptData,
    ) -> RunFinishedEvent:
        """
        Emit a ``RUN_FINISHED`` with ``outcome="interrupt"``.

        Extra fields (``outcome``, ``interrupt``) are accepted
        by the SDK because the model uses ``extra='allow'``.
        When the official SDK adds native interrupt support,
        swap this to use the first-class fields.
        """
        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=thread_id,
            run_id=run_id,
            outcome="interrupt",
            interrupt={
                "id": interrupt.id,
                "reason": interrupt.reason,
                "payload": interrupt.payload,
            },
        )

    # ── Steps ──────────────────────────────────────────────

    @staticmethod
    def step_started(step_name: str) -> StepStartedEvent:
        return StepStartedEvent(
            type=EventType.STEP_STARTED,
            step_name=step_name,
        )

    @staticmethod
    def step_finished(step_name: str) -> StepFinishedEvent:
        return StepFinishedEvent(
            type=EventType.STEP_FINISHED,
            step_name=step_name,
        )

    # ── Text message streaming ─────────────────────────────

    @staticmethod
    def text_start(
        message_id: str,
        role: str = "assistant",
    ) -> TextMessageStartEvent:
        return TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START,
            message_id=message_id,
            role=role,
        )

    @staticmethod
    def text_content(
        message_id: str,
        delta: str,
    ) -> TextMessageContentEvent:
        return TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=delta,
        )

    @staticmethod
    def text_end(
        message_id: str,
    ) -> TextMessageEndEvent:
        return TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END,
            message_id=message_id,
        )

    # ── Custom events ──────────────────────────────────────

    @staticmethod
    def custom(
        name: str,
        value: Any,
    ) -> CustomEvent:
        return CustomEvent(
            type=EventType.CUSTOM,
            name=name,
            value=value,
        )

    # ── Helpers ────────────────────────────────────────────

    @staticmethod
    def new_message_id() -> str:
        """Generate a unique message id for text streaming."""
        return str(uuid.uuid4())
