"""
AG-UI Middleware — Data Models

Defines the core types used across the middleware:

- InterruptData / ResumeData  – Interrupt-aware run lifecycle
- RunContext                  – Context bag passed to agent callables
- AgentResult                 – Return type from agent callables
- StepInfo                    – Named processing step metadata
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Interrupt lifecycle ────────────────────────────────────────────


class InterruptReason(str, Enum):
    """Well-known interrupt reasons (extensible via plain strings)."""

    HUMAN_APPROVAL = "human_approval"
    INFO_REQUIRED = "info_required"
    POLICY_HOLD = "policy_hold"
    ERROR_RECOVERY = "error_recovery"
    CONFIRMATION = "confirmation"


class InterruptData(BaseModel):
    """
    Payload attached to a RUN_FINISHED event with
    ``outcome="interrupt"``.

    Follows the AG-UI draft spec:
    https://docs.ag-ui.com/drafts/interrupts
    """

    id: str = Field(..., description="Unique interrupt identifier")
    reason: str = Field(
        ...,
        description=(
            "Why the interrupt was raised " "(e.g. 'human_approval', 'info_required')"
        ),
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON context for the UI",
    )


class ResumeData(BaseModel):
    """
    Data sent by the client to continue a previously
    interrupted run.

    Extracted from ``RunAgentInput.resume`` (extra field).
    """

    interrupt_id: str = Field(
        ...,
        alias="interruptId",
        description="Echo of InterruptData.id",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON response from the user",
    )

    model_config = {"populate_by_name": True}


# ── Interrupt persistence ─────────────────────────────────────────


class InterruptState(BaseModel):
    """
    Server-side record of an outstanding interrupt.
    Stored by :class:`InterruptManager` keyed on *thread_id*.
    """

    thread_id: str
    run_id: str
    interrupt: InterruptData
    agent_state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque agent state preserved for resume",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


# ── Agent callable contract ───────────────────────────────────────


class StepInfo(BaseModel):
    """Describes a named processing step emitted during a run."""

    name: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunContext(BaseModel):
    """
    Context bag provided to agent callables by the middleware.

    The agent function receives this so it can inspect run
    metadata and resume state without coupling to AG-UI types.
    """

    thread_id: str
    run_id: str
    is_resume: bool = False
    resume_data: Optional[ResumeData] = None
    saved_state: Optional[Dict[str, Any]] = None

    model_config = {"arbitrary_types_allowed": True}


class AgentResult(BaseModel):
    """
    Return type from an agent callable.

    The middleware inspects these fields to decide what AG-UI
    events to emit.

    * Normal completion → streams ``response`` as text.
    * Interrupt → emits `RUN_FINISHED` with ``outcome="interrupt"``
      and stores ``state_to_save`` for later resume.
    """

    response: str = Field(
        default="",
        description="Text response to stream to the client",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary metadata emitted as a CUSTOM event " "(e.g. task_analysis)"
        ),
    )
    steps: List[StepInfo] = Field(
        default_factory=list,
        description="Named steps that were executed",
    )
    interrupt: Optional[InterruptData] = Field(
        default=None,
        description=(
            "If set, the run finishes with an interrupt " "instead of streaming text"
        ),
    )
    state_to_save: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Opaque state preserved by InterruptManager " "for a future resume"
        ),
    )
