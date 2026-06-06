from typing import Optional, Union

from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_community.llms.ollama import Ollama
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

try:
    from langchain_openai import AzureChatOpenAI
except Exception:
    AzureChatOpenAI = None
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None
from logger import setup_logger

from framework_base.llm_providers.anthropic_provider import create_anthropic
from framework_base.llm_providers.bedrock_provider import create_bedrock
from framework_base.llm_providers.litellm_provider import create_litellm_chat
from framework_base.llm_providers.ollama_provider import (
    create_ollama,
    create_ollama_chat,
)
from framework_base.llm_providers.openai_provider import create_openai
from framework_base.llm_providers.openrouter_provider import create_openrouter
from framework_base.llm_providers.azure_provider import create_azure
from framework_base.llm_providers.gcp_provider import create_gcp

logger = setup_logger()

LLMInstance = Union[
    Ollama,
    ChatOllama,
    ChatBedrockConverse,
    ChatOpenAI,
    ChatAnthropic,
    (AzureChatOpenAI if AzureChatOpenAI is not None else object),
    (ChatGoogleGenerativeAI if ChatGoogleGenerativeAI is not None else object),
]


class LLMFactory:

    @staticmethod
    def create_llm(
        provider: str,
        model_name: str,
        model_type: str = "chat",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMInstance:
        try:
            p = provider.lower()

            def _ollama_factory(name, temp, max_t, **kwargs):
                if model_type.lower() == "chat":
                    return create_ollama_chat(name, temp, **kwargs)
                return create_ollama(name, temp, **kwargs)

            providers_map = {
                "ollama": _ollama_factory,
                "bedrock": create_bedrock,
                "litellm": create_litellm_chat,
                "anthropic": create_anthropic,
                "openai": create_openai,
                "openrouter": create_openrouter,
                "azure": create_azure,
                "gcp": create_gcp,
                "google": create_gcp,
            }

            factory = providers_map.get(p)
            if not factory:
                raise ValueError(f"Unsupported provider: {provider}")
            return factory(model_name, temperature, max_tokens, **kwargs)
        except Exception as e:
            logger.error(f"Failed to initialize {provider} LLM: {e}")
            raise
