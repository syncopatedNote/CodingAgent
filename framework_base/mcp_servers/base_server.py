"""
Base MCP Server Configuration
Defines the structure for MCP server configurations.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel, ABC):
    """
    Configuration for an MCP server supporting both streamable HTTP
    and stdio transports
    """

    name: str = Field(default="", description="Unique identifier for the server")
    enabled: bool = Field(default=True, description="Whether server is enabled")
    description: Optional[str] = Field(
        default=None, description="Human-readable description"
    )
    # Streamable HTTP Transport Configuration (Docker Compose mode)
    http_url: Optional[str] = Field(
        default=None, description="URL for streamable HTTP transport"
    )
    http_port: Optional[int] = Field(
        default=None, description="Port for streamable HTTP transport"
    )
    # stdio Transport Configuration (Local development mode)
    command: Optional[str] = Field(
        None, description="Command to execute (e.g., 'npx', 'docker')"
    )
    args: Optional[List[str]] = Field(
        default_factory=list, description="Arguments for the command"
    )
    env: Optional[Dict[str, str]] = Field(
        None, description="Environment variables for stdio transport"
    )

    class Config:
        extra = "allow"  # Allow additional fields for flexibility

    @abstractmethod
    def get_active_server_config(self) -> Dict:
        """
        Get the appropriate server configuration based on
        available transport
        """
        pass

    def get_streamable_http_config(self) -> Dict:
        """Get configuration for streamable HTTP transport"""
        url = ""
        if not self.http_url:
            raise ValueError(f"Streamable HTTP not supported for server: {self.name}")
        if self.http_port:
            url = self.http_url + f":{self.http_port}"
        else:
            url = self.http_url
        if not url:
            raise Exception("Not able to set http url for streamable http config")
        return {"url": f"{url}/mcp", "transport": "streamable_http"}

    def get_stdio_config(self) -> Dict:
        """Get configuration for stdio transport"""
        if not self.command:
            raise ValueError(f"Command not configured for server: {self.name}")

        config = {"command": self.command, "transport": "stdio"}

        if self.args:
            config["args"] = self.args  # type: ignore

        if self.env:
            config["env"] = self.env  # type: ignore
        return config

    def is_available(self) -> bool:
        """Check if server has minimum required configuration"""
        return bool(self.enabled and (self.http_url or self.command))
