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
from ..utils import extract_tables_from_pdf, extract_text_from_pdf

logger = setup_logger(__name__)

_SUMMARIZE_PROMPT = """You are an assistant tasked with summarizing tables and text.
Give a concise summary of the table or text.
Respond only with the summary, no additional comment.
Do not start your message by saying "Here is a summary" or anything like that.
Just give the summary as it is.

Table or text chunk: {element}
"""


def _build_summarize_chain():
    model = LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        temperature=0.5,
    )
    prompt = ChatPromptTemplate.from_template(_SUMMARIZE_PROMPT)
    return {"element": lambda x: x} | prompt | model | StrOutputParser()


def ingest_pdf(file_path: str, document_name: str) -> dict:
    """Extract text + tables from a PDF, summarize them, and load into the
    vector DB using the multi-vector pattern.

    Vectorstore holds the LLM-generated summaries (small, semantically rich).
    Docstore holds the original chunks (full text/table HTML) keyed by doc_id.
    Retrieval hits a summary, then fetches the original from the docstore.

    document_name + ingestion_date are stamped on every chunk's metadata so
    chunks can later be listed/deleted by source document.
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

    summarize = _build_summarize_chain()
    text_summaries = (
        summarize.batch(text_strings, {"max_concurrency": 3}) if text_strings else []
    )
    table_summaries = (
        summarize.batch(table_html, {"max_concurrency": 3}) if table_html else []
    )

    vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
    docstore = get_document_store()
    retriever = MultiVectorRetriever(
        vectorstore=vectorstore, docstore=docstore, id_key=ID_KEY
    )

    if text_strings:
        text_ids = [str(uuid.uuid4()) for _ in text_strings]
        retriever.vectorstore.add_documents(
            [
                Document(
                    page_content=text_summaries[i],
                    metadata={
                        ID_KEY: text_ids[i],
                        DOC_NAME_KEY: document_name,
                        INGEST_DATE_KEY: ingestion_date,
                        CHUNK_TYPE_KEY: "text",
                    },
                )
                for i in range(len(text_strings))
            ]
        )
        # Docstore values are JSON-serialized dicts — wrap content accordingly.
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

    if table_html:
        table_ids = [str(uuid.uuid4()) for _ in table_html]
        retriever.vectorstore.add_documents(
            [
                Document(
                    page_content=table_summaries[i],
                    metadata={
                        ID_KEY: table_ids[i],
                        DOC_NAME_KEY: document_name,
                        INGEST_DATE_KEY: ingestion_date,
                        CHUNK_TYPE_KEY: "table",
                    },
                )
                for i in range(len(table_html))
            ]
        )
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

    return {
        "status": "ingested",
        "texts": len(text_strings),
        "tables": len(table_html),
        "document_name": document_name,
    }
