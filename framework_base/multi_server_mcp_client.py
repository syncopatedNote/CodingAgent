from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
import os
from settings import settings

# MCP servers run as persistent services accessible via SSE (Server-Sent Events)
# over HTTP. This allows proper service-based architecture in Docker Compose.

# Check if MCP_ATLASSIAN_URL is set (Docker Compose) vs local development
USE_SSE_TRANSPORT = hasattr(settings, 'mcp_atlassian_url') and settings.mcp_atlassian_url

if USE_SSE_TRANSPORT:
    # Docker Compose: Connect to persistent MCP services via SSE/HTTP
    multi_server_mcp_client = MultiServerMCPClient(
        {
            "atlassian": {
                "url": f"{settings.mcp_atlassian_url}/sse",  # Add /sse endpoint
                "transport": "sse"
            },
            "gitlab": {
                "url": f"{settings.mcp_gitlab_url}/sse",  # Add /sse endpoint
                "transport": "sse"
            }
        }
    )
else:
    # Local development: Launch Docker containers on-demand with stdio
    multi_server_mcp_client = MultiServerMCPClient(
        {
            "atlassian": {
                "command": "docker",
                "args": [
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
                    "JIRA_PERSONAL_TOKEN",
                    "-e",
                    "JIRA_SSL_VERIFY",
                    "-e",
                    "MCP_VERY_VERBOSE",
                    "ghcr.io/sooperset/mcp-atlassian:latest"
                ],
                "transport": "stdio",
                "env": {
                    "MCP_VERY_VERBOSE": settings.mcp_very_verbose,
                    "CONFLUENCE_URL": settings.confluence_url,
                    "CONFLUENCE_USERNAME": settings.confluence_username,
                    "CONFLUENCE_API_TOKEN": settings.confluence_api_token,
                    "CONFLUENCE_SSL_VERIFY": settings.confluence_ssl_verify,
                    "JIRA_URL": settings.jira_url,
                    "JIRA_PERSONAL_TOKEN": settings.jira_personal_token,
                    "JIRA_SSL_VERIFY": settings.jira_ssl_verify
                }
            },
            "gitlab": {
                "command": "docker",
                "transport": "stdio",
                "args": [
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    "NODE_TLS_REJECT_UNAUTHORIZED",
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
                    "iwakitakuma/gitlab-mcp"
                ],
                "env": {
                    "NODE_TLS_REJECT_UNAUTHORIZED": "0",
                    "GITLAB_PERSONAL_ACCESS_TOKEN": settings.gitlab_personal_access_token,
                    "GITLAB_API_URL": settings.gitlab_api_url,
                    "GITLAB_READ_ONLY_MODE": "false",
                    "USE_GITLAB_WIKI": "true",
                    "USE_MILESTONE": "true",
                    "USE_PIPELINE": "true"
                }
            }
        }
    )


if __name__ == '__main__':
    async def main():
        tools = await multi_server_mcp_client.get_tools()
        return tools
    tools = asyncio.run(main())
    print(f"client_initialized: {tools}")
