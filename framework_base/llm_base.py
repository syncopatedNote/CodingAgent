from typing import Optional, Union
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
        **kwargs
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
            Union[Ollama, ChatOllama, Bedrock, BedrockChat]: Configured LLM instance
        """
        try:
            if provider.lower() == "ollama":
                if model_type.lower() == "chat":
                    return LLMFactory._create_ollama_chat(
                        model_name=model_name,
                        temperature=temperature,
                        **kwargs
                    )
                else:
                    return LLMFactory._create_ollama(
                        model_name=model_name,
                        temperature=temperature,
                        **kwargs
                    )

            elif provider.lower() == "bedrock":
                if model_type.lower() == "chat":
                    return LLMFactory._create_bedrock(
                        model_name=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model_type="chat",
                        **kwargs
                    )
                else:
                    return LLMFactory._create_bedrock(
                        model_name=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model_type="completion",
                        **kwargs
                    )
            elif provider.lower() == "litellm":
                return LLMFactory._create_litellm_chat(
                    model_name=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )

            else:
                raise ValueError(f"Unsupported provider: {provider}")

        except Exception as e:
            print(f"Failed to initialize Amazon Q LLM: {e}")
            raise e

    @staticmethod
    def _create_litellm_chat(
        model_name: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ChatOpenAI:
        """Create a ChatOpenAI instance for litellm"""
        return ChatOpenAI(
            model=model_name,
            openai_api_base="http://0.0.0.0:4000",
            openai_api_key="dummy-key",
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    @staticmethod
    def _create_ollama(
        model_name: str,
        temperature: float = 0.7,
        base_url: str = "http://localhost:11434",
        **kwargs
    ) -> Ollama:
        """Create an Ollama completion instance"""
        return Ollama(
            model=model_name,
            base_url=base_url,
            temperature=temperature,
            timeout=kwargs.get('timeout', 120)
        )

    @staticmethod
    def _create_ollama_chat(
        model_name: str,
        temperature: float = 0.7,
        base_url: str = "http://localhost:11434",
        **kwargs
    ) -> ChatOllama:
        """Create an Ollama chat instance"""
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=temperature,
            timeout=kwargs.get('timeout', 120),
            streaming=kwargs.get('streaming', False)
        )

    @staticmethod
    def _create_bedrock(
        model_name: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_type: str = "completion",
        **kwargs
    ) -> Union[Bedrock, BedrockChat]:
        """Create a Bedrock instance"""

        model_id_mapping = {
            "claude3": "anthropic.claude-3-sonnet-20240229-v1:0",
            "claude2": "anthropic.claude-v2",
            "claude-instant": "anthropic.claude-instant-v1",
            "titan": "amazon.titan-text-express-v1",
            "llama2": "meta.llama2-70b-chat-v1"
        }

        model_id = model_id_mapping.get(model_name.lower(), model_name)

        model_kwargs = {
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if "anthropic" in model_id and model_type == "chat":
            model_kwargs["anthropic_version"] = "bedrock-2023-05-31"
            return BedrockChat(
                model_id=model_id,
                model_kwargs=model_kwargs,
                region_name=kwargs.get('region_name', 'us-east-1'),
                credentials_profile_name=kwargs.get('profile_name')
            )
        else:
            return Bedrock(
                model_id=model_id,
                model_kwargs=model_kwargs,
                region_name=kwargs.get('region_name', 'us-east-1'),
                credentials_profile_name=kwargs.get('profile_name')
            )

