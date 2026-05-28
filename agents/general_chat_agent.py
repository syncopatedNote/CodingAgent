#!/usr/bin/env python3
"""
General Chat Agent
Handles general-purpose queries by enriching the LLM response with
relevant context retrieved from the ChromaDB knowledge base (RAG).
Falls back to a direct LLM answer when the knowledge base is
unavailable or returns no results.
"""

from langchain_core.messages import HumanMessage
from framework_base.llm_base import LLMFactory
from framework_base.vector_store import get_vector_store
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)

# Collection name used by the RAG ingestion pipeline
_RAG_COLLECTION = "uploads"


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

    async def _retrieve_rag_context(self, query: str) -> str:
        """Query the knowledge base and return formatted context, or an
        empty string if nothing is found or the store is unavailable."""
        try:
            vectorstore = get_vector_store(collection_name=_RAG_COLLECTION)
            docs = await vectorstore.asimilarity_search(query, k=4)
            if docs:
                context_parts = [
                    f"[Document {i}]:\n{doc.page_content}"
                    for i, doc in enumerate(docs, 1)
                ]
                rag_context = "\n\n".join(context_parts)
                logger.info(
                    f"Retrieved {len(docs)} document(s) from knowledge "
                    "base for general chat"
                )
                return rag_context
        except Exception as rag_err:
            logger.warning(
                f"Knowledge base query skipped ({rag_err}). "
                "Proceeding without RAG context."
            )
        return ""

    def _build_prompt(self, query: str, rag_context: str) -> str:
        """Build the LLM prompt, injecting KB context when available."""
        if rag_context:
            return (
                "You are a helpful AI assistant. Use the relevant documents\n"
                "retrieved from the knowledge base below to answer the user's question.\n"
                "If the retrieved documents do not contain enough information, supplement\n"
                "with your general knowledge and say so.\n\n"
                f"**Relevant context from knowledge base:**\n{rag_context}\n\n"
                f"**User question:** {query}\n\n"
                "Provide a clear, accurate answer grounded in the context above.\n"
                "Cite which document(s) support your answer where applicable."
            )
        return (
            "You are a helpful AI assistant that specializes in:\n\n"
            "\U0001f50d **Search Operations:**\n"
            "- Finding Confluence documentation and pages\n"
            "- Looking up Jira tickets and issues\n"
            "- Searching for specific information across systems\n\n"
            "\U0001f4bb **Code Generation:**\n"
            "- Generating code from Jira ticket requirements\n"
            "- Following development standards and best practices\n"
            "- Integrating with GitLab for code management\n\n"
            f"User question: {query}\n\n"
            "Provide a helpful response. If the user wants to search for "
            "something or generate code, guide them on how to ask more specifically.\n\n"
            "Examples of what you can help with:\n"
            '- "Search for API documentation"\n'
            '- "Find ticket PROJ-123"\n'
            '- "Generate code for DEV-456"\n'
            '- "Look for confluence pages about deployment"'
        )

    async def chat(self, query: str) -> str:
        """
        Answer a general chat query, optionally enriched with RAG context.

        Args:
            query: The user's question or message.

        Returns:
            The LLM-generated response as a string.
        """
        rag_context = await self._retrieve_rag_context(query)
        prompt = self._build_prompt(query, rag_context)
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content
