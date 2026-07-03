-- Semantic query cache for KB search answers.
-- Runs after 01-pgvector.sql, which creates the vector extension.

-- vector(768) matches sentence-transformers/all-mpnet-base-v2 (HF_EMBED_MODEL
-- default). If HF_EMBED_MODEL changes to a model with a different output
-- dimension, this table must be dropped and recreated with the new dimension;
-- inserts will fail loudly (pgvector dimension mismatch) until then.
CREATE TABLE IF NOT EXISTS semantic_query_cache (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text       TEXT        NOT NULL,
    query_embedding  vector(768) NOT NULL,
    response         TEXT        NOT NULL,
    source_doc_names TEXT[]      NOT NULL DEFAULT '{}',
    llm_model_name   TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL,
    hit_count        INTEGER     NOT NULL DEFAULT 0,
    last_hit_at      TIMESTAMPTZ
);

-- HNSW: incremental index, no training step, works correctly from row one
-- (unlike ivfflat, whose centroids are fixed at CREATE INDEX time).
CREATE INDEX IF NOT EXISTS idx_sqc_embedding
    ON semantic_query_cache USING hnsw (query_embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_sqc_expires_at
    ON semantic_query_cache (expires_at);

CREATE INDEX IF NOT EXISTS idx_sqc_doc_names
    ON semantic_query_cache USING GIN (source_doc_names);
