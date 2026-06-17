"""
gitlab_collector — fetches context from a GitLab repository.

Two modes:
* ``issue_iid`` set  → fetch that issue and return it as requirements.
* otherwise          → fetch the mandatory development-guidelines file from the
                       base branch.

Lifts the ``get_file_contents`` MCP-call logic from the retired
``components/gitlab_handler.py``.
"""

from typing import Optional

from langchain_core.tools import tool

from logger import setup_logger
from settings import settings
from .mcp_fetch import call_mcp_tool, result_to_text

logger = setup_logger(__name__)


@tool
async def gitlab_collector(
    project_id: str = "",
    issue_iid: Optional[int] = None,
    guidelines_file: str = "",
    branch: str = "",
) -> str:
    """Fetch a GitLab issue or the repository's development-guidelines file.

    Use this when the repository is hosted on GitLab. To fetch an issue (as the
    requirements source) pass ``issue_iid``. To fetch the mandatory guidelines
    file, omit ``issue_iid``.

    Args:
        project_id: GitLab project path ("group/project") or numeric id.
            Defaults to the configured GITLAB_PROJECT_ID when omitted.
        issue_iid: Issue internal id to fetch as requirements (optional).
        guidelines_file: Guidelines filename; defaults to the configured value
            (e.g. robots.md).
        branch: Branch/ref to read from; defaults to the configured base branch.
    """
    project = project_id or settings.gitlab_project_id
    ref = branch or settings.coding_base_branch
    if not project:
        return (
            "TERMINAL TOOL FAILURE — no GitLab project id provided and "
            "GITLAB_PROJECT_ID is not configured."
        )

    # ── Issue mode ──────────────────────────────────────────────────
    if issue_iid is not None:
        try:
            raw = await call_mcp_tool(
                "gitlab",
                "get_issue",
                {"project_id": project, "issue_iid": issue_iid},
            )
        except Exception as exc:
            logger.error(f"gitlab_collector issue fetch failed: {exc}")
            return (
                f"TERMINAL TOOL FAILURE — could not fetch GitLab issue "
                f"{project}#{issue_iid}: {exc}."
            )
        return f"GITLAB ISSUE {project}#{issue_iid}:\n{result_to_text(raw)}"

    # ── Guidelines-file mode ────────────────────────────────────────
    filename = guidelines_file or settings.coding_guidelines_filename
    try:
        raw = await call_mcp_tool(
            "gitlab",
            "get_file_contents",
            {"project_id": project, "file_path": filename, "ref": ref},
        )
    except Exception as exc:
        logger.error(f"gitlab_collector guidelines fetch failed: {exc}")
        return (
            f"TERMINAL TOOL FAILURE — could not fetch guidelines file "
            f"'{filename}' from {project}@{ref}: {exc}. The guidelines file "
            "is mandatory — if it does not exist, report a FAILURE."
        )

    content = result_to_text(raw).strip()
    if not content:
        return (
            f"TERMINAL TOOL FAILURE — guidelines file '{filename}' in "
            f"{project}@{ref} is empty. The guidelines file is mandatory."
        )
    return f"DEVELOPMENT GUIDELINES (gitlab {project}@{ref}/{filename}):\n" f"{content}"
