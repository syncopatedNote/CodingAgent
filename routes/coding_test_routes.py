"""
Direct Coding Pipeline Test Endpoint

Bypasses the supervisor classifier and calls CodingPipeline directly with
supplied requirements. Useful for testing both coding agent modes
(supervisor / deterministic) without relying on the supervisor to route
the request correctly.

POST /api/coding/test
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agents.coding_pipeline.coding_pipeline import CodingPipeline
from agents.coding_pipeline.collector_agent.context_bundle import ContextBundle
from logger import setup_logger
from settings import settings

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/coding", tags=["Coding (test)"])


class CodingTestRequest(BaseModel):
    requirements: str = Field(
        ...,
        description="What needs to be implemented.",
    )
    repo_owner: Optional[str] = Field(
        default=None,
        description=(
            "GitHub org / owner. Falls back to CODING_REPOSITORY_OWNER env var."
        ),
    )
    repo_name: str = Field(
        ...,
        description="Repository name (e.g. 'my-service').",
    )
    base_branch: Optional[str] = Field(
        default=None,
        description="Branch to base work on. Falls back to CODING_BASE_BRANCH.",
    )
    repo_source: Optional[str] = Field(
        default="github",
        description="'github' or 'gitlab'.",
    )
    design_details: Optional[str] = Field(
        default="",
        description="Optional design / Confluence context.",
    )
    mode: Optional[str] = Field(
        default="autonomous",
        description="'autonomous' or 'interactive'.",
    )


class CodingTestResponse(BaseModel):
    agent_mode: str
    response: Optional[str]
    thread_id: str


@router.post("/test", response_model=CodingTestResponse)
async def coding_test(request: CodingTestRequest):
    """
    Invoke the coding pipeline directly with the supplied requirements.

    Skips context collection entirely — builds a ContextBundle from the
    request body and hands it straight to whichever coding agent is selected
    by the CODING_AGENT_MODE setting (supervisor or deterministic).
    """
    owner = request.repo_owner or settings.coding_repository_owner or ""
    base = request.base_branch or settings.coding_base_branch

    bundle = ContextBundle(
        requirements=request.requirements,
        repo_source=request.repo_source or "github",
        confluence_design_details=request.design_details or "",
        development_guidelines="",  # no guidelines file fetched in test mode
        repository_reference=request.repo_name,
        repository_owner=owner,
        base_branch=base,
        git_issue_details="",
        status="complete",
    )

    agent_mode = settings.coding_agent_mode

    # Build a fresh pipeline for this request so we don't share MCP tool
    # caches or MemorySaver state with other in-flight requests.
    pipeline = CodingPipeline()

    logger.info(
        f"[coding/test] agent_mode={agent_mode} repo={owner}/{request.repo_name} "
        f"base={base} mode={request.mode}"
    )

    # Call the coding agent directly, bypassing the collector.
    result = await pipeline.coding_agent.run(
        bundle=bundle,
        mode=request.mode or "autonomous",
    )

    return CodingTestResponse(
        agent_mode=agent_mode,
        response=result.get("response"),
        thread_id=result.get("thread_id", ""),
    )
