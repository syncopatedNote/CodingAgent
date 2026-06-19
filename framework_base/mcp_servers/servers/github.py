"""
GitHub MCP Server Configuration
Provides access to GitHub repositories, issues, PRs, etc.
"""

from typing import Dict
from ..base_server import MCPServerConfig
from settings import settings


class GithubMcpServerConfig(MCPServerConfig):
    """GitHub MCP Server Configuration - Uses GitHub's remote hosted server"""

    def __init__(self, **data):
        super().__init__(**data)
        self.name = "github"
        self.enabled = settings.mcp_github_enabled
        self.description = "GitHub MCP server for repository and project management"
        self.http_url = settings.mcp_github_url
        self.command = None
        self.args = []
        self.env = {}

    def get_active_server_config(self) -> Dict:
        """Get the GitHub MCP server configuration."""
        return {
            "url": self.http_url,
            "transport": "streamable_http",
        }
