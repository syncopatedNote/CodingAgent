#!/usr/bin/env python3
"""
Knowledge Base Search Agent
Answers user queries by retrieving relevant context from the ChromaDB
knowledge base (RAG) and grounding the LLM response in those documents.
"""

from typing import Iterator, List, Optional, Sequence

from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.stores import BaseStore
from framework_base.doc_store import RedisDocStore, get_document_store
from framework_base.llm_base import LLMFactory
from framework_base.vector_store import get_vector_store
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)

# Must match the constants in RAG/loaders/pdf_loader.py
_RAG_COLLECTION = "uploads"
_ID_KEY = "doc_id"


class _DocStoreAdapter(BaseStore[str, Document]):
    """Adapts RedisDocStore (stores plain dicts) to BaseStore[str, Document].

    MultiVectorRetriever requires BaseStore[str, Document]. The ingest pipeline
    stores raw dicts so that table HTML and page numbers survive JSON round-trips.
    This adapter converts those dicts to Document objects on retrieval, placing
    type and page metadata in Document.metadata for use in context formatting.
    """

    def __init__(self, inner: RedisDocStore) -> None:
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

        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

    async def _retrieve_rag_context(self, query: str) -> str:
        """Query the knowledge base via MultiVectorRetriever and return
        formatted original document snippets, or an empty string if nothing
        is found or the store is unavailable.

        The vector store holds LLM-generated summaries; the docstore holds
        the original chunks. MultiVectorRetriever does the two-step lookup
        so the LLM receives full source content, not summaries.
        """
        try:
            vectorstore = get_vector_store(collection_name=_RAG_COLLECTION)
            docstore = _DocStoreAdapter(get_document_store())
            retriever = MultiVectorRetriever(
                vectorstore=vectorstore,
                docstore=docstore,
                id_key=_ID_KEY,
                search_kwargs={"k": 5},
            )
            docs = await retriever.ainvoke(query)
            if docs:
                context_parts = []
                for i, doc in enumerate(docs, 1):
                    if doc.metadata.get("type") == "table":
                        label = f"[Table {i}]"
                    else:
                        page = doc.metadata.get("page")
                        label = (
                            f"[Document {i}" + (f", page {page}" if page else "") + "]"
                        )
                    context_parts.append(f"{label}:\n{doc.page_content}")
                rag_context = "\n\n".join(context_parts)
                logger.info(f"Retrieved {len(docs)} document(s) from knowledge base")
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
            "You are a helpful AI assistant with access to a knowledge base.\n"
            "No relevant documents were found in the knowledge base for this query.\n\n"
            f"**User question:** {query}\n\n"
            "Answer using your general knowledge and clearly state that no matching\n"
            "documents were found in the knowledge base."
        )

    async def search(self, query: str) -> str:
        """
        Search the knowledge base and return a grounded answer.

        Args:
            query: The user's question or search query.

        Returns:
            The LLM-generated response grounded in retrieved documents.
        """
        rag_context = await self._retrieve_rag_context(query)
        prompt = self._build_prompt(query, rag_context)
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content
