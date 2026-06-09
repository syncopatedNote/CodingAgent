from framework_base.llm_base import LLMFactory
from langchain.schema.document import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from logger import setup_logger
from settings import settings
from ..constants import CHUNK_TYPE_KEY, DOC_NAME_KEY, ID_KEY, INGEST_DATE_KEY
from ..prompts.search_queries import SEARCH_QUERIES_PROMPT
from ..prompts.search_questions import SEARCH_QUESTIONS_PROMPT
from ..prompts.summary import SUMMARY_PROMPT

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
        temperature=0.1,
    )
    prompt = ChatPromptTemplate.from_template(SUMMARY_PROMPT)
    return {"element": lambda x: x} | prompt | model | StrOutputParser()


def _build_hyde_chains():
    model = LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        temperature=0.4,
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
    """Produce up to 3 vector Documents per chunk, all pointing to the same doc_id.

    1. Summary  — prose overview for broad/topic-level queries.
    2. Questions — joined hypothetical questions for natural-language queries.
    3. Queries   — joined search terms for keyword/mixed-style queries.

    Each Document carries ID_KEY so MultiVectorRetriever fetches the original
    chunk from the docstore on any retrieval hit.
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
