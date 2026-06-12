"""
confluence_collector — fetches the design content of a Confluence page.

Lifts the page-id extraction and ``confluence_get_page`` MCP call from the
retired ``components/confluence_handler.py``.
"""

import re

from langchain_core.tools import tool

from logger import setup_logger
from .mcp_fetch import call_mcp_tool, result_to_text

logger = setup_logger(__name__)

_PAGE_ID_RE = re.compile(r"/pages/(\d+)")


def _resolve_page_id(page_ref: str) -> str:
    """Accept a full Confluence URL or a bare numeric id and return the id."""
    page_ref = (page_ref or "").strip()
    if page_ref.isdigit():
        return page_ref
    match = _PAGE_ID_RE.search(page_ref)
    return match.group(1) if match else ""


@tool
async def confluence_collector(page_ref: str) -> str:
    """Fetch a Confluence design page and return its content as markdown.

    Use this when a Confluence/design link was provided by the user or surfaced
    by ``jira_collector``.

    Args:
        page_ref: A Confluence page URL (…/pages/<id>/…) or a bare page id.
    """
    page_id = _resolve_page_id(page_ref)
    if not page_id:
        return (
            f"TERMINAL TOOL FAILURE — could not extract a page id from "
            f"'{page_ref}'. Provide a Confluence URL containing /pages/<id>/ "
            "or a numeric page id."
        )

    try:
        raw = await call_mcp_tool(
            "atlassian",
            "confluence_get_page",
            {
                "page_id": page_id,
                "convert_to_markdown": True,
                "include_metadata": True,
            },
        )
    except Exception as exc:
        logger.error(f"confluence_collector failed for page {page_id}: {exc}")
        return (
            f"TERMINAL TOOL FAILURE — could not fetch Confluence page "
            f"'{page_id}': {exc}. Do NOT retry with the same id."
        )

    content = result_to_text(raw).strip()
    if not content:
        return f"Confluence page {page_id} was fetched but returned no content."
    return f"CONFLUENCE DESIGN (page {page_id}):\n{content}"
