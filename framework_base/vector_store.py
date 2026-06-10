from langchain_postgres import PGVector
from langchain_huggingface import HuggingFaceEmbeddings
from settings import settings


def get_vector_store(
    collection_name: str = "langchain",
    async_mode: bool = False,
) -> PGVector:
    """Return a PGVector store backed by the existing PostgreSQL instance.

    Tables (langchain_pg_collection, langchain_pg_embedding) are created
    automatically on first call via CREATE TABLE IF NOT EXISTS.

    Pass async_mode=True for async callers (retrieval). Sync callers
    (ingestion loaders) use the default sync engine.
    """
    embedding_function = HuggingFaceEmbeddings(
        model_name=settings.hf_embed_model,
        model_kwargs={"device": settings.embed_device},
        encode_kwargs={"normalize_embeddings": True},
    )
    # psycopg3 sync dialect; swap to psycopg_async for async callers so
    # SQLAlchemy creates the async engine required by asimilarity_search.
    driver = "psycopg_async" if async_mode else "psycopg"
    pg_url = settings.postgres_dsn.replace(
        "postgresql://", f"postgresql+{driver}://", 1
    )
    return PGVector(
        embeddings=embedding_function,
        collection_name=collection_name,
        connection=pg_url,
        async_mode=async_mode,
        use_jsonb=True,
    )
