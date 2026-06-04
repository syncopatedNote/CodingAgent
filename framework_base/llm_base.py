from typing import Optional, Union
from settings import settings
from langchain_community.llms.ollama import Ollama
from langchain_aws import ChatBedrockConverse
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from logger import setup_logger

logger = setup_logger()


class LLMFactory:
    """Factory class to create different types of LLM instances"""

    @staticmethod
    def create_llm(
        provider: str,
        model_name: str,
        model_type: str = "completion",  # "completion" or "chat"
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Union[Ollama, ChatOllama, ChatBedrockConverse, ChatOpenAI]:
        try:
            if provider.lower() == "ollama":
                if model_type.lower() == "chat":
                    return LLMFactory._create_ollama_chat(
                        model_name=model_name, temperature=temperature, **kwargs
                    )
                else:
                    return LLMFactory._create_ollama(
                        model_name=model_name, temperature=temperature, **kwargs
                    )

            elif provider.lower() == "bedrock":
                return LLMFactory._create_bedrock(
                    model_name=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            elif provider.lower() == "litellm":
                return LLMFactory._create_litellm_chat(
                    model_name=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            else:
                raise ValueError(f"Unsupported provider: {provider}")

        except Exception as e:
            print(f"Failed to initialize {provider} LLM: {e}")
            raise e

    @staticmethod
    def _create_litellm_chat(
        model_name: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ChatOpenAI:
        """
        Create a ChatOpenAI instance routed through the LiteLLM proxy.

        The LiteLLM proxy handles model routing, API key management,
        and provider translation.  The model_name here corresponds
        to a model_name entry in litellm_config.yaml.
        """
        proxy_url = settings.litellm_proxy_url
        proxy_key = settings.litellm_master_key

        if not proxy_url:
            raise ValueError(
                "LITELLM_PROXY_URL not set. Configure it in .env "
                "or docker-compose.yml."
            )

        # Strip any provider prefix — LiteLLM uses its own
        # model_name aliases defined in litellm_config.yaml
        actual_model = model_name.replace("github/", "")

        openai_kwargs: dict = {
            "base_url": f"{proxy_url.rstrip('/')}/v1",
            "api_key": proxy_key or "not-needed",
        }

        if max_tokens:
            openai_kwargs["max_completion_tokens"] = max_tokens

        logger.info(f"Using LiteLLM proxy model: {actual_model} " f"via {proxy_url}")
        return ChatOpenAI(
            model=actual_model,
            temperature=temperature,
            **openai_kwargs,
        )

    @staticmethod
    def _create_ollama(
        model_name: str,
        temperature: float = 0.7,
        base_url: str = "http://localhost:11434",
        **kwargs,
    ) -> Ollama:
        """Create an Ollama completion instance"""
        return Ollama(model=model_name, base_url=base_url, temperature=temperature)

    @staticmethod
    def _create_ollama_chat(
        model_name: str,
        temperature: float = 0.7,
        base_url: str = "http://localhost:11434",
        **kwargs,
    ) -> ChatOllama:
        """Create an Ollama chat instance"""
        return ChatOllama(model=model_name, base_url=base_url, temperature=temperature)

    @staticmethod
    def _create_bedrock(
        model_name: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ChatBedrockConverse:
        """Create a Bedrock instance using the Converse API (supports all models)"""
        import boto3

        region_name = kwargs.get("region_name") or settings.aws_region

        session_kwargs = {}
        if kwargs.get("profile_name"):
            session_kwargs["profile_name"] = kwargs.get("profile_name")
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
