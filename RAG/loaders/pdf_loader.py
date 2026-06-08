import uuid
from datetime import datetime, timezone

from framework_base.doc_store import get_document_store
from framework_base.llm_base import LLMFactory
from framework_base.vector_store import get_vector_store
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain.schema.document import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from logger import setup_logger
from settings import settings
from ..constants import (
    CHUNK_TYPE_KEY,
    COLLECTION_NAME,
    DOC_NAME_KEY,
    ID_KEY,
    INGEST_DATE_KEY,
)
from ..prompts.search_queries import SEARCH_QUERIES_PROMPT
from ..prompts.search_questions import SEARCH_QUESTIONS_PROMPT
from ..prompts.summary import SUMMARY_PROMPT
from ..utils import extract_tables_from_pdf, extract_text_from_pdf

logger = setup_logger(__name__)

_NUMBER_OF_QUESTIONS = 3
_NUMBER_OF_QUERIES = 3


def _parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


def _build_summarize_chain():
    model = LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        temperature=0.3,
    )
    prompt = ChatPromptTemplate.from_template(SUMMARY_PROMPT)
    return {"element": lambda x: x} | prompt | model | StrOutputParser()


def _build_hyde_chains():
    model = LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        temperature=0.3,
    )
    parser = StrOutputParser()
    q_prompt = ChatPromptTemplate.from_template(SEARCH_QUESTIONS_PROMPT)
    sq_prompt = ChatPromptTemplate.from_template(SEARCH_QUERIES_PROMPT)
    questions_chain = (
        {"chunk": lambda x: x, "n": lambda _: _NUMBER_OF_QUESTIONS}
        | q_prompt
        | model
        | parser
    )
    queries_chain = (
        {"chunk": lambda x: x, "n": lambda _: _NUMBER_OF_QUERIES}
        | sq_prompt
        | model
        | parser
    )
    return questions_chain, queries_chain


def _build_chunk_vector_docs(
    chunk_ids: list[str],
    summaries: list[str],
    questions_per_chunk: list[list[str]],
    queries_per_chunk: list[list[str]],
    document_name: str,
    ingestion_date: str,
    chunk_type: str,
) -> list[Document]:
    """Produce 3 vector Documents per chunk, all pointing to the same doc_id.

    1. Summary  — prose overview for broad/topic-level queries.
    2. Questions — joined hypothetical questions for natural-language queries.
    3. Queries   — joined search terms for keyword/mixed-style queries.

    Each Document carries ID_KEY so MultiVectorRetriever fetches the original
    chunk from the docstore on retrieval hit.
    """
    docs = []
    for chunk_id, summary, questions, queries in zip(
        chunk_ids, summaries, questions_per_chunk, queries_per_chunk
    ):
        shared_metadata = {
            ID_KEY: chunk_id,
            DOC_NAME_KEY: document_name,
            INGEST_DATE_KEY: ingestion_date,
            CHUNK_TYPE_KEY: chunk_type,
        }
        if summary.strip():
            docs.append(Document(page_content=summary, metadata=shared_metadata))
        if questions:
            docs.append(
                Document(page_content="\n".join(questions), metadata=shared_metadata)
            )
        if queries:
            docs.append(
                Document(page_content="\n".join(queries), metadata=shared_metadata)
            )
    return docs


def ingest_pdf(file_path: str, document_name: str) -> dict:
    """Extract text + tables from a PDF and load into the vector DB.

    Each chunk produces 3 vectors in ChromaDB, all pointing to the same doc_id:
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
        tables = extract_tables_from_pdf(file_path=file_path)
    except Exception:
        # tabula-py needs Java; if missing in the worker image, skip tables
        # rather than failing the whole ingest.
        logger.warning(
            "Table extraction failed; continuing without tables", exc_info=True
        )
        tables = []

    table_html = [t.to_html() for t in tables] if tables else []

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
                        "html": table_html[i],
                        DOC_NAME_KEY: document_name,
                        INGEST_DATE_KEY: ingestion_date,
                    },
                )
                for i in range(len(table_html))
            ]
        )

    logger.info(
        f"Stored {text_vector_count} text vectors ({len(text_strings)} chunks × 3) "
        f"and {table_vector_count} table vectors ({len(table_html)} tables × 3)"
    )

    return {
        "status": "ingested",
        "texts": len(text_strings),
        "text_vectors": text_vector_count,
        "tables": len(table_html),
        "table_vectors": table_vector_count,
        "document_name": document_name,
    }
