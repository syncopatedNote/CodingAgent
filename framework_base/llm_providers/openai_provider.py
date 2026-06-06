from typing import Optional

from langchain_openai import ChatOpenAI
from settings import settings


def create_openai(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> ChatOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not set.")

    openai_kwargs: dict = {
        "model": model_name,
        "temperature": temperature,
        "api_key": settings.openai_api_key,
    }
    if max_tokens:
        openai_kwargs["max_completion_tokens"] = max_tokens

    return ChatOpenAI(**openai_kwargs)
