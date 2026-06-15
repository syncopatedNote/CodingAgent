"""
Shared repository-MCP helpers for the coding agents.

Both the improvised :class:`LangGraphCodingAgent` and the deterministic
:class:`DeterministicCodingAgent` talk to the same GitHub/GitLab MCP servers to
explore the repo tree, read existing file contents (read-before-write), and push
finalised files. The provider-specific tool-name map and the fetch/load plumbing
are identical between them, so they live here as plain functions keyed on a
caller-owned per-server tool cache (no shared mutable module state).
"""

from typing import Optional

from framework_base.mcp_servers.multi_server_mcp_client import (
    multi_server_mcp_client,
)
from logger import setup_logger
from ..collector_agent.mcp_fetch import result_to_text

logger = setup_logger(__name__)


# Per-provider MCP tool names, keyed by repo_source. The "tree" tool gives the
# live repository structure; "read" fetches a single file's contents; "branch"
# creates a work branch; "write" creates/updates a file on a branch. Add an
# entry here when onboarding a new repository provider.
PROVIDER_TOOLS: dict[str, dict[str, str]] = {
    "github": {
        "tree": "get_repository_tree",
        "read": "get_file_contents",
        "branch": "create_branch",
        "write": "create_or_update_file",
    },
    "gitlab": {
        "tree": "list_repository_tree",
        "read": "get_file_contents",
        "branch": "create_branch",
        "write": "create_or_update_file",
    },
}

# Generated artifacts written fresh every run; their remote contents must NOT be
# injected as existing_code (each run pushes to a new branch).
FRESH_WRITE_PATHS: frozenset[str] = frozenset({"assumptions_and_decisions.md"})


async def load_server_tools_cached(server_name: str, cache: dict[str, list]) -> list:
    """Return tools for *server_name*, loading from the MCP client once.

    *cache* is a caller-owned ``{server_name: [tools]}`` dict; results are stored
    there and reused on subsequent calls. Returns ``[]`` on failure (logged).
    """
    if server_name in cache:
        logger.debug(f"Using cached tools for MCP server '{server_name}'")
        return cache[server_name]

    try:
        tools = await multi_server_mcp_client.get_tools(server_name=server_name)
        cache[server_name] = tools
        logger.info(
            f"Loaded and cached {len(tools)} tools for MCP server "
            f"'{server_name}': {[t.name for t in tools]}"
        )
        return tools
    except Exception as exc:
        logger.error(
            f"Failed to load tools for MCP server '{server_name}': {exc}",
            exc_info=True,
        )
        return []


def find_tool(cache: dict[str, list], server_name: str, tool_name: str):
    """Return the named tool from *server_name*'s cached tools, or ``None``."""
    return next(
        (t for t in cache.get(server_name, []) if t.name == tool_name),
        None,
    )


async def fetch_existing_code(
    cache: dict[str, list],
    *,
    provider: str,
    owner: str,
    repo_reference: str,
    base_branch: str,
    target_path: str,
) -> Optional[str]:
    """Fetch current contents of *target_path* from the repo, or ``None``.

    Returns the file's text when it exists on *base_branch* (so the caller injects
    it as ``existing_code``), or ``None`` when the path is blank, excluded, the
    provider/tool is unknown, or the fetch fails (e.g. a 404 for a new file —
    generate fresh in that case).
    """
    if not target_path or target_path in FRESH_WRITE_PATHS:
        return None

    read_tool_name = PROVIDER_TOOLS.get(provider, {}).get("read")
    if not read_tool_name:
        logger.debug(f"No read tool mapped for provider '{provider}'")
        return None

    read_tool = find_tool(cache, provider, read_tool_name)
    if read_tool is None:
        logger.debug(f"Read tool '{read_tool_name}' not loaded for '{provider}'")
        return None

    fetch_args = {
        "owner": owner,
        "repo": repo_reference,
        "path": target_path,
        "ref": base_branch,
    }
    try:
        raw = await read_tool.ainvoke(fetch_args)
    except Exception as exc:
        logger.info(
            f"No existing contents for '{target_path}' "
            f"({type(exc).__name__}) — generating fresh"
        )
        return None

    existing = result_to_text(raw).strip()
    if not existing:
        return None
    logger.info(
        f"Injected existing contents for '{target_path}' ({len(existing)} chars)"
    )
    return existing
