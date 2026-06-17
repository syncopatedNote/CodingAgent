"""
ContextBundle — the structured hand-off from the context collector to the
coding agent.

The collector gathers everything the coding agent needs up front (requirements,
design, mandatory development guidelines, the target repo/branch) and packs it
into this immutable dataclass. The coding agent then runs a pure
generate → review → push loop with no further context gathering.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ContextBundle:
    """All context required to implement a change, gathered by the
    collector."""

    # Core task text — the Jira/issue description, or the raw user prompt.
    requirements: str = ""
    # The repository provider service - github or gitlab.
    repo_source: str = ""
    # Confluence (or other) design-doc content. Empty when none was linked.
    confluence_design_details: str = ""
    # Contents of the mandatory development-guidelines file (e.g. robots.md).
    development_guidelines: str = ""
    # Repository name for github or project id for gitlab
    repository_reference: str = ""
    # Owner/org for github; unused for gitlab project ids. Falls back to
    # settings.coding_repository_owner.
    repository_owner: str = ""
    # Branch to base work on. Defaults to settings.coding_base_branch.
    base_branch: str = ""
    # GitHub/GitLab issue details when an issue was linked on the Jira ticket.
    # Format: "<issue label> - <issue title> - <issue description>".
    # Empty when no issue link was present; fetch is skipped in that case.
    git_issue_details: str = ""
    # "complete" when the bundle is usable, "failed" otherwise.
    status: str = "complete"
    # Human-readable reason when status == "failed".
    failure_reason: Optional[str] = None

    def is_complete(self) -> bool:
        return self.status == "complete"
