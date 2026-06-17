#!/usr/bin/env python3
"""
Knowledge Base Search Agent
Answers user queries by retrieving relevant context from the pgvector
knowledge base (RAG) and grounding the LLM response in those documents.
"""

from typing import Iterator, List, Optional, Sequence

from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.stores import BaseStore
from framework_base.doc_store import PostgresDocStore, get_document_store
from agents.prompts.kb_search.search_prompts import (
    KB_SEARCH_WITH_CONTEXT_PROMPT,
    KB_SEARCH_NO_CONTEXT_PROMPT,
)
from framework_base.llm_base import LLMFactory
from framework_base.reranker import RerankerFactory
from framework_base.vector_store import get_vector_store
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)

# Must match the constants in RAG/loaders/pdf_loader.py
_RAG_COLLECTION = "uploads"
_ID_KEY = "doc_id"

# Fetch more candidates than needed so the reranker has headroom after
# MultiVectorRetriever deduplicates multiple vectors per source chunk.
_VECTOR_FETCH_K = 20


class _DocStoreAdapter(BaseStore[str, Document]):
    """Adapts PostgresDocStore (plain dicts) to BaseStore[str, Document].

    MultiVectorRetriever requires BaseStore[str, Document]. The ingest
    pipeline stores raw dicts so that table HTML and page numbers survive
    JSON round-trips. This adapter converts those dicts to Document objects
    on retrieval, placing type and page metadata in Document.metadata.
    """

    def __init__(self, inner: PostgresDocStore) -> None:
        self._inner = inner

    def mget(self, keys: Sequence[str]) -> List[Optional[Document]]:
        results: List[Optional[Document]] = []
        for raw in self._inner.mget(keys):
            if raw is None:
                results.append(None)
                continue
            doc_type = raw.get("type", "text")
            content = (
                raw.get("html", "") if doc_type == "table" else raw.get("content", "")
            )
            metadata = {"type": doc_type}
            if raw.get("page") is not None:
                metadata["page"] = raw["page"]
            if raw.get("document_name") is not None:
                metadata["document_name"] = raw["document_name"]
            results.append(Document(page_content=content, metadata=metadata))
        return results

    def mset(self, _: Sequence[tuple[str, Document]]) -> None:
        raise NotImplementedError("_DocStoreAdapter is read-only")

    def mdelete(self, keys: Sequence[str]) -> None:
        self._inner.mdelete(keys)

    def yield_keys(self, prefix: Optional[str] = None) -> Iterator[str]:
        return self._inner.yield_keys(prefix)


class KnowledgeBaseSearchAgent:
    def __init__(self):
        """Initialize the knowledge base search agent with an LLM."""
        llm_kwargs = {"temperature": 0.3}

        is_ollama = settings.llm_provider.lower() == "ollama"
        if is_ollama and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

    async def _retrieve_rag_context(self, query: str) -> str:
        """Retrieve and rerank relevant chunks from the knowledge base.

        Pipeline:
          1. MultiVectorRetriever fetches _VECTOR_FETCH_K vector candidates
             from ChromaDB (summaries / HyDE questions / search queries),
             deduplicates by doc_id, and returns the original source chunks
             from PostgreSQL.
          2. ContextualCompressionRetriever passes those candidates to the
             configured reranker, which scores each (query, chunk) pair and
             returns the top_n most relevant chunks.

        Returns a formatted context string, or an empty string when nothing
        is found or the store is unavailable.
        """
        try:
            vectorstore = get_vector_store(
                collection_name=_RAG_COLLECTION, async_mode=True
            )
            docstore = _DocStoreAdapter(get_document_store())
            base_retriever = MultiVectorRetriever(
                vectorstore=vectorstore,
                docstore=docstore,
                id_key=_ID_KEY,
                search_kwargs={"k": _VECTOR_FETCH_K},
            )
            retriever = ContextualCompressionRetriever(
                base_compressor=RerankerFactory.create_reranker(),
                base_retriever=base_retriever,
            )
            docs = await retriever.ainvoke(query)
            if docs:
                context_parts = []
                for doc in docs:
                    doc_name = doc.metadata.get("document_name", "unknown")
                    page = doc.metadata.get("page")
                    page_str = f", page {page + 1}" if page is not None else ""
                    if doc.metadata.get("type") == "table":
                        label = f"[Table from {doc_name}{page_str}]"
                    else:
                        label = f"[{doc_name}{page_str}]"
                    context_parts.append(f"{label}:\n{doc.page_content}")
                rag_context = "\n\n".join(context_parts)
                logger.info(
                    f"Retrieved {len(docs)} document(s) from knowledge base"
                    " after reranking"
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
            return KB_SEARCH_WITH_CONTEXT_PROMPT.format(
                rag_context=rag_context, query=query
            )
        return KB_SEARCH_NO_CONTEXT_PROMPT.format(query=query)

    async def search(self, query: str) -> str:
        """Search the knowledge base and return a grounded answer.

        Args:
            query: The user's question or search query.

        Returns:
            The LLM-generated response grounded in retrieved documents.
        """
        rag_context = await self._retrieve_rag_context(query)
        prompt = self._build_prompt(query, rag_context)
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content
