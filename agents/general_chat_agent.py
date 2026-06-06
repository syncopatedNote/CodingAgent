#!/usr/bin/env python3
"""
General Chat Agent
Handles general-purpose conversational queries with a direct LLM call.
No RAG — for knowledge base search use KnowledgeBaseSearchAgent instead.
"""

from langchain_core.messages import HumanMessage
from framework_base.llm_base import LLMFactory
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)


class GeneralChatAgent:
    def __init__(self):
        """Initialize the general chat agent with an LLM."""
        llm_kwargs = {"temperature": 0.3}

        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

    def _build_prompt(self, query: str) -> str:
        return (
            "You are a helpful AI assistant. Answer the user's question\n"
            "clearly and concisely. Use Markdown formatting where helpful\n"
            "(lists, code fences, bold headings). Do not invent facts.\n\n"
            f"User question: {query}"
        )

    async def chat(self, query: str) -> str:
        """
        Answer a general chat query via a direct LLM call.

        Args:
            query: The user's question or message.

        Returns:
            The LLM-generated response as a string.
        """
        prompt = self._build_prompt(query)
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content
