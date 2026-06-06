from langchain_community.llms.ollama import Ollama
from langchain_ollama import ChatOllama


def create_ollama(
    model_name: str,
    temperature: float = 0.7,
    base_url: str = "http://localhost:11434",
    **kwargs,
) -> Ollama:
    return Ollama(model=model_name, base_url=base_url, temperature=temperature)


def create_ollama_chat(
    model_name: str,
    temperature: float = 0.7,
    base_url: str = "http://localhost:11434",
    **kwargs,
) -> ChatOllama:
    return ChatOllama(model=model_name, base_url=base_url, temperature=temperature)
