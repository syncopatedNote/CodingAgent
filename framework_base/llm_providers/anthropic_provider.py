from typing import Optional

from langchain_anthropic import ChatAnthropic
from settings import settings


def create_anthropic(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> ChatAnthropic:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set.")

    anthropic_kwargs: dict = {
        "model": model_name,
        "temperature": temperature,
        "api_key": settings.anthropic_api_key,
    }
    if max_tokens:
        anthropic_kwargs["max_tokens"] = max_tokens

    return ChatAnthropic(**anthropic_kwargs)
