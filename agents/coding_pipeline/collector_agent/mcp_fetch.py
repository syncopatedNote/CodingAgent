"""
Small MCP helpers shared by the per-platform sub-collectors.

Each sub-collector opens a session to one MCP server, finds the tool it needs
by name, invokes it, and normalises the (str | dict) result to text. This
factors out that repetition. The logic mirrors the now-retired
``agents/components/*_handler.py`` files this package replaces.
"""

import json
from typing import Any

from langchain_mcp_adapters.tools import load_mcp_tools

from framework_base.mcp_servers.multi_server_mcp_client import (
    multi_server_mcp_client,
)
from logger import setup_logger

logger = setup_logger(__name__)


def result_to_text(result: Any) -> str:
    """Best-effort extraction of human-readable text from an MCP tool result.

    MCP tools return either a plain string or a dict whose payload lives under
    one of a few common keys. Falls back to a JSON dump.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("content", "value", "text", "body"):
            if key in result:
                inner = result[key]
                if isinstance(inner, dict):
                    # e.g. {"content": {"value": "..."}}
                    return inner.get("value", json.dumps(inner, default=str))
                return (
                    inner if isinstance(inner, str) else json.dumps(inner, default=str)
                )
        return json.dumps(result, default=str)
    return str(result)


async def call_mcp_tool(server: str, tool_name_substr: str, args: dict) -> Any:
    """Invoke the first tool on *server* whose name contains *tool_name_substr*.

    Returns the raw tool result so callers can parse fields themselves.
    Raises ``ValueError`` (treated as terminal, non-retryable) when no matching
    tool is available on the server.
    """
    async with multi_server_mcp_client.session(server) as session:
        tools = await load_mcp_tools(session)
        tool = next((t for t in tools if tool_name_substr in t.name), None)
        if tool is None:
            available = [t.name for t in tools]
            raise ValueError(
                f"No MCP tool matching '{tool_name_substr}' on server "
                f"'{server}'. Available tools: {available}"
            )
        logger.info(f"Collector calling MCP tool '{tool.name}' on '{server}'")
        return await tool.ainvoke(args)
