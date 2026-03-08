"""
GitLab MCP Server Configuration
Provides access to GitLab repositories, issues, MRs, etc.
"""

from typing import Dict
from ..base_server import MCPServerConfig
from settings import settings


class GitlabMcpServerConfig(MCPServerConfig):
    """GitLab MCP Server Configuration"""

    def __init__(self, **data):
        super().__init__(**data)
        self.name = "gitlab"
        self.enabled = settings.mcp_gitlab_enabled
        self.description = "GitLab MCP server for repository\
            and project management"
        self.http_url = settings.mcp_gitlab_url
        self.command = "docker"
        self.args = [
            "run",
            "-i",
            "--rm",
            "-e",
            "GITLAB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITLAB_API_URL",
            "-e",
            "GITLAB_READ_ONLY_MODE",
            "-e",
            "USE_GITLAB_WIKI",
            "-e",
            "USE_MILESTONE",
            "-e",
            "USE_PIPELINE",
            "zereight050/gitlab-mcp",
        ]
        self.env = {
            "GITLAB_PERSONAL_ACCESS_TOKEN": (settings.gitlab_personal_access_token),
            "GITLAB_API_URL": settings.gitlab_api_url,
            "GITLAB_READ_ONLY_MODE": "false",
            "USE_GITLAB_WIKI": "true",
            "USE_MILESTONE": "true",
            "USE_PIPELINE": "true",
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
