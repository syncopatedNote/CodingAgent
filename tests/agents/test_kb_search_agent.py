"""Unit tests for KnowledgeBaseSearchAgent's semantic-cache integration.

LLM, retriever pipeline, and cache are all mocked. Covers: cache hit
short-circuits retrieval + LLM; miss falls through and writes back;
no-context answers are never cached; disabled flag skips the cache
entirely; and _retrieve_rag_context's (context, source_doc_names) tuple
contract including name dedup and missing-document_name handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from agents.kb_search_agent import KnowledgeBaseSearchAgent
from settings import settings


def _make_agent(mock_llm, cache=None, cache_enabled=True) -> KnowledgeBaseSearchAgent:
    with (
        patch("agents.kb_search_agent.LLMFactory") as factory,
        patch("agents.kb_search_agent.get_semantic_cache") as get_cache,
        patch.object(settings, "semantic_cache_enabled", cache_enabled),
    ):
        factory.create_llm.return_value = mock_llm
        get_cache.return_value = cache
        agent = KnowledgeBaseSearchAgent()
    return agent


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="fresh answer"))
    return llm


@pytest.fixture()
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


# ── search() cache behaviour ───────────────────────────────────────


async def test_cache_hit_short_circuits_retrieval_and_llm(mock_llm, mock_cache):
    mock_cache.get = AsyncMock(return_value="cached answer")
    agent = _make_agent(mock_llm, cache=mock_cache)
    agent._retrieve_rag_context = AsyncMock()

    result = await agent.search("what is cortex?")

    assert result == "cached answer"
    agent._retrieve_rag_context.assert_not_awaited()
    mock_llm.ainvoke.assert_not_awaited()
    mock_cache.set.assert_not_awaited()


async def test_cache_miss_calls_llm_and_writes_back(mock_llm, mock_cache):
    agent = _make_agent(mock_llm, cache=mock_cache)
    agent._retrieve_rag_context = AsyncMock(return_value=("some context", ["a.pdf"]))

    result = await agent.search("what is cortex?")

    assert result == "fresh answer"
    mock_llm.ainvoke.assert_awaited_once()
    mock_cache.set.assert_awaited_once_with(
        "what is cortex?", "fresh answer", ["a.pdf"]
    )


async def test_no_context_answer_is_not_cached(mock_llm, mock_cache):
    agent = _make_agent(mock_llm, cache=mock_cache)
    agent._retrieve_rag_context = AsyncMock(return_value=("", []))

    result = await agent.search("what is cortex?")

    assert result == "fresh answer"
    mock_cache.set.assert_not_awaited()


async def test_cache_disabled_skips_cache_entirely(mock_llm):
    with (
        patch("agents.kb_search_agent.LLMFactory") as factory,
        patch("agents.kb_search_agent.get_semantic_cache") as get_cache,
        patch.object(settings, "semantic_cache_enabled", False),
    ):
        factory.create_llm.return_value = mock_llm
        agent = KnowledgeBaseSearchAgent()

    get_cache.assert_not_called()
    assert agent.cache is None

    agent._retrieve_rag_context = AsyncMock(return_value=("ctx", ["a.pdf"]))
    assert await agent.search("q") == "fresh answer"


# ── _retrieve_rag_context tuple contract ───────────────────────────


async def test_retrieve_rag_context_returns_deduped_source_names(mock_llm):
    agent = _make_agent(mock_llm, cache_enabled=False)
    docs = [
        Document(page_content="c1", metadata={"document_name": "a.pdf", "page": 0}),
        Document(
            page_content="c2",
            metadata={"document_name": "a.pdf", "type": "table", "page": 1},
        ),
        Document(page_content="c3", metadata={}),  # Confluence-style: no name
        Document(page_content="c4", metadata={"document_name": "b.pdf"}),
    ]
    retriever = MagicMock()
    retriever.ainvoke = AsyncMock(return_value=docs)

    with (
        patch("agents.kb_search_agent.get_vector_store"),
        patch("agents.kb_search_agent.get_document_store"),
        patch("agents.kb_search_agent.MultiVectorRetriever"),
        patch("agents.kb_search_agent.RerankerFactory"),
        patch(
            "agents.kb_search_agent.ContextualCompressionRetriever",
            return_value=retriever,
        ),
    ):
        rag_context, source_doc_names = await agent._retrieve_rag_context("q")

    assert source_doc_names == ["a.pdf", "b.pdf"]  # deduped, no-name doc skipped
    assert "[a.pdf, page 1]:\nc1" in rag_context
    assert "[Table from a.pdf, page 2]:\nc2" in rag_context
    assert "[unknown]:\nc3" in rag_context
    assert "[b.pdf]:\nc4" in rag_context


async def test_retrieve_rag_context_failure_returns_empty_tuple(mock_llm):
    agent = _make_agent(mock_llm, cache_enabled=False)
    with patch(
        "agents.kb_search_agent.get_vector_store",
        side_effect=RuntimeError("store down"),
    ):
        assert await agent._retrieve_rag_context("q") == ("", [])
