from typing import Optional

from langchain_openai import AzureChatOpenAI
from settings import settings


def create_azure(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> AzureChatOpenAI:
    # Prefer settings-based configuration, fall back to kwargs
    api_key = kwargs.get("api_key") or settings.azure_openai_api_key
    endpoint = kwargs.get("endpoint") or settings.azure_openai_endpoint
    deployment = kwargs.get("azure_deployment") or settings.azure_openai_deployment
    api_version = kwargs.get("api_version") or settings.azure_openai_api_version

    if not deployment:
        raise ValueError(
            "azure deployment name must be provided via settings or kwargs"
        )

    azure_kwargs: dict = {
        "model": model_name,
        "azure_deployment": deployment,
        "temperature": temperature,
    }

    if api_key:
        azure_kwargs["api_key"] = api_key
    if endpoint:
        azure_kwargs["azure_endpoint"] = endpoint
    if api_version:
        # different versions expect either api_version or openai_api_version
        azure_kwargs["api_version"] = api_version
    if max_tokens:
        azure_kwargs["max_tokens"] = max_tokens

    return AzureChatOpenAI(**azure_kwargs)
