from typing import Optional

from langchain_openai import ChatOpenAI
from settings import settings

_BASE_URL = "https://openrouter.ai/api/v1"


def create_openrouter(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> ChatOpenAI:
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY not set.")

    openai_kwargs: dict = {
        "model": model_name,
        "temperature": temperature,
        "base_url": _BASE_URL,
        "api_key": settings.openrouter_api_key,
    }
    if max_tokens:
        openai_kwargs["max_completion_tokens"] = max_tokens

    return ChatOpenAI(**openai_kwargs)
