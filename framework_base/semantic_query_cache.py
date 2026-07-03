#!/usr/bin/env python3
"""
Semantic query cache for KB search answers.

Caches the final LLM-synthesized answer keyed by the *embedding* of the user
query. A lookup embeds the incoming query and nearest-neighbor searches the
``semantic_query_cache`` table (pgvector, cosine distance); a hit within the
configured similarity threshold returns the stored response without any
retrieval or LLM call.

Expiry is lazy: ``get`` filters ``expires_at > NOW()``, and ``set``
opportunistically deletes expired rows and enforces the LRU size cap
(SEMANTIC_CACHE_MAX_ENTRIES) — no scheduler required. Entries are filtered by
``llm_model_name`` so a model switch never serves another model's answers.

Invalidation is by source document name (``source_doc_names`` column), fired
by the document-delete route (async) and by the RAG ingest loaders on
completion (sync). Invalidation never raises — TTL is the backstop.
"""

import asyncio
from typing import List, Optional

import psycopg

from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)

_INVALIDATE_SQL = "DELETE FROM semantic_query_cache WHERE %s = ANY(source_doc_names)"


class SemanticQueryCache:
    """Postgres/pgvector-backed semantic cache for KB search answers.

    All operations degrade gracefully: a cache failure is logged and treated
    as a miss (``get``) or a no-op (``set`` / invalidation) — the cache must
    never take down KB search or an ingest run.
    """

    def __init__(self) -> None:
        # Loaded lazily on first get/set so invalidation-only callers
        # (the rag-worker) never pay the embedding-model load.
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            from langchain_huggingface import HuggingFaceEmbeddings

            # Same construction as framework_base/vector_store.py so cosine
            # distances are on the same normalized scale.
            self._embedder = HuggingFaceEmbeddings(
                model_name=settings.hf_embed_model,
                model_kwargs={"device": settings.embed_device},
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._embedder

    def _embed_to_vector_literal(self, query: str) -> str:
        """Embed ``query`` and serialize to a pgvector literal ('[f1,f2,...]').

        The literal is always passed as a bound parameter cast with
        ``%s::vector`` — never interpolated into SQL.
        """
        embedding = self._get_embedder().embed_query(query)
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"

    async def get(self, query: str) -> Optional[str]:
        """Return the cached response for a semantically similar query, or None."""
        try:
            vector_literal = await asyncio.to_thread(
                self._embed_to_vector_literal, query
            )
            async with await psycopg.AsyncConnection.connect(
                settings.postgres_dsn
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, response,
                               query_embedding <=> %s::vector AS distance
                        FROM semantic_query_cache
                        WHERE expires_at > NOW()
                          AND llm_model_name = %s
                        ORDER BY distance
                        LIMIT 1
                        """,
                        (vector_literal, settings.llm_model_name),
                    )
                    row = await cur.fetchone()
        except Exception:
            logger.warning(
                "Semantic cache lookup failed; treating as miss", exc_info=True
            )
            return None

        if row is None:
            logger.info("Semantic cache miss (no live entries for model)")
            return None

        entry_id, response, distance = row
        max_distance = 1.0 - settings.semantic_cache_similarity_threshold
        if distance <= max_distance:
            logger.info(f"Semantic cache HIT (distance={distance:.4f})")
            self._record_hit(entry_id)
            return response

        # Logged distances on near-misses are the tuning signal for
        # SEMANTIC_CACHE_SIMILARITY_THRESHOLD.
        logger.info(f"Semantic cache miss (nearest distance={distance:.4f})")
        return None

    def _record_hit(self, entry_id) -> None:
        """Bump hit stats in the background; never blocks or raises."""

        async def _bump() -> None:
            try:
                async with await psycopg.AsyncConnection.connect(
                    settings.postgres_dsn
                ) as conn:
                    await conn.execute(
                        """
                        UPDATE semantic_query_cache
                        SET hit_count = hit_count + 1, last_hit_at = NOW()
                        WHERE id = %s
                        """,
                        (entry_id,),
                    )
            except Exception:
                logger.warning("Semantic cache hit-count update failed", exc_info=True)

        asyncio.create_task(_bump())

    async def set(self, query: str, response: str, source_doc_names: List[str]) -> None:
        """Cache ``response`` for ``query``, tagged with its source documents.

        Skipped when ``source_doc_names`` is empty: a no-context answer changes
        as soon as a document is ingested, and with no source names it could
        never be invalidated.
        """
        if not source_doc_names:
            logger.info("Semantic cache write skipped: no source documents")
            return
        try:
            vector_literal = await asyncio.to_thread(
                self._embed_to_vector_literal, query
            )
            async with await psycopg.AsyncConnection.connect(
                settings.postgres_dsn
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO semantic_query_cache
                            (query_text, query_embedding, response,
                             source_doc_names, llm_model_name, expires_at)
                        VALUES (%s, %s::vector, %s, %s, %s,
                                NOW() + make_interval(hours => %s))
                        """,
                        (
                            query,
                            vector_literal,
                            response,
                            source_doc_names,
                            settings.llm_model_name,
                            settings.semantic_cache_ttl_hours,
                        ),
                    )
                    # Opportunistic cleanup: lazy expiry + LRU cap. Runs only
                    # on cache misses, which already paid for an LLM call.
                    await cur.execute(
                        "DELETE FROM semantic_query_cache WHERE expires_at < NOW()"
                    )
                    await cur.execute(
                        """
                        DELETE FROM semantic_query_cache
                        WHERE id IN (
                            SELECT id FROM semantic_query_cache
                            ORDER BY COALESCE(last_hit_at, created_at) DESC
                            OFFSET %s
                        )
                        """,
                        (settings.semantic_cache_max_entries,),
                    )
            logger.info(f"Semantic cache write (sources={source_doc_names})")
        except Exception:
            logger.warning("Semantic cache write failed; skipping", exc_info=True)

    async def invalidate_by_document(self, doc_name: str) -> int:
        """Delete every cache entry sourced from ``doc_name``. Never raises."""
        try:
            async with await psycopg.AsyncConnection.connect(
                settings.postgres_dsn
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(_INVALIDATE_SQL, (doc_name,))
                    return cur.rowcount
        except Exception:
            logger.warning(
                f"Semantic cache invalidation failed for '{doc_name}'",
                exc_info=True,
            )
            return 0

    def sync_invalidate_by_document(self, doc_name: str) -> int:
        """Sync variant of invalidate_by_document for the RAG ingest loaders.

        Never raises — ingest must not fail because of the cache.
        """
        try:
            with psycopg.connect(settings.postgres_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(_INVALIDATE_SQL, (doc_name,))
                    return cur.rowcount
        except Exception:
            logger.warning(
                f"Semantic cache invalidation failed for '{doc_name}'",
                exc_info=True,
            )
            return 0


_cache_instance: Optional[SemanticQueryCache] = None


def get_semantic_cache() -> SemanticQueryCache:
    """Return the process-wide cache instance (embedding model loads once)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticQueryCache()
    return _cache_instance
