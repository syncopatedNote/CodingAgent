from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
from framework_base.mcp_servers.registry import get_mcp_registry
from logger import setup_logger

logger = setup_logger()

# MCP servers run as persistent services accessible via SSE
# over HTTP. This allows proper service-based architecture in Docker Compose.


def _build_client_config() -> dict:
    """
    Build MCP client configuration from registry.

    Returns:
        Dictionary mapping server names to their connection configs
    """
    registry = get_mcp_registry()
    enabled_servers = registry.get_enabled_servers()

    if not enabled_servers:
        raise ValueError("No MCP servers are enabled. Check your .env configuration.")

    config = {}
    for _, server_conf in enabled_servers.items():
        # Skip servers that don't have required credentials
        if not server_conf.is_available():
            continue

        # Get appropriate config based on deployment environment
        server_config = server_conf.get_active_server_config()

        # Only add server if it returned a valid configuration
        if server_config:
            config[server_conf.name] = server_config

    return config


# Initialize the multi-server MCP client with discovered and enabled servers
_config = _build_client_config()

multi_server_mcp_client = MultiServerMCPClient(_build_client_config())


async def get_read_only_tools(server_name: str = None):
    """
    Get only read-only tools from MCP servers.

    Filters tools by the MCP standard 'readOnlyHint' metadata annotation.
    This is useful for search agents that only need query/read operations.

    Args:
        server_name: Optional server name to filter tools from a specific server

    Returns:
        List of tools that have readOnlyHint=True in their metadata
    """
    all_tools = await multi_server_mcp_client.get_tools(server_name=server_name)
    read_only_tools = [
        t
        for t in all_tools
        if hasattr(t, "metadata")
        and t.metadata
        and t.metadata.get("readOnlyHint") is True
    ]
    logger.info(
        f"Filtered {len(read_only_tools)} read-only tools "
        f"from {len(all_tools)} total tools"
    )
    return read_only_tools


if __name__ == "__main__":

    async def main():
        tools = await multi_server_mcp_client.get_tools()
        return tools

    tools = asyncio.run(main())
    print(f"client_initialized: {tools}")
