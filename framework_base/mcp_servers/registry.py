"""
MCP Server Registry
Manages registration and discovery of MCP servers.
"""

from typing import Dict, Optional
from .base_server import MCPServerConfig
from logger import setup_logger

logger = setup_logger(__name__)


class MCPServerRegistry:
    """Registry for managing MCP server configurations"""

    def __init__(self):
        self._servers: Dict[str, MCPServerConfig] = {}

    def register(self, server: MCPServerConfig) -> None:
        """
        Register a new MCP server configuration

        Args:
            server: MCPServerConfig instance to register
        """
        if server.name in self._servers:
            logger.warning(
                f"Server '{server.name}'\
                           already registered, overwriting"
            )

        self._servers[server.name] = server
        logger.debug(
            f"Registered MCP server: {server.name} " f"(enabled={server.enabled})"
        )

    def unregister(self, name: str) -> None:
        """Remove a server from registry"""
        if name in self._servers:
            del self._servers[name]
            logger.debug(f"Unregistered MCP server: {name}")

    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """Get a specific server configuration by name"""
        return self._servers.get(name)

    def get_all_servers(self) -> Dict[str, MCPServerConfig]:
        """Get all registered servers"""
        return dict(self._servers)

    def get_enabled_servers(self) -> Dict[str, MCPServerConfig]:
        """
        Get only enabled servers that have proper configuration

        Returns:
            Dictionary of server name to server config for enabled servers
        """
        enabled = {
            name: server
            for name, server in self._servers.items()
            if server.enabled and server.is_available()
        }

        logger.info(
            f"Found {len(enabled)} enabled MCP servers: " f"{list(enabled.keys())}"
        )
        return enabled

    def list_servers(self) -> Dict[str, bool]:
        """Get a summary of all servers and their enabled status"""
        return {name: server.enabled for name, server in self._servers.items()}


# Global registry instance
_registry: Optional[MCPServerRegistry] = None


def get_mcp_registry() -> MCPServerRegistry:
    """
    Get or create the global MCP server registry

    Returns:
        The global MCPServerRegistry instance
    """
    global _registry

    if _registry is None:
        _registry = MCPServerRegistry()
        # Auto-discover and register all servers
        _auto_register_servers(_registry)

    return _registry


def _auto_register_servers(registry: MCPServerRegistry):
    """Automatically discover and register all available MCP servers"""
    from .servers.atlassian import AtlassianMcpServerConfig
    from .servers.gitlab import GitlabMcpServerConfig
    from .servers.github import GithubMcpServerConfig

    try:
        # Register Atlassian server
        registry.register(AtlassianMcpServerConfig())
    except Exception as e:
        logger.error(f"Failed to register Atlassian server: {e}")

    try:
        # Register GitLab server
        registry.register(GitlabMcpServerConfig())
    except Exception as e:
        logger.error(f"Failed to register GitLab server: {e}")

    try:
        # Register GitHub server
        registry.register(GithubMcpServerConfig())
    except Exception as e:
        logger.error(f"Failed to register GitHub server: {e}")
