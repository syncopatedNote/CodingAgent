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
        self.description = "GitHub MCP server for repository\
            and project management"
        # Remote HTTP transport (GitHub's hosted MCP server)
        self.http_url = "https://api.githubcopilot.com/mcp/"
        self.command = None  # No local command needed
        self.args = []
        self.env = {}

    def get_active_server_config(self) -> Dict:
        """
        Get the remote GitHub MCP server configuration
        """
        return {
            "url": self.http_url,
            "transport": "streamable_http",
            "headers": {"Authorization": f"Bearer {settings.github_token}"},
        }
