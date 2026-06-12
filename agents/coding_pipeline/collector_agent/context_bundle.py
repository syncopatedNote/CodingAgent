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
    """All context required to implement a change, gathered by the collector."""

    # Core task text — the Jira/issue description, or the raw user prompt.
    requirements: str = ""
    # The entry-point reference: "PROJ-123" / "owner/repo#42" / "" if free-text.
    source_ref: str = ""
    # Confluence (or other) design-doc content. Empty when none was linked.
    confluence_design_details: str = ""
    # Contents of the mandatory development-guidelines file (e.g. robots.md).
    development_guidelines: str = ""
    # Repository the coding agent should work in (URL / slug / project path).
    repository_reference: str = ""
    # Branch to base work on. Defaults to settings.coding_base_branch.
    target_branch: str = ""
    # "complete" when the bundle is usable, "failed" otherwise.
    status: str = "complete"
    # Human-readable reason when status == "failed".
    failure_reason: Optional[str] = None

    def is_complete(self) -> bool:
        return self.status == "complete"
