#!/usr/bin/env python3
"""
Document management routes for the RAG knowledge base.

Looks up and deletes chunks in the Chroma 'uploads' collection by
document_name. All metadata-key constants come from RAG.constants — the
single source of truth shared with the ingest pipeline.
"""

from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from framework_base.doc_store import get_document_store
from framework_base.vector_store import get_vector_store
from logger import setup_logger
from RAG.constants import COLLECTION_NAME, DOC_NAME_KEY, ID_KEY, INGEST_DATE_KEY

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["Documents"])


class DocumentSummary(BaseModel):
    document_name: str
    chunk_count: int = Field(..., description="Number of chunks in Chroma")
    ingestion_date: Optional[str] = Field(
        None, description="Latest ISO timestamp when this document was ingested"
    )


class DocumentListResponse(BaseModel):
    documents: List[DocumentSummary]
    total: int


class DeleteResponse(BaseModel):
    document_name: str
    chroma_deleted: int
    redis_deleted: int


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
    document in the Chroma knowledge base.

    - **With `document_name`**: Chroma applies a server-side `where` filter —
      only chunks for that document are returned.
    - **Without `document_name`**: ⚠️ All chunk metadata is fetched from Chroma
      and aggregated in Python. Avoid on large collections.
    """
    try:
        vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
        if document_name:
            result = vectorstore._collection.get(
                where={DOC_NAME_KEY: document_name},
                include=["metadatas"],
            )
        else:
            result = vectorstore._collection.get(include=["metadatas"])
    except Exception:
        logger.exception("Failed to query Chroma (document_name=%s)", document_name)
        raise HTTPException(status_code=502, detail="Vector store unavailable")

    metadatas = result.get("metadatas") or []
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
    """Delete every chunk belonging to `document_name` from both Chroma and
    Redis. Returns counts of records removed from each store."""
    document_name = document_name.strip("\"'")
    try:
        vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
        # Fetch matching chunks first so we know which Redis keys to delete
        matches = vectorstore._collection.get(
            where={DOC_NAME_KEY: document_name},
            include=["metadatas"],
        )
    except Exception:
        logger.exception("Failed to query Chroma for document_name=%s", document_name)
        raise HTTPException(status_code=502, detail="Vector store unavailable")

    chroma_ids = matches.get("ids") or []
    metadatas = matches.get("metadatas") or []

    if not chroma_ids:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for document '{document_name}'",
        )

    doc_ids = [m.get(ID_KEY) for m in metadatas if m and m.get(ID_KEY)]

    # Delete from Chroma by Chroma's internal ids — exact match, no race
    # with the `where` filter if another ingest is happening concurrently.
    try:
        vectorstore._collection.delete(ids=chroma_ids)
    except Exception:
        logger.exception("Chroma delete failed for document_name=%s", document_name)
        raise HTTPException(status_code=502, detail="Vector store delete failed")

    # Delete the matching original chunks from Redis
    redis_deleted = 0
    if doc_ids:
        try:
            docstore = get_document_store()
            docstore.mdelete(doc_ids)
            redis_deleted = len(doc_ids)
        except Exception:
            logger.exception(
                "Redis delete failed for document_name=%s — Chroma chunks removed "
                "but %d Redis keys may be orphaned",
                document_name,
                len(doc_ids),
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Chroma cleared ({len(chroma_ids)} chunks) but Redis "
                    f"delete failed; {len(doc_ids)} keys may be orphaned"
                ),
            )

    logger.info(
        "Deleted document '%s': %d Chroma chunks, %d Redis keys",
        document_name,
        len(chroma_ids),
        redis_deleted,
    )
    return DeleteResponse(
        document_name=document_name,
        chroma_deleted=len(chroma_ids),
        redis_deleted=redis_deleted,
    )
