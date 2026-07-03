"""Unit tests for the semantic-cache invalidation hook in ingest_pdf.

Extraction, summarization chains, stores, and the cache are all mocked.
Covers: invalidation fires at ingest completion with the document name;
it is skipped when the cache is disabled; and it does NOT fire when the
ingest fails partway (old content still being served means old cache
entries are still valid).
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

import RAG.loaders.pdf_loader as pdf_loader
from settings import settings


def _patch_pipeline(stack: ExitStack, cache_enabled: bool = True):
    """Patch ingest_pdf's collaborators; returns (mock_cache, mock_retriever)."""
    stack.enter_context(
        patch.object(
            pdf_loader,
            "extract_text_from_pdf",
            return_value=[{"text": "chunk one", "page": 0}],
        )
    )
    stack.enter_context(
        patch.object(pdf_loader, "extract_tables_from_pdf", return_value=[])
    )

    summarize_chain = MagicMock()
    summarize_chain.batch = MagicMock(return_value=["summary one"])
    stack.enter_context(
        patch.object(pdf_loader, "_build_summarize_chain", return_value=summarize_chain)
    )
    hyde_chain = MagicMock()
    hyde_chain.batch = MagicMock(return_value=["q1\nq2"])
    stack.enter_context(
        patch.object(
            pdf_loader, "_build_hyde_chains", return_value=(hyde_chain, hyde_chain)
        )
    )

    stack.enter_context(patch.object(pdf_loader, "get_vector_store"))
    stack.enter_context(patch.object(pdf_loader, "get_document_store"))
    retriever = MagicMock()
    stack.enter_context(
        patch.object(pdf_loader, "MultiVectorRetriever", return_value=retriever)
    )

    cache = MagicMock()
    cache.sync_invalidate_by_document = MagicMock(return_value=2)
    stack.enter_context(
        patch.object(pdf_loader, "get_semantic_cache", return_value=cache)
    )
    stack.enter_context(patch.object(settings, "semantic_cache_enabled", cache_enabled))
    return cache, retriever


def test_ingest_pdf_invalidates_cache_at_completion():
    with ExitStack() as stack:
        cache, retriever = _patch_pipeline(stack)
        result = pdf_loader.ingest_pdf("fake.pdf", "doc.pdf")

    assert result["status"] == "ingested"
    assert result["document_name"] == "doc.pdf"
    retriever.vectorstore.add_documents.assert_called_once()
    retriever.docstore.mset.assert_called_once()
    cache.sync_invalidate_by_document.assert_called_once_with("doc.pdf")


def test_ingest_pdf_skips_invalidation_when_disabled():
    with ExitStack() as stack:
        cache, _ = _patch_pipeline(stack, cache_enabled=False)
        result = pdf_loader.ingest_pdf("fake.pdf", "doc.pdf")

    assert result["status"] == "ingested"
    cache.sync_invalidate_by_document.assert_not_called()


def test_ingest_pdf_failure_does_not_invalidate():
    with ExitStack() as stack:
        cache, retriever = _patch_pipeline(stack)
        retriever.vectorstore.add_documents.side_effect = RuntimeError("store down")
        with pytest.raises(RuntimeError):
            pdf_loader.ingest_pdf("fake.pdf", "doc.pdf")

    cache.sync_invalidate_by_document.assert_not_called()
