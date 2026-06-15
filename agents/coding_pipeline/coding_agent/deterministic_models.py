"""
Structured-output models for the deterministic coding agent.

The deterministic agent drives the LLM through fixed steps and parses each
step's output into a typed model rather than scraping free text:

* :class:`NominatedFiles` — explore step: which existing files are likely
  impacted and worth reading before planning.
* :class:`WorkPlan` / :class:`PlannedFile` — plan step: the ordered, file-by-file
  change list the per-file loop walks.
* :class:`CodeReview` — review step: the approval decision plus blocking /
  non-blocking issues. Routing keys on ``approved`` only; ``confidence`` is
  recorded for reporting.
"""

from pydantic import BaseModel, Field


class NominatedFiles(BaseModel):
    """Existing repository paths the explore step thinks the change will touch."""

    paths: list[str] = Field(
        default_factory=list,
        description=(
            "Repository-root-relative paths of EXISTING files likely impacted "
            "by the change, worth reading before planning. Omit new files."
        ),
    )


class PlannedFile(BaseModel):
    """One file's planned change in the ordered work plan."""

    path: str = Field(
        description="Repository-root-relative path of the file to create or modify."
    )
    intent: str = Field(
        description="Precisely what should change in THIS file and why."
    )
    is_new: bool = Field(
        default=False,
        description="True if this file does not yet exist and is created fresh.",
    )


class WorkPlan(BaseModel):
    """Ordered, file-by-file implementation plan produced by the plan step."""

    files: list[PlannedFile] = Field(
        default_factory=list,
        description=(
            "Files to change, in dependency order — a file others import or "
            "depend on comes before its dependents."
        ),
    )


class CodeReview(BaseModel):
    """Structured review of a single generated file.

    ``approved`` is the sole routing signal: approved files are staged as-is,
    unapproved files are regenerated until the cycle ceiling, then staged with a
    warning carrying any unresolved ``blocking_issues``. ``confidence`` is
    recorded for reporting/logging only — it does not gate routing.
    """

    approved: bool = Field(description="True only when there are NO blocking issues.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-rated certainty in this review (0.0–1.0). Reporting only.",
    )
    blocking_issues: list[str] = Field(
        default_factory=list,
        description=(
            "Correctness, security, or requirements gaps that MUST be fixed. "
            "Non-empty implies approved=false."
        ),
    )
    non_blocking_issues: list[str] = Field(
        default_factory=list,
        description="Style/naming/nits that do not block staging the file.",
    )
