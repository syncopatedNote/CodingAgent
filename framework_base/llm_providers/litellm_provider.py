from typing import Optional

from langchain_openai import ChatOpenAI
from logger import setup_logger
from settings import settings

logger = setup_logger(__name__)


def create_litellm_chat(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> ChatOpenAI:
    proxy_url = settings.litellm_proxy_url
    proxy_key = settings.litellm_master_key

    if not proxy_url:
        raise ValueError(
            "LITELLM_PROXY_URL not set. Configure it in .env or docker-compose.yml."
        )

    actual_model = model_name.replace("github/", "")
    openai_kwargs: dict = {
        "base_url": f"{proxy_url.rstrip('/')}/v1",
        "api_key": proxy_key or "not-needed",
    }
    if max_tokens:
        openai_kwargs["max_completion_tokens"] = max_tokens

    logger.info(f"Using LiteLLM proxy model: {actual_model} via {proxy_url}")
    return ChatOpenAI(model=actual_model, temperature=temperature, **openai_kwargs)
