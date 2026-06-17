"""
jira_collector — fetches a Jira ticket and surfaces its requirements plus any
linked repository / Confluence design pages.

Lifts the MCP-call logic from the retired ``components/jira_handler.py`` and the
link-finding from ``components/confluence_handler.py``, but returns plain text to
the collector LLM instead of a LangGraph ``Command``.
"""

import json
import re
from typing import Optional

from langchain_core.tools import tool

from logger import setup_logger
from .mcp_fetch import call_mcp_tool

logger = setup_logger(__name__)

# A Confluence/design link: any URL that looks like a wiki/Confluence page.
_CONFLUENCE_RE = re.compile(
    r"https?://[^\s)\]]*(?:confluence|/wiki/|/pages/)[^\s)\]]*",
    re.IGNORECASE,
)
# A git repository link on GitHub or GitLab.
_REPO_RE = re.compile(
    r"https?://[^\s)\]]*(?:github\.com|gitlab)[^\s)\]]*",
    re.IGNORECASE,
)


def _find_first(pattern: re.Pattern, *texts: str) -> Optional[str]:
    """Return the first regex match across *texts*, searched in order."""
    for text in texts:
        if not text:
            continue
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _coerce(data):
    """Parse a tool result that may be a JSON string into a dict/list."""
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return data
    return data


def _extract_fields(ticket) -> dict:
    """Best-effort pull of summary/description/labels/comments from the result.

    The mcp-atlassian shape varies (sometimes nested under ``fields``,
    sometimes flat), so we probe both.
    """
    if not isinstance(ticket, dict):
        return {}
    fields = ticket.get("fields", ticket)
    labels = fields.get("labels", []) or ticket.get("labels", [])
    return {
        "summary": fields.get("summary", "") or ticket.get("summary", ""),
        "description": fields.get("description", "") or ticket.get("description", ""),
        "labels": labels if isinstance(labels, list) else [labels],
        "comments_blob": json.dumps(
            fields.get("comment", ticket.get("comments", "")), default=str
        ),
    }


@tool
async def jira_collector(ticket_key: str) -> str:
    """Fetch a Jira ticket and return its requirements plus discovered links.

    Use this when the user's request references a Jira ticket (e.g. PROJ-123).
    The returned text includes the ticket summary/description and any git
    repository link or Confluence design link found on the ticket — call the
    matching repo/confluence sub-collector next to fetch those.

    Args:
        ticket_key: The Jira issue key, e.g. "PROJ-123".
    """
    try:
        raw = await call_mcp_tool(
            "atlassian",
            "jira_get_issue",
            {
                "issue_key": ticket_key,
                "fields": "summary,description,comment,labels",
                "comment_limit": 50,
            },
        )
    except Exception as exc:
        logger.error(f"jira_collector failed for {ticket_key}: {exc}")
        return (
            f"TERMINAL TOOL FAILURE — could not fetch Jira ticket "
            f"'{ticket_key}': {exc}. Do NOT retry with the same key."
        )

    ticket = _coerce(raw)
    fields = _extract_fields(ticket)
    labels_text = " ".join(str(x) for x in fields.get("labels", []))
    full_blob = raw if isinstance(raw, str) else json.dumps(raw, default=str)

    # Prefer Labels, then description, then comments/whole-ticket for links.
    repo_link = _find_first(
        _REPO_RE,
        labels_text,
        fields.get("description", ""),
        fields.get("comments_blob", ""),
        full_blob,
    )
    confluence_link = _find_first(
        _CONFLUENCE_RE,
        labels_text,
        fields.get("description", ""),
        fields.get("comments_blob", ""),
        full_blob,
    )

    summary = fields.get("summary", "") or "(no summary)"
    description = fields.get("description", "") or full_blob[:4000]

    return (
        f"JIRA TICKET {ticket_key}\n"
        f"Summary: {summary}\n\n"
        f"Description:\n{description}\n\n"
        f"Discovered repository link: {repo_link or 'NONE FOUND'}\n"
        f"Discovered Confluence/design link: "
        f"{confluence_link or 'NONE FOUND'}\n"
    )
