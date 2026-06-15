"""Shared fixtures for the coding-agent unit tests.

These tests exercise the read-before-write and branch-enforcement logic in
``LangGraphCodingAgent`` without constructing real LLM or MCP clients. The
agent is built via ``object.__new__`` so ``__init__`` (which builds an LLM and
reads the live MCP server list) never runs; only the attributes the helpers
touch are populated.
"""

import pytest

from agents.coding_pipeline.coding_agent.langgraph_coding_agent import (
    LangGraphCodingAgent,
)


class FakeTool:
    """Minimal stand-in for a loaded MCP tool.

    ``ainvoke`` returns ``result`` unless ``raises`` is set, in which case it
    raises that exception (used to simulate a 404 / missing file).
    """

    def __init__(self, name, result=None, raises=None):
        self.name = name
        self._result = result
        self._raises = raises
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        if self._raises is not None:
            raise self._raises
        return self._result


@pytest.fixture
def make_agent():
    """Return a factory that builds a bare agent with given loaded MCP tools.

    Usage: ``agent = make_agent({"github": [FakeTool("get_file_contents", ...)]})``
    """

    def _factory(tools_by_server=None):
        agent = object.__new__(LangGraphCodingAgent)
        agent._mcp_tools_by_server = tools_by_server or {}
        return agent

    return _factory


@pytest.fixture
def github_state():
    """A representative CodingTaskState for a GitHub run."""
    return {
        "messages": [],
        "mode": "autonomous",
        "active_mcp_server": "github",
        "coding_guidelines": "guidelines text",
        "repo_source": "github",
        "repo_owner": "acme",
        "repo_reference": "widgets",
        "repo_base_branch": "main",
    }
