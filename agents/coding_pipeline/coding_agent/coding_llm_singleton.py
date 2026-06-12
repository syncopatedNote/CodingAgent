from typing import Any

from framework_base.llm_base import LLMFactory
from settings import settings


def _create_code_llm():
    """Build an LLM instance tuned for code-generation tasks (lower temperature)."""
    kwargs: dict[str, Any] = {"temperature": 0.3}
    if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
        kwargs["base_url"] = settings.ollama_base_url
    return LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        **kwargs,
    )


# Module-level singleton — created once at import time, shared across all
# generate_code / review_code tool calls in the process.
code_llm = _create_code_llm()
