from typing import Optional

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
    # LLM providers info
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    # Azure OpenAI Configuration
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str = Field(default="", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="", alias="AZURE_OPENAI_API_VERSION")
    # Google / GCP Configuration
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gcp_project: str = Field(default="", alias="GCP_PROJECT")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # LLM Configuration
    llm_provider: str = Field(default="litellm", alias="LLM_PROVIDER")
    llm_model_name: str = Field(default="gpt-4o-mini", alias="LLM_MODEL_NAME")
    llm_model_type: str = Field(default="chat", alias="LLM_MODEL_TYPE")

    # Reranker Configuration
    reranker_provider: str = Field(default="flashrank", alias="RERANKER_PROVIDER")
    reranker_top_n: int = Field(default=5, alias="RERANKER_TOP_N")

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

    # PostgreSQL docstore + pgvector store
    postgres_dsn: str = Field(alias="POSTGRES_DSN")

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

    # Sprint Start Agent
    jira_webhook_secret: str = Field(default="", alias="JIRA_WEBHOOK_SECRET")
    sprint_start_max_concurrent: int = Field(
        default=1, alias="SPRINT_START_MAX_CONCURRENT"
    )

    # Coding pipeline (context collector + coding agent)
    # Branch the coding agent bases its work on, and the branch the development
    # guidelines file is read from.
    coding_base_branch: str = Field(default="main", alias="CODING_BASE_BRANCH")
    # Filename of the mandatory development-guidelines file in the repo root.
    coding_guidelines_filename: str = Field(
        default="robots.md", alias="CODING_GUIDELINES_FILENAME"
    )
    # Repository owner / org. Mandatory — GitHub MCP push tools fail without it.
    # The pipeline refuses to run when this is unset.
    coding_repository_owner: Optional[str] = Field(
        default=None, alias="CODING_REPOSITORY_OWNER"
    )
    # Which coding agent the pipeline uses: "supervisor" (the improvised
    # hub-and-spoke LangGraphCodingAgent) or "deterministic" (the explicit
    # explore → plan → per-file generate/review → push DeterministicCodingAgent).
    coding_agent_mode: str = Field(default="supervisor", alias="CODING_AGENT_MODE")
    # Max generate→review cycles per file in the deterministic agent. The loop
    # exits early when the reviewer returns approved=true, so this is a ceiling,
    # not a fixed count. On hitting the ceiling the file is staged with a
    # warning carrying any unresolved blocking issues.
    coding_max_review_cycles: int = Field(default=3, alias="CODING_MAX_REVIEW_CYCLES")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


# Global settings instance
settings = Settings()
