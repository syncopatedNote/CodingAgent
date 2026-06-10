import uuid
from datetime import datetime, timezone

from framework_base.doc_store import get_document_store
from framework_base.vector_store import get_vector_store
from langchain.retrievers.multi_vector import MultiVectorRetriever
from logger import setup_logger
from ..constants import COLLECTION_NAME, DOC_NAME_KEY, ID_KEY, INGEST_DATE_KEY
from ..utils import extract_tables_from_pdf, extract_text_from_pdf
from .chunk_ingestor import (
    _build_chunk_vector_docs,
    _build_hyde_chains,
    _build_summarize_chain,
    _parse_lines,
)

logger = setup_logger(__name__)


def ingest_pdf(file_path: str, document_name: str) -> dict:
    """Extract text + tables from a PDF and load into the vector DB.

    Each chunk produces up to 3 vectors in pgvector, all pointing to the same
    doc_id:
      1. Summary        — broad topic recall
      2. HyDE questions — natural-language query recall
      3. HyDE queries   — keyword/mixed-style query recall

    Docstore holds the original chunks (full text/table HTML) keyed by doc_id.
    """
    logger.info(f"Extracting content from PDF: {file_path}")

    ingestion_date = datetime.now(timezone.utc).isoformat()

    text_chunks = extract_text_from_pdf(filepath=file_path)
    text_strings = [c["text"] for c in text_chunks]

    try:
        table_entries = extract_tables_from_pdf(file_path=file_path)
    except Exception:
        # tabula-py needs Java; if missing in the worker image, skip tables
        # rather than failing the whole ingest.
        logger.warning(
            "Table extraction failed; continuing without tables", exc_info=True
        )
        table_entries = []

    table_html = [e["table"].to_html() for e in table_entries]
    table_pages = [e["page"] for e in table_entries]

    logger.info(f"Extracted {len(text_strings)} text chunks, {len(table_html)} tables")

    summarize_chain = _build_summarize_chain()
    questions_chain, queries_chain = _build_hyde_chains()

    text_summaries = (
        summarize_chain.batch(text_strings, {"max_concurrency": 3})
        if text_strings
        else []
    )
    text_questions = (
        [
            _parse_lines(r)
            for r in questions_chain.batch(text_strings, {"max_concurrency": 3})
        ]
        if text_strings
        else []
    )
    text_queries = (
        [
            _parse_lines(r)
            for r in queries_chain.batch(text_strings, {"max_concurrency": 3})
        ]
        if text_strings
        else []
    )

    table_summaries = (
        summarize_chain.batch(table_html, {"max_concurrency": 3}) if table_html else []
    )
    table_questions = (
        [
            _parse_lines(r)
            for r in questions_chain.batch(table_html, {"max_concurrency": 3})
        ]
        if table_html
        else []
    )
    table_queries = (
        [
            _parse_lines(r)
            for r in queries_chain.batch(table_html, {"max_concurrency": 3})
        ]
        if table_html
        else []
    )

    vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
    docstore = get_document_store()
    retriever = MultiVectorRetriever(
        vectorstore=vectorstore, docstore=docstore, id_key=ID_KEY
    )

    text_vector_count = 0
    if text_strings:
        text_ids = [str(uuid.uuid4()) for _ in text_strings]
        text_vector_docs = _build_chunk_vector_docs(
            text_ids,
            text_summaries,
            text_questions,
            text_queries,
            document_name,
            ingestion_date,
            "text",
        )
        retriever.vectorstore.add_documents(text_vector_docs)
        text_vector_count = len(text_vector_docs)

        retriever.docstore.mset(
            [
                (
                    text_ids[i],
                    {
                        "type": "text",
                        "page": text_chunks[i].get("page"),
                        "content": text_strings[i],
                        DOC_NAME_KEY: document_name,
                        INGEST_DATE_KEY: ingestion_date,
                    },
                )
                for i in range(len(text_strings))
            ]
        )

    table_vector_count = 0
    if table_html:
        table_ids = [str(uuid.uuid4()) for _ in table_html]
        table_vector_docs = _build_chunk_vector_docs(
            table_ids,
            table_summaries,
            table_questions,
            table_queries,
            document_name,
            ingestion_date,
            "table",
        )
        retriever.vectorstore.add_documents(table_vector_docs)
        table_vector_count = len(table_vector_docs)

        retriever.docstore.mset(
            [
                (
                    table_ids[i],
                    {
                        "type": "table",
                        "page": table_pages[i],
                        "html": table_html[i],
                        DOC_NAME_KEY: document_name,
                        INGEST_DATE_KEY: ingestion_date,
                    },
                )
                for i in range(len(table_html))
            ]
        )

    n_text = len(text_strings)
    n_table = len(table_html)
    logger.info(
        f"Stored {text_vector_count} text vectors ({n_text} chunks × 3) "
        f"and {table_vector_count} table vectors ({n_table} tables × 3)"
    )

    return {
        "status": "ingested",
        "texts": len(text_strings),
        "text_vectors": text_vector_count,
        "tables": len(table_html),
        "table_vectors": table_vector_count,
        "document_name": document_name,
    }
