from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
from settings import settings

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
        },
        "context7": {
            "command": "npx",
            "transport": "stdio",
            "args": [
                "-y",
                "@upstash/context7-mcp"
            ],
            "env": {
                "NODE_TLS_REJECT_UNAUTHORIZED": "0"
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
