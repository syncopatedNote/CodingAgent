from typing import Optional, Union
from settings import settings
from langchain_community.llms.ollama import Ollama
from langchain_community.llms.bedrock import Bedrock
from langchain_community.chat_models import BedrockChat
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
    ) -> Union[Ollama, ChatOllama, Bedrock, BedrockChat, ChatOpenAI]:
        """
        Create and return an LLM instance based on the provider and model.

        Args:
            provider (str): The LLM provider ('ollama' or 'bedrock')
            model_name (str): Name of the model to use
            model_type (str): Type of model interface ('completion' or 'chat')
            temperature (float): Temperature for response generation
            max_tokens (int, optional): Maximum tokens in the response
            **kwargs: Additional arguments for specific providers

        Returns:
            Union[Ollama, ChatOllama, Bedrock, BedrockChat]: Configured
            LLM instance
        """
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
                if model_type.lower() == "chat":
                    return LLMFactory._create_bedrock(
                        model_name=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model_type="chat",
                        **kwargs,
                    )
                else:
                    return LLMFactory._create_bedrock(
                        model_name=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model_type="completion",
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
    ) -> Union[ChatOllama, ChatOpenAI]:
        """
        Create a ChatOpenAI instance for litellm.
        Supports:
        - ollama/* for local Ollama models
        - github/* for GitHub Copilot models
        - Direct OpenAI models (gpt-4, gpt-3.5-turbo, etc.)
        """
        # GitHub Copilot models via OpenAI-compatible API
        actual_model = model_name.replace("github/", "")

        # Get GitHub token from environment or kwargs
        github_token = settings.github_token
        if not github_token:
            raise ValueError(
                "GITHUB_TOKEN not found. Set it in .env file or pass "
                "as github_token kwarg."
            )

        openai_kwargs = {
            "base_url": ("https://models.inference.ai.azure.com"),
            "api_key": github_token,
        }

        # Add max_tokens if provided
        if max_tokens:
            openai_kwargs["max_completion_tokens"] = max_tokens

        logger.info(f"Using GitHub model: {actual_model}")
        return ChatOpenAI(model=actual_model, temperature=temperature, **openai_kwargs)

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
        model_type: str = "completion",
        **kwargs,
    ) -> Union[Bedrock, BedrockChat]:
        """Create a Bedrock instance"""
        import boto3

        model_id_mapping = {
            "claude3": {
                "model_id": "anthropic.claude-3-sonnet-20240229-v1:0",
                "anthropic_version": "bedrock-2023-05-31",
            },
            "claude2": {
                "model_id": "anthropic.claude-v2",
                "anthropic_version": "bedrock-2023-05-31",
            },
            "claude-instant": {
                "model_id": "anthropic.claude-instant-v1",
                "anthropic_version": "bedrock-2023-05-31",
            },
            "titan": {"model_id": "amazon.titan-text-express-v1"},
            "llama2": {"model_id": "meta.llama2-70b-chat-v1"},
        }

        model_config = model_id_mapping.get(model_name.lower())
        if model_config:
            model_id = model_config["model_id"]
            anthropic_version = model_config.get("anthropic_version")
        else:
            model_id = model_name
            # Detect if it's an anthropic model by checking the model_id
            anthropic_version = (
                "bedrock-2023-05-31" if "anthropic" in model_name.lower() else None
            )
        region_name = kwargs.get("region_name", "us-east-1")

        # Create boto3 client for Bedrock
        session_kwargs = {}
        if kwargs.get("profile_name"):
            session_kwargs["profile_name"] = kwargs.get("profile_name")

        session = boto3.Session(**session_kwargs)
        client = session.client(service_name="bedrock-runtime", region_name=region_name)

        model_kwargs = {
            "temperature": temperature,
        }

        # Only add max_tokens if provided
        if max_tokens:
            model_kwargs["max_tokens"] = max_tokens

        if anthropic_version and model_type == "chat":
            return BedrockChat(
                client=client, model_id=model_id, model_kwargs=model_kwargs
            )
        else:
            return Bedrock(client=client, model_id=model_id, model_kwargs=model_kwargs)
