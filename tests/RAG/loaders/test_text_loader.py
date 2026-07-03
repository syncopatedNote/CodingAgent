"""Unit tests for the semantic-cache invalidation hook in ingest_text_file.

Chunking, summarization chains, stores, and the cache are all mocked.
Covers: invalidation fires at ingest completion; the empty-file early
return does not invalidate (nothing was written); disabled flag skips it.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import RAG.loaders.text_loader as text_loader
from settings import settings


def _patch_pipeline(stack: ExitStack, chunks, cache_enabled: bool = True):
    """Patch ingest_text_file's collaborators; returns the mock cache."""
    stack.enter_context(patch.object(text_loader, "split_text", return_value=chunks))

    summarize_chain = MagicMock()
    summarize_chain.batch = MagicMock(return_value=["summary one"])
    stack.enter_context(
        patch.object(
            text_loader, "_build_summarize_chain", return_value=summarize_chain
        )
    )
    hyde_chain = MagicMock()
    hyde_chain.batch = MagicMock(return_value=["q1\nq2"])
    stack.enter_context(
        patch.object(
            text_loader, "_build_hyde_chains", return_value=(hyde_chain, hyde_chain)
        )
    )

    stack.enter_context(patch.object(text_loader, "get_vector_store"))
    stack.enter_context(patch.object(text_loader, "get_document_store"))
    stack.enter_context(
        patch.object(text_loader, "MultiVectorRetriever", return_value=MagicMock())
    )

    cache = MagicMock()
    cache.sync_invalidate_by_document = MagicMock(return_value=1)
    stack.enter_context(
        patch.object(text_loader, "get_semantic_cache", return_value=cache)
    )
    stack.enter_context(patch.object(settings, "semantic_cache_enabled", cache_enabled))
    return cache


def _write_source_file(tmp_path, content="hello world"):
    source = tmp_path / "notes.txt"
    source.write_text(content)
    return str(source)


def test_ingest_text_file_invalidates_cache_at_completion(tmp_path):
    with ExitStack() as stack:
        cache = _patch_pipeline(stack, chunks=["chunk one"])
        result = text_loader.ingest_text_file(_write_source_file(tmp_path), "notes.txt")

    assert result["status"] == "ingested"
    assert result["texts"] == 1
    cache.sync_invalidate_by_document.assert_called_once_with("notes.txt")


def test_empty_file_early_return_does_not_invalidate(tmp_path):
    with ExitStack() as stack:
        cache = _patch_pipeline(stack, chunks=[])
        result = text_loader.ingest_text_file(
            _write_source_file(tmp_path, content=""), "notes.txt"
        )

    assert result["texts"] == 0
    cache.sync_invalidate_by_document.assert_not_called()


def test_ingest_text_file_skips_invalidation_when_disabled(tmp_path):
    with ExitStack() as stack:
        cache = _patch_pipeline(stack, chunks=["chunk one"], cache_enabled=False)
        result = text_loader.ingest_text_file(_write_source_file(tmp_path), "notes.txt")

    assert result["status"] == "ingested"
    cache.sync_invalidate_by_document.assert_not_called()
