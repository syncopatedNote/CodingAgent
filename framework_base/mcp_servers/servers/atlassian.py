"""
Atlassian MCP Server Configuration
Provides access to Confluence and Jira tools.
"""

from typing import Dict
from ..base_server import MCPServerConfig
from settings import settings


class AtlassianMcpServerConfig(MCPServerConfig):
    """Atlassian MCP Server Configuration for Confluence and Jira"""

    def __init__(self, **data):
        super().__init__(**data)
        self.name = "atlassian"
        self.enabled = getattr(settings, "mcp_atlassian_enabled", True)
        self.description = "Atlassian MCP server for Confluence\
            and Jira integration"
        self.http_url = getattr(settings, "mcp_atlassian_url", "")
        # stdio Transport (Local dev with Docker)
        self.command = "docker"
        self.args = [
            "run",
            "--rm",
            "-i",
            "-e",
            "CONFLUENCE_URL",
            "-e",
            "CONFLUENCE_USERNAME",
            "-e",
            "CONFLUENCE_API_TOKEN",
            "-e",
            "CONFLUENCE_SSL_VERIFY",
            "-e",
            "JIRA_URL",
            "-e",
            "JIRA_USERNAME",
            "-e",
            "JIRA_API_TOKEN",
            "-e",
            "JIRA_PERSONAL_TOKEN",
            "-e",
            "JIRA_SSL_VERIFY",
            "ghcr.io/sooperset/mcp-atlassian:latest",
        ]
        self.env = {
            "CONFLUENCE_URL": settings.confluence_url,
            "CONFLUENCE_USERNAME": settings.confluence_username,
            "CONFLUENCE_API_TOKEN": settings.confluence_api_token,
            "CONFLUENCE_SSL_VERIFY": settings.confluence_ssl_verify,
            "JIRA_URL": settings.jira_url,
            "JIRA_USERNAME": getattr(settings, "jira_username", ""),
            "JIRA_API_TOKEN": getattr(settings, "jira_api_token", ""),
            "JIRA_PERSONAL_TOKEN": settings.jira_personal_token,
            "JIRA_SSL_VERIFY": settings.jira_ssl_verify,
        }

    def get_active_server_config(self) -> Dict:
        """
        Get the appropriate server configuration based
        on available transport
        """
        if self.http_url:
            return self.get_streamable_http_config()
        else:
            return self.get_stdio_config()
