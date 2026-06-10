"""
Sprint Start Agent

Triggered when a Jira sprint starts.  Fetches all open tickets for the
sprint via MCP Jira tools, then drives the coding agent autonomously for
each ticket — no human interaction required.
"""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

from framework_base.multi_server_mcp_client import multi_server_mcp_client
from agents.langgraph_coding_agent import LangGraphCodingAgent
from logger import setup_logger
from settings import settings

logger = setup_logger(__name__)


# ── Result types ───────────────────────────────────────────────────


@dataclass
class TicketResult:
    ticket_id: str
    status: str  # "completed" | "failed" | "skipped"
    branch_name: Optional[str] = None
    failure_reason: Optional[str] = None


@dataclass
class SprintRunResult:
    sprint_id: str
    sprint_name: str
    completed: list[TicketResult] = field(default_factory=list)
    failed: list[TicketResult] = field(default_factory=list)
    skipped: list[TicketResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.failed) + len(self.skipped)


# ── Agent ──────────────────────────────────────────────────────────


class SprintStartAgent:
    """
    Orchestrates autonomous coding-agent runs for every open ticket
    in a Jira sprint.

    Ticket fetching uses MCP Jira tools directly.  Each ticket is
    processed by a fresh invocation of ``LangGraphCodingAgent`` in
    ``autonomous`` mode so no human input is ever requested.
    """

    def __init__(self) -> None:
        self._coding_agent = LangGraphCodingAgent()

    async def run(self, sprint_id: str, sprint_name: str = "") -> SprintRunResult:
        """Process all open tickets in the sprint.

        Parameters
        ----------
        sprint_id:
            Numeric Jira sprint ID (from the webhook payload).
        sprint_name:
            Human-readable sprint name used only for logging.
        """
        result = SprintRunResult(sprint_id=sprint_id, sprint_name=sprint_name)

        tickets = await self._fetch_sprint_tickets(sprint_id)
        if not tickets:
            logger.warning(
                f"No actionable tickets found for sprint "
                f"'{sprint_name}' (id={sprint_id})"
            )
            return result

        logger.info(f"Sprint '{sprint_name}': processing " f"{len(tickets)} ticket(s)")

        max_concurrent = settings.sprint_start_max_concurrent
        if max_concurrent > 1:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def _bounded(ticket: dict) -> TicketResult:
                async with semaphore:
                    # Each parallel run needs its own agent instance
                    # to avoid shared tool-cache race conditions.
                    agent = LangGraphCodingAgent()
                    return await self._process_ticket(ticket, agent)

            ticket_results = await asyncio.gather(*[_bounded(t) for t in tickets])
        else:
            ticket_results = [
                await self._process_ticket(t, self._coding_agent) for t in tickets
            ]

        for tr in ticket_results:
            if tr.status == "completed":
                result.completed.append(tr)
            elif tr.status == "failed":
                result.failed.append(tr)
            else:
                result.skipped.append(tr)

        logger.info(
            f"Sprint '{sprint_name}' complete — "
            f"completed={len(result.completed)}, "
            f"failed={len(result.failed)}, "
            f"skipped={len(result.skipped)}"
        )
        return result

    # ── Ticket fetching ────────────────────────────────────────────

    async def _fetch_sprint_tickets(self, sprint_id: str) -> list[dict]:
        """Return a list of ticket dicts for the sprint.

        Uses ``jira_search`` (mcp-atlassian) to list ticket keys,
        then ``jira_get_issue`` to fetch full details per ticket.
        """
        tools = await multi_server_mcp_client.get_tools()
        tool_map = {t.name: t for t in tools}

        search_tool = tool_map.get("jira_search")
        if not search_tool:
            logger.error(
                "jira_search MCP tool not available — "
                "check MCP Atlassian configuration"
            )
            return []

        # Exclude Done tickets; include Stories, Tasks, and Bugs.
        jql = (
            f"sprint = {sprint_id} "
            f"AND issuetype in (Story, Task, Bug) "
            f"AND statusCategory != Done "
            f"ORDER BY priority ASC"
        )

        try:
            raw = await search_tool.ainvoke({"jql": jql, "max_results": 50})
        except Exception as exc:
            logger.error(
                f"jira_search failed for sprint {sprint_id}: {exc}",
                exc_info=True,
            )
            return []

        ticket_keys = self._extract_ticket_keys(str(raw))
        if not ticket_keys:
            logger.warning(
                f"jira_search returned no ticket keys for sprint "
                f"{sprint_id}. Raw output (truncated): "
                f"{str(raw)[:300]}"
            )
            return []

        logger.info(
            f"Found {len(ticket_keys)} ticket(s) in sprint "
            f"{sprint_id}: {ticket_keys}"
        )

        return await self._fetch_ticket_details(ticket_keys, tool_map)

    async def _fetch_ticket_details(
        self, keys: list[str], tool_map: dict
    ) -> list[dict]:
        """Fetch full issue details for each key."""
        get_issue = tool_map.get("jira_get_issue")
        tickets: list[dict] = []

        for key in keys:
            if get_issue:
                try:
                    details = await get_issue.ainvoke({"issue_key": key})
                    tickets.append({"id": key, "raw_details": str(details)})
                    continue
                except Exception as exc:
                    logger.warning(f"Could not fetch details for {key}: {exc}")
            # Fall back to key-only entry; coding agent will search
            # for the issue itself using MCP tools.
            tickets.append(
                {
                    "id": key,
                    "raw_details": (f"Jira ticket {key} " f"(fetch details from Jira)"),
                }
            )

        return tickets

    @staticmethod
    def _extract_ticket_keys(text: str) -> list[str]:
        """Return deduplicated Jira ticket keys from arbitrary text."""
        return list(dict.fromkeys(re.findall(r"\b[A-Z]+-\d+\b", text)))

    # ── Per-ticket processing ──────────────────────────────────────

    @staticmethod
    def _build_ticket_task(ticket: dict) -> str:
        return (
            f"Implement Jira ticket {ticket['id']}.\n\n"
            f"Ticket details:\n{ticket['raw_details']}"
        )

    async def _process_ticket(
        self, ticket: dict, agent: LangGraphCodingAgent
    ) -> TicketResult:
        ticket_id = ticket["id"]

        if not ticket.get("raw_details", "").strip():
            logger.warning(f"Skipping {ticket_id}: no content")
            return TicketResult(
                ticket_id=ticket_id,
                status="skipped",
                failure_reason="No ticket content",
            )

        task = self._build_ticket_task(ticket)
        logger.info(f"Starting autonomous run for {ticket_id}")

        try:
            result = await agent.run(
                user_input=task,
                thread_id=str(uuid.uuid4()),
                mode="autonomous",
            )
        except Exception as exc:
            logger.error(
                f"Coding agent raised for {ticket_id}: {exc}",
                exc_info=True,
            )
            return TicketResult(
                ticket_id=ticket_id,
                status="failed",
                failure_reason=str(exc),
            )

        response = result.get("response") or ""

        if response.strip().startswith("FAILURE:"):
            first_line = response.strip().splitlines()[0]
            reason = first_line.removeprefix("FAILURE:").strip()
            logger.warning(f"{ticket_id} reported failure: {reason}")
            return TicketResult(
                ticket_id=ticket_id,
                status="failed",
                failure_reason=reason,
            )

        branch = self._extract_branch_name(response)
        logger.info(f"{ticket_id} completed. Branch: {branch or '(not found)'}")
        return TicketResult(
            ticket_id=ticket_id,
            status="completed",
            branch_name=branch,
        )

    @staticmethod
    def _extract_branch_name(response: str) -> Optional[str]:
        """Parse the branch name from the agent's final summary."""
        for pattern in (
            r"[Bb]ranch(?:\s+[Cc]reated)?[:\s]+`?([a-zA-Z0-9/_.-]+)`?",
            r"`([a-zA-Z0-9/_.-]*[A-Z]+-\d+[a-zA-Z0-9/_.-]*)`",
        ):
            match = re.search(pattern, response)
            if match:
                return match.group(1)
        return None
