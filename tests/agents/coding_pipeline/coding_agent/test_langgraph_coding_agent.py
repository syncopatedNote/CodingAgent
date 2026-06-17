"""Unit tests for the read-before-write logic in ``LangGraphCodingAgent``.

Covers:
* ``_PROVIDER_TOOLS`` map shape.
* ``_fetch_existing_code`` — inject on hit, None on 404 / empty / blank path /
  fresh-write exclusion / unknown provider / unloaded tool.
"""

import pytest

from agents.coding_pipeline.coding_agent.repo_mcp_helpers import (
    PROVIDER_TOOLS as _PROVIDER_TOOLS,
    FRESH_WRITE_PATHS as _FRESH_WRITE_PATHS,
)
from tests.agents.coding_pipeline.coding_agent.conftest import FakeTool


# ── _PROVIDER_TOOLS map ────────────────────────────────────────────


def test_provider_map_has_github_and_gitlab():
    assert set(_PROVIDER_TOOLS) == {"github", "gitlab"}


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_map_has_all_roles(provider):
    roles = _PROVIDER_TOOLS[provider]
    assert set(roles) == {"tree", "read", "branch", "write"}
    assert all(isinstance(v, str) and v for v in roles.values())


def test_provider_tree_tools_differ_by_provider():
    # The whole point of the map: GitHub and GitLab name the tree tool
    # differently, so a hardcoded name would break one of them.
    assert _PROVIDER_TOOLS["github"]["tree"] == "get_repository_tree"
    assert _PROVIDER_TOOLS["gitlab"]["tree"] == "list_repository_tree"


# ── _fetch_existing_code ───────────────────────────────────────────


async def test_fetch_injects_existing_contents_on_hit(make_agent, github_state):
    read_tool = FakeTool("get_file_contents", result="print('hi')\n")
    agent = make_agent({"github": [read_tool]})

    result = await agent._fetch_existing_code(github_state, "app/main.py")

    assert result == "print('hi')"  # stripped
    # Fetched with the repo coordinates from state.
    assert read_tool.calls == [
        {"owner": "acme", "repo": "widgets", "path": "app/main.py", "ref": "main"}
    ]


async def test_fetch_returns_none_on_404(make_agent, github_state):
    read_tool = FakeTool("get_file_contents", raises=Exception("404 Not Found"))
    agent = make_agent({"github": [read_tool]})

    result = await agent._fetch_existing_code(github_state, "app/new_file.py")

    assert result is None  # new file → generate fresh


async def test_fetch_returns_none_on_empty_file(make_agent, github_state):
    read_tool = FakeTool("get_file_contents", result="   \n  ")
    agent = make_agent({"github": [read_tool]})

    result = await agent._fetch_existing_code(github_state, "app/empty.py")

    assert result is None


async def test_fetch_skips_blank_target_path(make_agent, github_state):
    read_tool = FakeTool("get_file_contents", result="data")
    agent = make_agent({"github": [read_tool]})

    result = await agent._fetch_existing_code(github_state, "")

    assert result is None
    assert read_tool.calls == []  # never called


async def test_fetch_skips_fresh_write_paths(make_agent, github_state):
    fresh = next(iter(_FRESH_WRITE_PATHS))
    read_tool = FakeTool("get_file_contents", result="old content")
    agent = make_agent({"github": [read_tool]})

    result = await agent._fetch_existing_code(github_state, fresh)

    assert result is None
    assert read_tool.calls == []  # excluded file is never fetched


async def test_fetch_skips_unknown_provider(make_agent, github_state):
    state = {**github_state, "repo_source": "bitbucket"}
    agent = make_agent({"github": [FakeTool("get_file_contents", result="x")]})

    result = await agent._fetch_existing_code(state, "app/main.py")

    assert result is None  # no map entry → no fetch


async def test_fetch_returns_none_when_read_tool_not_loaded(make_agent, github_state):
    # Provider is mapped, but the read tool wasn't loaded into the cache.
    agent = make_agent({"github": [FakeTool("some_other_tool")]})

    result = await agent._fetch_existing_code(github_state, "app/main.py")

    assert result is None
