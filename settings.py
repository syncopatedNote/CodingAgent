from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Settings loaded from environment variables and .env file."""

    mcp_very_verbose: str = Field(default="true", alias="MCP_VERY_VERBOSE")
    confluence_url: str = Field(default="", alias="CONFLUENCE_URL")
    confluence_username: str = Field(default="", alias="CONFLUENCE_USERNAME")
    confluence_api_token: str = Field(default="", alias="CONFLUENCE_API_TOKEN")
    confluence_ssl_verify: str = Field(default="false", alias="CONFLUENCE_SSL_VERIFY")
    jira_url: str = Field(default="", alias="JIRA_URL")
    jira_personal_token: str = Field(default="", alias="JIRA_PERSONAL_TOKEN")
    jira_ssl_verify: str = Field(default="false", alias="JIRA_SSL_VERIFY")
    gitlab_personal_access_token: str = Field(
        default="", alias="GITLAB_PERSONAL_ACCESS_TOKEN"
    )
    gitlab_api_url: str = Field(default="", alias="GITLAB_API_URL")
    gitlab_project_id: str = Field(default="", alias="GITLAB_PROJECT_ID")
    development_rules_path: str = Field(default="", alias="DEVELOPMENT_RULES_PATH")
    development_rules_branch: str = Field(default="", alias="DEVELOPMENT_RULES_BRANCH")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # LLM Configuration
    llm_provider: str = Field(default="litellm", alias="LLM_PROVIDER")
    llm_model_name: str = Field(default="gpt-4o-mini", alias="LLM_MODEL_NAME")
    llm_model_type: str = Field(default="chat", alias="LLM_MODEL_TYPE")

    # AWS Configuration
    aws_access_key_id: str = Field(default="", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # LiteLLM Proxy Configuration
    litellm_proxy_url: str = Field(
        default="http://litellm:4000", alias="LITELLM_PROXY_URL"
    )
    litellm_master_key: str = Field(default="sk-1234", alias="LITELLM_MASTER_KEY")

    # Ollama Configuration
    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )

    # Chroma (vector DB) Configuration (hosted service only)
    chroma_server_host: str = Field(default="", alias="CHROMA_SERVER_HOST")
    chroma_server_http_port: int = Field(default=0, alias="CHROMA_SERVER_HTTP_PORT")

    # Embedding model configuration (local HuggingFace)
    hf_embed_model: str = Field(
        default="sentence-transformers/all-mpnet-base-v2", alias="HF_EMBED_MODEL"
    )
    embed_device: str = Field(default="cpu", alias="EMBED_DEVICE")

    # MCP Server URLs (for Docker Compose / SSE transport)
    mcp_atlassian_url: str = Field(default="", alias="MCP_ATLASSIAN_URL")
    mcp_gitlab_url: str = Field(default="", alias="MCP_GITLAB_URL")
    mcp_github_url: str = Field(default="", alias="MCP_GITHUB_URL")
    mcp_context7_url: str = Field(default="", alias="MCP_CONTEXT7_URL")

    # MCP Server Enable Flags
    mcp_atlassian_enabled: bool = Field(default=True, alias="MCP_ATLASSIAN_ENABLED")
    mcp_gitlab_enabled: bool = Field(default=True, alias="MCP_GITLAB_ENABLED")
    mcp_github_enabled: bool = Field(default=True, alias="MCP_GITHUB_ENABLED")
    mcp_context7_enabled: bool = Field(default=True, alias="MCP_CONTEXT7_ENABLED")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


# Global settings instance
settings = Settings()
