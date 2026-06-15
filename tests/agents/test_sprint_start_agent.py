"""Unit tests for SprintStartAgent.

These tests exercise the orchestration logic — ticket fetching, per-ticket
processing, result bucketing, concurrency, and edge cases — without making
any real MCP or LLM calls.

Mock return values for jira_search and jira_get_issue are modelled on the
real mcp-atlassian tool response shape (plain text strings, as confirmed by
the agent's own ``str(raw)`` coercion before regex extraction).

Webhook payload used as the trigger source:
    jira_samples/sprint_start_event.json
        sprint.id   = 1
        sprint.name = "COR Sprint 1"

Real sprint 1 data (fetched from vishal2414.atlassian.net):
    COR-1 | Feature | To Do
         "Add a new llm provider for oracle cloud infrastructure"
         Description: "create a new llm provider for oci infra."
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agents.sprint_start_agent import SprintStartAgent, TicketResult, SprintRunResult


# ── Fixtures ───────────────────────────────────────────────────────


SAMPLES_DIR = Path(__file__).parent.parent.parent / "jira_samples"


@pytest.fixture()
def sprint_payload() -> dict:
    """The real sprint_started webhook payload from jira_samples/."""
    return json.loads((SAMPLES_DIR / "sprint_start_event.json").read_text())


# Real mcp-atlassian jira_search return: a plain text string containing
# issue keys in the format PROJECT-N. The agent calls str(raw) then
# regex-extracts keys with r"\b[A-Z]+-\d+\b".
JIRA_SEARCH_RESULT = (
    "Issues in sprint 1:\n"
    "COR-1: Add a new llm provider for oracle cloud infrastructure [Story] [To Do]\n"
)

# Real mcp-atlassian jira_get_issue return: a formatted text blob with
# the full ticket detail. The agent stores str(details) verbatim as
# raw_details and passes it to the coding pipeline as task context.
JIRA_GET_ISSUE_COR1 = (
    "Issue: COR-1\n"
    "Summary: Add a new llm provider for oracle cloud infrastructure\n"
    "Type: Feature\n"
    "Status: To Do\n"
    "Priority: Medium\n"
    "Description: create a new llm provider for oci infra.\n"
    "Sprint: COR Sprint 1\n"
    "Project: COR\n"
)


def _make_fake_tool(name: str, result: str) -> MagicMock:
    """Return a mock MCP tool whose ainvoke returns *result*."""
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=result)
    return tool


def _make_tool_map(search_result=JIRA_SEARCH_RESULT, issue_result=JIRA_GET_ISSUE_COR1):
    """Return a {name: tool} map with both jira tools wired."""
    return {
        "jira_search": _make_fake_tool("jira_search", search_result),
        "jira_get_issue": _make_fake_tool("jira_get_issue", issue_result),
    }


def _pipeline_success(branch="cortex/add-oci-provider-a1b2") -> AsyncMock:
    """Pipeline mock that returns a successful coding-agent response."""
    mock = AsyncMock()
    mock.run = AsyncMock(
        return_value={
            "response": f"Branch: `{branch}`\nAll files pushed.",
            "interrupt": None,
            "thread_id": "test-thread-id",
        }
    )
    return mock


def _pipeline_failure(reason="repo not found") -> AsyncMock:
    """Pipeline mock that returns a FAILURE: response."""
    mock = AsyncMock()
    mock.run = AsyncMock(
        return_value={
            "response": f"FAILURE: {reason}\nREF: github\nATTEMPTED: context collection",
            "interrupt": None,
            "thread_id": "test-thread-id",
        }
    )
    return mock


def _make_agent(tool_map=None, pipeline=None) -> SprintStartAgent:
    """Build a SprintStartAgent with patched MCP client and pipeline."""
    agent = object.__new__(SprintStartAgent)
    agent._pipeline = pipeline or _pipeline_success()
    agent._tool_map = tool_map or _make_tool_map()
    return agent


# ── _extract_ticket_keys ───────────────────────────────────────────


def test_extract_ticket_keys_finds_standard_keys():
    text = "COR-1 and COR-22 and also PROJ-100 were updated"
    assert SprintStartAgent._extract_ticket_keys(text) == [
        "COR-1",
        "COR-22",
        "PROJ-100",
    ]


def test_extract_ticket_keys_deduplicates():
    text = "COR-1 is blocked by COR-1 and COR-2"
    assert SprintStartAgent._extract_ticket_keys(text) == ["COR-1", "COR-2"]


def test_extract_ticket_keys_preserves_order():
    text = "COR-3 then COR-1 then COR-2"
    assert SprintStartAgent._extract_ticket_keys(text) == ["COR-3", "COR-1", "COR-2"]


def test_extract_ticket_keys_ignores_lowercase():
    assert SprintStartAgent._extract_ticket_keys("cor-1 is invalid") == []


def test_extract_ticket_keys_returns_empty_on_no_match():
    assert SprintStartAgent._extract_ticket_keys("no tickets here") == []


def test_extract_ticket_keys_matches_real_jira_search_output():
    keys = SprintStartAgent._extract_ticket_keys(JIRA_SEARCH_RESULT)
    assert keys == ["COR-1"]


# ── _extract_branch_name ───────────────────────────────────────────


def test_extract_branch_name_from_backtick_format():
    response = "Branch: `cortex/add-oci-provider-a1b2`\nAll files pushed."
    assert (
        SprintStartAgent._extract_branch_name(response)
        == "cortex/add-oci-provider-a1b2"
    )


def test_extract_branch_name_case_insensitive():
    response = "branch created: cortex/cor-1-feature"
    assert SprintStartAgent._extract_branch_name(response) is not None


def test_extract_branch_name_returns_none_when_absent():
    # Avoid the word "branch" — the regex is intentionally loose and would
    # match "branch <word>" even in a negative sentence.
    assert (
        SprintStartAgent._extract_branch_name("All files pushed successfully.") is None
    )


# ── _build_ticket_task ─────────────────────────────────────────────


def test_build_ticket_task_includes_ticket_id_and_details():
    ticket = {"id": "COR-1", "raw_details": JIRA_GET_ISSUE_COR1}
    task = SprintStartAgent._build_ticket_task(ticket)
    assert "COR-1" in task
    assert "oracle cloud infrastructure" in task


# ── _process_ticket ────────────────────────────────────────────────


async def test_process_ticket_returns_completed_on_success():
    agent = _make_agent(pipeline=_pipeline_success("cortex/add-oci-provider-a1b2"))
    ticket = {"id": "COR-1", "raw_details": JIRA_GET_ISSUE_COR1}

    result = await agent._process_ticket(ticket, agent._pipeline)

    assert result.status == "completed"
    assert result.ticket_id == "COR-1"
    assert result.branch_name == "cortex/add-oci-provider-a1b2"
    assert result.failure_reason is None


async def test_process_ticket_returns_failed_on_failure_response():
    agent = _make_agent(pipeline=_pipeline_failure("repository inaccessible"))
    ticket = {"id": "COR-1", "raw_details": JIRA_GET_ISSUE_COR1}

    result = await agent._process_ticket(ticket, agent._pipeline)

    assert result.status == "failed"
    assert result.failure_reason == "repository inaccessible"
    assert result.branch_name is None


async def test_process_ticket_returns_skipped_when_no_details():
    agent = _make_agent()
    ticket = {"id": "COR-1", "raw_details": ""}

    result = await agent._process_ticket(ticket, agent._pipeline)

    assert result.status == "skipped"
    assert result.failure_reason == "No ticket content"
    agent._pipeline.run.assert_not_called()


async def test_process_ticket_returns_failed_on_pipeline_exception():
    pipeline = AsyncMock()
    pipeline.run = AsyncMock(side_effect=RuntimeError("unexpected crash"))
    agent = _make_agent(pipeline=pipeline)
    ticket = {"id": "COR-1", "raw_details": JIRA_GET_ISSUE_COR1}

    result = await agent._process_ticket(ticket, agent._pipeline)

    assert result.status == "failed"
    assert "unexpected crash" in result.failure_reason


async def test_process_ticket_passes_autonomous_mode_to_pipeline():
    agent = _make_agent(pipeline=_pipeline_success())
    ticket = {"id": "COR-1", "raw_details": JIRA_GET_ISSUE_COR1}

    await agent._process_ticket(ticket, agent._pipeline)

    call_kwargs = agent._pipeline.run.call_args
    assert call_kwargs.kwargs.get("mode") == "autonomous"


# ── _fetch_sprint_tickets (full flow with mocked MCP) ─────────────


async def test_fetch_sprint_tickets_returns_ticket_with_real_details():
    agent = _make_agent()
    tool_map = _make_tool_map()

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=list(tool_map.values()))
        tickets = await agent._fetch_sprint_tickets("1")

    assert len(tickets) == 1
    assert tickets[0]["id"] == "COR-1"
    assert "oracle cloud infrastructure" in tickets[0]["raw_details"]


async def test_fetch_sprint_tickets_returns_empty_when_jira_search_missing():
    agent = _make_agent()
    # Only confluence tools available — no jira_search
    confluence_tool = _make_fake_tool("confluence_search", "")

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=[confluence_tool])
        tickets = await agent._fetch_sprint_tickets("1")

    assert tickets == []


async def test_fetch_sprint_tickets_returns_empty_when_search_raises():
    agent = _make_agent()
    broken_search = MagicMock()
    broken_search.name = "jira_search"
    broken_search.ainvoke = AsyncMock(side_effect=ConnectionError("MCP down"))

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=[broken_search])
        tickets = await agent._fetch_sprint_tickets("1")

    assert tickets == []


async def test_fetch_sprint_tickets_falls_back_to_key_only_when_get_issue_fails():
    agent = _make_agent()
    search_tool = _make_fake_tool("jira_search", JIRA_SEARCH_RESULT)
    broken_get = MagicMock()
    broken_get.name = "jira_get_issue"
    broken_get.ainvoke = AsyncMock(side_effect=Exception("not found"))

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=[search_tool, broken_get])
        tickets = await agent._fetch_sprint_tickets("1")

    assert len(tickets) == 1
    assert tickets[0]["id"] == "COR-1"
    # Fallback raw_details contains the key so the pipeline can still search
    assert "COR-1" in tickets[0]["raw_details"]


async def test_fetch_sprint_tickets_uses_correct_jql_for_sprint(sprint_payload):
    """JQL must filter by sprint id, open issue types, and exclude Done."""
    agent = _make_agent()
    tool_map = _make_tool_map()

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=list(tool_map.values()))
        sprint_id = str(sprint_payload["sprint"]["id"])  # "1"
        await agent._fetch_sprint_tickets(sprint_id)

    jql_call = tool_map["jira_search"].ainvoke.call_args[0][0]["jql"]
    assert "sprint = 1" in jql_call
    assert "Story" in jql_call
    assert "Task" in jql_call
    assert "Bug" in jql_call
    assert "Done" in jql_call


# ── SprintRunResult ────────────────────────────────────────────────


def test_sprint_run_result_total_counts_all_buckets():
    result = SprintRunResult(sprint_id="1", sprint_name="COR Sprint 1")
    result.completed.append(TicketResult("COR-1", "completed", "cortex/branch"))
    result.failed.append(TicketResult("COR-2", "failed", failure_reason="err"))
    result.skipped.append(TicketResult("COR-3", "skipped"))
    assert result.total == 3


def test_sprint_run_result_starts_empty():
    result = SprintRunResult(sprint_id="1", sprint_name="COR Sprint 1")
    assert result.total == 0
    assert result.completed == []
    assert result.failed == []
    assert result.skipped == []


# ── run() — full end-to-end with real sprint_start_event.json ─────


async def test_run_processes_sprint_from_webhook_payload(sprint_payload):
    """Full run driven by the real webhook sample in jira_samples/."""
    sprint = sprint_payload["sprint"]
    agent = _make_agent(
        tool_map=_make_tool_map(),
        pipeline=_pipeline_success("cortex/add-oci-provider-a1b2"),
    )

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=list(_make_tool_map().values()))
        result = await agent.run(
            sprint_id=str(sprint["id"]),
            sprint_name=sprint["name"],
        )

    assert result.sprint_id == "1"
    assert result.sprint_name == "COR Sprint 1"
    assert len(result.completed) == 1
    assert result.completed[0].ticket_id == "COR-1"
    assert result.completed[0].branch_name == "cortex/add-oci-provider-a1b2"
    assert result.failed == []
    assert result.skipped == []


async def test_run_returns_empty_result_when_no_tickets(sprint_payload):
    sprint = sprint_payload["sprint"]
    agent = _make_agent(tool_map=_make_tool_map(search_result="No issues found."))

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(
            return_value=list(_make_tool_map(search_result="No issues found.").values())
        )
        result = await agent.run(
            sprint_id=str(sprint["id"]),
            sprint_name=sprint["name"],
        )

    assert result.total == 0


async def test_run_buckets_mixed_results(sprint_payload):
    """Two tickets: one succeeds, one fails — both correctly bucketed."""
    sprint = sprint_payload["sprint"]

    multi_search_result = (
        "COR-1: Add OCI provider [Story] [To Do]\n"
        "COR-2: Fix token refresh bug [Bug] [In Progress]\n"
    )
    cor2_details = (
        "Issue: COR-2\nSummary: Fix token refresh bug\n"
        "Type: Bug\nStatus: In Progress\n"
    )

    call_count = 0

    async def _get_issue_side_effect(args):
        nonlocal call_count
        call_count += 1
        if args["issue_key"] == "COR-1":
            return JIRA_GET_ISSUE_COR1
        return cor2_details

    search_tool = _make_fake_tool("jira_search", multi_search_result)
    get_tool = MagicMock()
    get_tool.name = "jira_get_issue"
    get_tool.ainvoke = AsyncMock(side_effect=_get_issue_side_effect)

    pipeline_success = _pipeline_success("cortex/add-oci-provider-a1b2")
    run_count = 0

    async def _pipeline_run_side_effect(**kwargs):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            return {
                "response": "Branch: `cortex/add-oci-provider-a1b2`\nPushed.",
                "interrupt": None,
                "thread_id": "t1",
            }
        return {
            "response": "FAILURE: branch creation failed\nREF: github\nATTEMPTED: push",
            "interrupt": None,
            "thread_id": "t2",
        }

    agent = _make_agent(pipeline=pipeline_success)
    agent._pipeline.run = AsyncMock(side_effect=_pipeline_run_side_effect)

    with patch("agents.sprint_start_agent.multi_server_mcp_client") as mock_client:
        mock_client.get_tools = AsyncMock(return_value=[search_tool, get_tool])
        result = await agent.run(
            sprint_id=str(sprint["id"]),
            sprint_name=sprint["name"],
        )

    assert len(result.completed) == 1
    assert len(result.failed) == 1
    assert result.completed[0].ticket_id == "COR-1"
    assert result.failed[0].ticket_id == "COR-2"
    assert result.total == 2
