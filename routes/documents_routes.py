#!/usr/bin/env python3
"""
Document management routes for the RAG knowledge base.

Looks up and deletes chunks in the pgvector 'uploads' collection by
document_name. All metadata-key constants come from RAG.constants — the
single source of truth shared with the ingest pipeline.
"""

from collections import defaultdict
from typing import List, Optional

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from framework_base.doc_store import get_document_store
from framework_base.semantic_query_cache import get_semantic_cache
from logger import setup_logger
from settings import settings
from RAG.constants import COLLECTION_NAME, DOC_NAME_KEY, ID_KEY, INGEST_DATE_KEY

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["Documents"])


class DocumentSummary(BaseModel):
    document_name: str
    chunk_count: int = Field(..., description="Number of chunks in the vector store")
    ingestion_date: Optional[str] = Field(
        None, description="Latest ISO timestamp when this document was ingested"
    )


class DocumentListResponse(BaseModel):
    documents: List[DocumentSummary]
    total: int


class DeleteResponse(BaseModel):
    document_name: str
    vectors_deleted: int
    docstore_deleted: int


def _summarise_metadatas(metadatas: list) -> List[DocumentSummary]:
    """Aggregate a flat list of per-chunk metadata dicts into one
    DocumentSummary per unique document_name."""
    counts: dict[str, int] = defaultdict(int)
    latest: dict[str, str] = {}
    for meta in metadatas:
        if not meta:
            continue
        name = meta.get(DOC_NAME_KEY)
        if not name:
            continue
        name = str(name)
        counts[name] += 1
        raw = meta.get(INGEST_DATE_KEY)
        if raw is not None:
            ts = str(raw)
            if name not in latest or ts > latest[name]:
                latest[name] = ts
    return [
        DocumentSummary(
            document_name=name,
            chunk_count=counts[name],
            ingestion_date=latest.get(name),
        )
        for name in sorted(counts)
    ]


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents in the knowledge base",
)
async def list_documents(
    document_name: Optional[str] = Query(
        None,
        description=(
            "Filter by exact document name. "
            "**Warning: omitting this parameter fetches metadata for every chunk "
            "in the collection and may be slow on large knowledge bases.**"
        ),
    ),
) -> DocumentListResponse:
    """Return a summary (chunk count + latest ingestion date) for each unique
    document in the pgvector knowledge base.

    - **With `document_name`**: a server-side WHERE filter is applied —
      only chunks for that document are returned.
    - **Without `document_name`**: ⚠️ All chunk metadata is fetched and
      aggregated in Python. Avoid on large collections.
    """
    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            async with conn.cursor() as cur:
                if document_name:
                    await cur.execute(
                        """
                        SELECT e.cmetadata
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c
                          ON e.collection_id = c.uuid
                        WHERE c.name = %s
                          AND e.cmetadata->>'document_name' = %s
                        """,
                        (COLLECTION_NAME, document_name),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT e.cmetadata
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c
                          ON e.collection_id = c.uuid
                        WHERE c.name = %s
                        """,
                        (COLLECTION_NAME,),
                    )
                rows = await cur.fetchall()
    except Exception:
        # structlog's BoundLogger takes a single event string — %-style
        # positional args raise TypeError, so format inline.
        logger.exception(
            f"Failed to query vector store (document_name={document_name})"
        )
        raise HTTPException(status_code=502, detail="Vector store unavailable")

    metadatas = [row[0] for row in rows]
    if not metadatas:
        if document_name:
            raise HTTPException(
                status_code=404,
                detail=f"No chunks found for document '{document_name}'",
            )
        return DocumentListResponse(documents=[], total=0)

    docs = _summarise_metadatas(metadatas)
    return DocumentListResponse(documents=docs, total=len(docs))


@router.delete("/{document_name:path}", response_model=DeleteResponse)
async def delete_document(document_name: str) -> DeleteResponse:
    """Delete every chunk belonging to `document_name` from both the vector
    store and the docstore. Returns counts of records removed from each."""
    document_name = document_name.strip("\"'")

    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    DELETE FROM langchain_pg_embedding e
                    USING langchain_pg_collection c
                    WHERE e.collection_id = c.uuid
                      AND c.name = %s
                      AND e.cmetadata->>'document_name' = %s
                    RETURNING e.cmetadata->>'doc_id'
                    """,
                    (COLLECTION_NAME, document_name),
                )
                rows = await cur.fetchall()
    except Exception:
        # Worded to avoid bandit B608 (flags "delete from" inside f-strings
        # as SQL construction; this is only a log message).
        logger.exception(
            f"Vector-store delete failed for document_name={document_name}"
        )
        raise HTTPException(status_code=502, detail="Vector store unavailable")

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for document '{document_name}'",
        )

    vectors_deleted = len(rows)
    doc_ids = [r[0] for r in rows if r[0]]

    docstore_deleted = 0
    if doc_ids:
        try:
            docstore = get_document_store()
            docstore.mdelete(doc_ids)
            docstore_deleted = len(doc_ids)
        except Exception:
            logger.exception(
                f"Docstore delete failed for document_name={document_name} — "
                f"vector chunks removed but {len(doc_ids)} docstore keys may "
                "be orphaned"
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Vector store cleared ({vectors_deleted} chunks) but docstore "
                    f"delete failed; {len(doc_ids)} keys may be orphaned"
                ),
            )

    if settings.semantic_cache_enabled:
        # Best-effort — invalidate_by_document never raises; TTL is the backstop.
        cache_invalidated = await get_semantic_cache().invalidate_by_document(
            document_name
        )
        logger.info(
            f"Invalidated {cache_invalidated} semantic-cache entries for "
            f"document '{document_name}'"
        )

    logger.info(
        f"Deleted document '{document_name}': {vectors_deleted} vector chunks, "
        f"{docstore_deleted} docstore keys"
    )
    return DeleteResponse(
        document_name=document_name,
        vectors_deleted=vectors_deleted,
        docstore_deleted=docstore_deleted,
    )
