from typing import Optional

import boto3
from langchain_aws import ChatBedrockConverse
from settings import settings


def create_bedrock(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> ChatBedrockConverse:
    region_name = kwargs.get("region_name") or settings.aws_region

    session_kwargs = {}
    if kwargs.get("profile_name"):
        session_kwargs["profile_name"] = kwargs["profile_name"]
    if settings.aws_access_key_id:
        session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    session = boto3.Session(**session_kwargs)
    client = session.client(service_name="bedrock-runtime", region_name=region_name)

    converse_kwargs: dict = {
        "client": client,
        "model": model_name,
        "temperature": temperature,
    }
    if max_tokens:
        converse_kwargs["max_tokens"] = max_tokens

    return ChatBedrockConverse(**converse_kwargs)
