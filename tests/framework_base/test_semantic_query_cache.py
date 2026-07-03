"""Unit tests for SemanticQueryCache.

All Postgres access and the embedding model are mocked — no live
infrastructure. Covers threshold behaviour, model-name filtering, the
skip-on-empty-sources rule, opportunistic cleanup on writes, never-raise
invalidation, graceful degradation on DB errors, and lazy embedder loading.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import framework_base.semantic_query_cache as sqc_module
from framework_base.semantic_query_cache import (
    SemanticQueryCache,
    get_semantic_cache,
)
from settings import settings


EMBEDDING = [0.1, 0.2, 0.3]


# ── Mock plumbing ──────────────────────────────────────────────────


def _async_cm(obj):
    """Wrap `obj` in an async context manager mock."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=obj)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _sync_cm(obj):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=obj)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _wire_async_connect(mock_psycopg, fetch_row=None, rowcount=0):
    """Wire mock_psycopg.AsyncConnection.connect and return the cursor mock."""
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=fetch_row)
    cursor.rowcount = rowcount
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=_async_cm(cursor))
    conn.execute = AsyncMock()
    mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=_async_cm(conn))
    return cursor


def _wire_sync_connect(mock_psycopg, rowcount=0):
    cursor = MagicMock()
    cursor.rowcount = rowcount
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=_sync_cm(cursor))
    mock_psycopg.connect = MagicMock(return_value=_sync_cm(conn))
    return cursor


@pytest.fixture()
def cache() -> SemanticQueryCache:
    """A cache instance with a fake (pre-loaded) embedder."""
    instance = SemanticQueryCache()
    embedder = MagicMock()
    embedder.embed_query = MagicMock(return_value=EMBEDDING)
    instance._embedder = embedder
    return instance


# ── get ────────────────────────────────────────────────────────────


async def test_get_hit_within_threshold_returns_response(cache, monkeypatch):
    monkeypatch.setattr(settings, "semantic_cache_similarity_threshold", 0.92)
    cache._record_hit = MagicMock()
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        _wire_async_connect(mock_psycopg, fetch_row=("id-1", "cached answer", 0.05))
        result = await cache.get("what is cortex?")
    assert result == "cached answer"
    cache._record_hit.assert_called_once_with("id-1")


async def test_get_near_miss_beyond_threshold_returns_none(cache, monkeypatch):
    monkeypatch.setattr(settings, "semantic_cache_similarity_threshold", 0.92)
    cache._record_hit = MagicMock()
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        _wire_async_connect(mock_psycopg, fetch_row=("id-1", "cached answer", 0.2))
        result = await cache.get("what is cortex?")
    assert result is None
    cache._record_hit.assert_not_called()


async def test_get_empty_cache_returns_none(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        _wire_async_connect(mock_psycopg, fetch_row=None)
        assert await cache.get("anything") is None


async def test_get_filters_by_current_model_and_binds_vector(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        cursor = _wire_async_connect(mock_psycopg, fetch_row=None)
        await cache.get("q")
    sql, params = cursor.execute.await_args.args
    assert "llm_model_name = %s" in sql
    assert "expires_at > NOW()" in sql
    vector_literal, model_name = params
    assert vector_literal == "[0.1,0.2,0.3]"
    assert model_name == settings.llm_model_name


async def test_get_db_error_degrades_to_miss(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        mock_psycopg.AsyncConnection.connect = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        assert await cache.get("q") is None  # no raise


# ── set ────────────────────────────────────────────────────────────


async def test_set_skips_when_no_source_docs(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        await cache.set("q", "answer", [])
    mock_psycopg.AsyncConnection.connect.assert_not_called()
    cache._embedder.embed_query.assert_not_called()


async def test_set_inserts_then_cleans_up(cache, monkeypatch):
    monkeypatch.setattr(settings, "semantic_cache_ttl_hours", 24)
    monkeypatch.setattr(settings, "semantic_cache_max_entries", 10_000)
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        cursor = _wire_async_connect(mock_psycopg)
        await cache.set("q", "answer", ["doc1.pdf"])

    assert cursor.execute.await_count == 3
    insert_sql, insert_params = cursor.execute.await_args_list[0].args
    assert "INSERT INTO semantic_query_cache" in insert_sql
    assert "make_interval(hours => %s)" in insert_sql
    assert insert_params == (
        "q",
        "[0.1,0.2,0.3]",
        "answer",
        ["doc1.pdf"],
        settings.llm_model_name,
        24,
    )

    expiry_sql = cursor.execute.await_args_list[1].args[0]
    assert "expires_at < NOW()" in expiry_sql

    lru_sql, lru_params = cursor.execute.await_args_list[2].args
    assert "OFFSET %s" in lru_sql
    assert lru_params == (10_000,)


async def test_set_db_error_never_raises(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        mock_psycopg.AsyncConnection.connect = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        await cache.set("q", "answer", ["doc1.pdf"])  # no raise


# ── invalidation ───────────────────────────────────────────────────


async def test_invalidate_by_document_returns_rowcount(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        cursor = _wire_async_connect(mock_psycopg, rowcount=3)
        assert await cache.invalidate_by_document("doc1.pdf") == 3
    sql, params = cursor.execute.await_args.args
    assert "ANY(source_doc_names)" in sql
    assert params == ("doc1.pdf",)


async def test_invalidate_by_document_error_returns_zero(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        mock_psycopg.AsyncConnection.connect = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        assert await cache.invalidate_by_document("doc1.pdf") == 0


def test_sync_invalidate_returns_rowcount(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        cursor = _wire_sync_connect(mock_psycopg, rowcount=2)
        assert cache.sync_invalidate_by_document("doc1.pdf") == 2
    sql, params = cursor.execute.call_args.args
    assert "ANY(source_doc_names)" in sql
    assert params == ("doc1.pdf",)


def test_sync_invalidate_error_returns_zero(cache):
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        mock_psycopg.connect = MagicMock(side_effect=RuntimeError("db down"))
        assert cache.sync_invalidate_by_document("doc1.pdf") == 0


# ── lazy embedder + singleton ──────────────────────────────────────


def test_invalidation_never_loads_embedding_model():
    instance = SemanticQueryCache()
    with patch.object(sqc_module, "psycopg") as mock_psycopg:
        _wire_sync_connect(mock_psycopg, rowcount=0)
        instance.sync_invalidate_by_document("doc1.pdf")
    assert instance._embedder is None


def test_get_semantic_cache_is_a_singleton(monkeypatch):
    monkeypatch.setattr(sqc_module, "_cache_instance", None)
    first = get_semantic_cache()
    assert get_semantic_cache() is first
