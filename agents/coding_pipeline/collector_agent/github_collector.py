"""
github_collector — fetches context from a GitHub repository.

Two modes:
* ``issue_number`` set → fetch that issue and return it as requirements.
* otherwise            → fetch the mandatory development-guidelines file from
                         the base branch.

Mirrors ``gitlab_collector`` against the GitHub MCP server. The repository owner
comes from ``settings.coding_repository_owner`` (mandatory).
"""

from typing import Optional

from langchain_core.tools import tool

from logger import setup_logger
from settings import settings
from .mcp_fetch import call_mcp_tool, result_to_text

logger = setup_logger(__name__)


@tool
async def github_collector(
    repo: str,
    issue_number: Optional[int] = None,
    guidelines_file: str = "",
    branch: str = "",
    owner: str = "",
) -> str | dict:
    """Fetch a GitHub issue or the repository's development-guidelines file.

    Use this when the repository is hosted on GitHub. To fetch an issue (as the
    requirements source) pass ``issue_number``. To fetch the mandatory
    guidelines file, omit ``issue_number``.

    Args:
        repo: Repository name (without the owner).
        issue_number: Issue number to fetch as requirements (optional).
        guidelines_file: Guidelines filename; defaults to the configured value.
        branch: Branch/ref to read from; defaults to the configured base branch.
        owner: Repository owner/org; defaults to CODING_REPOSITORY_OWNER.
    """
    repo_owner = owner or (settings.coding_repository_owner or "")
    ref = branch or settings.coding_base_branch
    if not repo_owner:
        return (
            "TERMINAL TOOL FAILURE — no repository owner provided and "
            "CODING_REPOSITORY_OWNER is not configured."
        )
    if not repo:
        return "TERMINAL TOOL FAILURE — no repository name provided."

    # ── Issue mode ──────────────────────────────────────────────────
    if issue_number is not None:
        try:
            raw = await call_mcp_tool(
                "github",
                "get_issue",
                {
                    "owner": repo_owner,
                    "repo": repo,
                    "issue_number": issue_number,
                },
            )
        except Exception as exc:
            logger.error(f"github_collector issue fetch failed: {exc}")
            return (
                f"TERMINAL TOOL FAILURE — could not fetch GitHub issue "
                f"{repo_owner}/{repo}#{issue_number}: {exc}."
            )
        return (
            f"GITHUB ISSUE {repo_owner}/{repo}#{issue_number}:\n"
            f"{result_to_text(raw)}"
        )

    # ── Guidelines-file mode ────────────────────────────────────────
    filename = guidelines_file or settings.coding_guidelines_filename
    try:
        raw = await call_mcp_tool(
            "github",
            "get_file_contents",
            {
                "owner": repo_owner,
                "repo": repo,
                "path": filename,
                "ref": ref,
            },
        )
    except Exception as exc:
        logger.error(f"github_collector guidelines fetch failed: {exc}")
        return (
            f"TERMINAL TOOL FAILURE — could not fetch guidelines file "
            f"'{filename}' from {repo_owner}/{repo}@{ref}: {exc}. The "
            "guidelines file is mandatory — if it does not exist, report a "
            "FAILURE."
        )

    content = result_to_text(raw).strip()
    if not content:
        return (
            f"TERMINAL TOOL FAILURE — guidelines file '{filename}' in "
            f"{repo_owner}/{repo}@{ref} is empty. The guidelines file is "
            "mandatory."
        )
    return {
        "__guidelines_payload__": True,
        "content": content,
        "signal": (
            f"✓ Development guidelines fetched from "
            f"github {repo_owner}/{repo}@{ref}/{filename} "
            f"({len(content)} chars) — stored for hand-off. "
            "Proceed to the next step."
        ),
    }
