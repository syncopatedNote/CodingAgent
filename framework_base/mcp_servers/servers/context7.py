"""
Context7 MCP Server Configuration
Provides access to up-to-date library and framework documentation.
"""

from typing import Dict
from ..base_server import MCPServerConfig
from settings import settings


class Context7McpServerConfig(MCPServerConfig):
    """Context7 MCP Server Configuration for library documentation lookup"""

    def __init__(self, **data):
        super().__init__(**data)
        self.name = "context7"
        self.enabled = getattr(settings, "mcp_context7_enabled", True)
        self.description = (
            "Context7 MCP server for up-to-date library "
            "and framework documentation lookup"
        )
        self.http_url = getattr(settings, "mcp_context7_url", "")
        # stdio Transport (Local dev via npx)
        self.command = "npx"
        self.args = ["-y", "@upstash/context7-mcp"]
        self.env = {}

    def get_active_server_config(self) -> Dict:
        """
        Get the appropriate server configuration based
        on available transport.
        Prefers streamable HTTP when URL is configured (Docker),
        falls back to stdio for local dev.
        """
        if self.http_url:
            return self.get_streamable_http_config()
        else:
            return self.get_stdio_config()
