"""Unit tests for the delete-path semantic-cache invalidation in
routes/documents_routes.py.

Postgres, the docstore, and the cache are mocked. Covers: invalidation
fires after a successful delete; the invalidation result never changes
the HTTP response; no invalidation when the cache is disabled or the
document is not found.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import routes.documents_routes as documents_routes
from routes.documents_routes import delete_document
from settings import settings


def _async_cm(obj):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=obj)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _wire_vector_delete(mock_psycopg, rows):
    """Wire the pgvector DELETE ... RETURNING query to return `rows`."""
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=_async_cm(cursor))
    mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=_async_cm(conn))


@pytest.fixture()
def mock_cache():
    cache = MagicMock()
    cache.invalidate_by_document = AsyncMock(return_value=5)
    return cache


async def test_delete_invalidates_cache_after_success(mock_cache):
    with (
        patch.object(documents_routes, "psycopg") as mock_psycopg,
        patch.object(documents_routes, "get_document_store") as mock_store,
        patch.object(documents_routes, "get_semantic_cache", return_value=mock_cache),
        patch.object(settings, "semantic_cache_enabled", True),
    ):
        _wire_vector_delete(mock_psycopg, rows=[("id1",), ("id2",)])
        response = await delete_document("doc.pdf")

    assert response.vectors_deleted == 2
    assert response.docstore_deleted == 2
    mock_store.return_value.mdelete.assert_called_once_with(["id1", "id2"])
    mock_cache.invalidate_by_document.assert_awaited_once_with("doc.pdf")


async def test_invalidation_count_does_not_change_response(mock_cache):
    mock_cache.invalidate_by_document = AsyncMock(return_value=0)  # cache failure path
    with (
        patch.object(documents_routes, "psycopg") as mock_psycopg,
        patch.object(documents_routes, "get_document_store"),
        patch.object(documents_routes, "get_semantic_cache", return_value=mock_cache),
        patch.object(settings, "semantic_cache_enabled", True),
    ):
        _wire_vector_delete(mock_psycopg, rows=[("id1",)])
        response = await delete_document("doc.pdf")

    assert response.document_name == "doc.pdf"
    assert response.vectors_deleted == 1


async def test_no_invalidation_when_cache_disabled():
    with (
        patch.object(documents_routes, "psycopg") as mock_psycopg,
        patch.object(documents_routes, "get_document_store"),
        patch.object(documents_routes, "get_semantic_cache") as get_cache,
        patch.object(settings, "semantic_cache_enabled", False),
    ):
        _wire_vector_delete(mock_psycopg, rows=[("id1",)])
        await delete_document("doc.pdf")

    get_cache.assert_not_called()


async def test_no_invalidation_when_document_not_found(mock_cache):
    with (
        patch.object(documents_routes, "psycopg") as mock_psycopg,
        patch.object(documents_routes, "get_document_store"),
        patch.object(documents_routes, "get_semantic_cache", return_value=mock_cache),
        patch.object(settings, "semantic_cache_enabled", True),
    ):
        _wire_vector_delete(mock_psycopg, rows=[])
        with pytest.raises(HTTPException) as exc_info:
            await delete_document("missing.pdf")

    assert exc_info.value.status_code == 404
    mock_cache.invalidate_by_document.assert_not_awaited()
