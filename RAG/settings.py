from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Always read from the root .env — one source of truth for all services.
_ENV_FILE = Path(__file__).parent.parent / ".env"


class RagSettings(BaseSettings):
    """Settings for the RAG upload service. Loaded from the root .env file."""

    aws_access_key_id: str = Field(alias="RAG_AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(alias="RAG_AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", alias="RAG_AWS_REGION")
    s3_bucket_name: str = Field(alias="S3_BUCKET_NAME")
    presigned_url_expiry_seconds: int = Field(
        default=300, alias="PRESIGNED_URL_EXPIRY_SECONDS"
    )

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}


rag_settings = RagSettings()
