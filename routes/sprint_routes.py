"""
Sprint Routes

Webhook receiver for Jira sprint events.  On a ``sprint_started``
event the sprint start agent fetches all tickets and drives the
coding agent autonomously for each one as a background task.
"""

import hashlib
import hmac
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agents.sprint_start_agent import SprintStartAgent
from logger import setup_logger
from settings import settings

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/sprint", tags=["Sprint"])

_sprint_start_agent = SprintStartAgent()


# ── Request models ─────────────────────────────────────────────────


class JiraSprintDetail(BaseModel):
    id: Optional[Any] = Field(None, description="Numeric sprint ID from Jira")
    name: Optional[str] = Field(None, description="Human-readable sprint name")

    model_config = {"extra": "allow"}


class JiraWebhookPayload(BaseModel):
    webhookEvent: str = Field("", description="Jira event type, e.g. 'sprint_started'")
    sprint: Optional[JiraSprintDetail] = Field(
        None, description="Sprint details (present on sprint events)"
    )

    model_config = {"extra": "allow"}


# ── Helpers ────────────────────────────────────────────────────────


async def _validate_webhook_signature(request: Request, secret: str) -> None:
    """Verify the Jira HMAC-SHA256 webhook signature."""
    signature_header = request.headers.get("X-Hub-Signature", "")
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature header")

    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature_header, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


async def _run_sprint_background(sprint_id: str, sprint_name: str) -> None:
    """Background task: invoke sprint start agent and log results."""
    try:
        result = await _sprint_start_agent.run(
            sprint_id=sprint_id, sprint_name=sprint_name
        )
        logger.info(
            f"Sprint '{sprint_name}' ({sprint_id}) finished — "
            f"completed={len(result.completed)}, "
            f"failed={len(result.failed)}, "
            f"skipped={len(result.skipped)}"
        )
        for t in result.completed:
            logger.info(f"  DONE  {t.ticket_id} → branch: {t.branch_name}")
        for t in result.failed:
            logger.warning(f"  FAIL  {t.ticket_id} — {t.failure_reason}")
        for t in result.skipped:
            logger.warning(f"  SKIP  {t.ticket_id} — {t.failure_reason}")
    except Exception as exc:
        logger.error(
            f"Sprint start agent error for sprint "
            f"'{sprint_name}' ({sprint_id}): {exc}",
            exc_info=True,
        )


# ── Endpoint ───────────────────────────────────────────────────────


@router.post("/webhook/jira", status_code=202)
async def jira_sprint_webhook(
    payload: JiraWebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Receive Jira sprint webhook events.

    Processes ``sprint_started`` events by fetching all open tickets
    for the sprint and running the coding agent autonomously for each
    one.  Other event types are acknowledged and ignored.

    Configure Jira to POST to this endpoint with event type
    ``sprint_started``.  Set ``JIRA_WEBHOOK_SECRET`` to enable
    HMAC-SHA256 signature validation (strongly recommended in
    production).
    """
    if settings.jira_webhook_secret:
        await _validate_webhook_signature(request, settings.jira_webhook_secret)
    else:
        logger.warning(
            "JIRA_WEBHOOK_SECRET is not set — webhook signature "
            "validation is disabled.  Set it in production."
        )

    if payload.webhookEvent != "sprint_started":
        return {
            "accepted": True,
            "action": "ignored",
            "event": payload.webhookEvent,
        }

    sprint_id: Optional[str] = (
        str(payload.sprint.id).strip() if payload.sprint and payload.sprint.id else ""
    )
    sprint_name: str = (
        payload.sprint.name or sprint_id or "unknown"
        if payload.sprint
        else sprint_id or "unknown"
    )

    if not sprint_id:
        raise HTTPException(
            status_code=400,
            detail="Sprint ID missing from webhook payload",
        )

    logger.info(
        f"Jira sprint started: '{sprint_name}' (id={sprint_id}) "
        f"— queuing autonomous processing"
    )
    background_tasks.add_task(_run_sprint_background, sprint_id, sprint_name)

    return {
        "accepted": True,
        "action": "processing",
        "sprint_id": sprint_id,
        "sprint_name": sprint_name,
    }
