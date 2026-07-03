import uuid
from datetime import datetime, timezone

from framework_base.doc_store import get_document_store
from framework_base.semantic_query_cache import get_semantic_cache
from framework_base.vector_store import get_vector_store
from langchain.retrievers.multi_vector import MultiVectorRetriever
from logger import setup_logger
from settings import settings
from ..constants import COLLECTION_NAME, DOC_NAME_KEY, ID_KEY, INGEST_DATE_KEY
from ..utils import split_text
from .chunk_ingestor import (
    _build_chunk_vector_docs,
    _build_hyde_chains,
    _build_summarize_chain,
    _parse_lines,
)

logger = setup_logger(__name__)


def ingest_text_file(file_path: str, document_name: str) -> dict:
    """Read a plain-text file, chunk it, and load into the vector DB.

    Applies the same multi-vector pipeline as the PDF loader:
      - RecursiveCharacterTextSplitter for chunking
      - Each chunk produces 3 vectors in pgvector (summary, HyDE questions,
        HyDE queries), all pointing to the same doc_id in the docstore
      - Docstore holds the original chunk text keyed by doc_id

    Text files have no page structure, so no page metadata is stored.
    """
    logger.info(f"Ingesting text file: {file_path}")

    with open(file_path, "rb") as fh:
        raw_text = fh.read().decode(errors="ignore")

    text_chunks = split_text(raw_text)

    if not text_chunks:
        logger.warning(f"No text extracted from {file_path}; skipping ingestion")
        return {
            "status": "ingested",
            "texts": 0,
            "text_vectors": 0,
            "tables": 0,
            "document_name": document_name,
        }

    logger.info(f"Split into {len(text_chunks)} chunk(s)")

    ingestion_date = datetime.now(timezone.utc).isoformat()

    summarize_chain = _build_summarize_chain()
    questions_chain, queries_chain = _build_hyde_chains()

    summaries = summarize_chain.batch(text_chunks, {"max_concurrency": 3})
    questions = [
        _parse_lines(r)
        for r in questions_chain.batch(text_chunks, {"max_concurrency": 3})
    ]
    queries = [
        _parse_lines(r)
        for r in queries_chain.batch(text_chunks, {"max_concurrency": 3})
    ]

    chunk_ids = [str(uuid.uuid4()) for _ in text_chunks]

    vector_docs = _build_chunk_vector_docs(
        chunk_ids,
        summaries,
        questions,
        queries,
        document_name,
        ingestion_date,
        "text",
    )

    vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
    docstore = get_document_store()
    retriever = MultiVectorRetriever(
        vectorstore=vectorstore, docstore=docstore, id_key=ID_KEY
    )

    retriever.vectorstore.add_documents(vector_docs)
    retriever.docstore.mset(
        [
            (
                chunk_ids[i],
                {
                    "type": "text",
                    "content": text_chunks[i],
                    DOC_NAME_KEY: document_name,
                    INGEST_DATE_KEY: ingestion_date,
                },
            )
            for i in range(len(text_chunks))
        ]
    )

    logger.info(
        f"Stored {len(vector_docs)} vectors ({len(text_chunks)} chunks × 3) "
        f"for {document_name}"
    )

    # Invalidate at completion, not start: during a long ingest queries still
    # retrieve the old chunks, so entries cached mid-run would go stale the
    # moment the new content lands. sync_invalidate_by_document never raises.
    if settings.semantic_cache_enabled:
        invalidated = get_semantic_cache().sync_invalidate_by_document(document_name)
        logger.info(
            f"Invalidated {invalidated} semantic-cache entries after "
            f"ingesting '{document_name}'"
        )

    return {
        "status": "ingested",
        "texts": len(text_chunks),
        "text_vectors": len(vector_docs),
        "tables": 0,
        "document_name": document_name,
    }
