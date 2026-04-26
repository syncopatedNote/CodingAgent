import logging
import os
import tempfile
import uuid

from framework_base.doc_store import get_document_store
from framework_base.vector_store import get_vector_store
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_core.documents import Document

from .loaders.pdf_loader import COLLECTION_NAME, ID_KEY, ingest_pdf
from .services.s3_service import download_object_to_file

logger = logging.getLogger(__name__)


def ingest_file(bucket: str, object_key: str) -> dict:
    """Download an object from S3, dispatch to the right loader, and store
    in Chroma + the docstore. PDFs go through the multi-vector pipeline in
    `pdf_loader.ingest_pdf`; other files are ingested as a single text doc.
    """
    _, ext = os.path.splitext(object_key)
    ext = ext.lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
        tmp_path = tf.name

    try:
        download_object_to_file(bucket, object_key, tmp_path)

        if ext == ".pdf":
            result = ingest_pdf(tmp_path)
        else:
            result = _ingest_text_file(tmp_path)

        result["object_key"] = object_key
        logger.info("Ingestion complete for s3://%s/%s", bucket, object_key)
        return result

    except Exception:
        logger.exception("Ingestion failed for s3://%s/%s", bucket, object_key)
        raise
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _ingest_text_file(file_path: str) -> dict:
    with open(file_path, "rb") as fh:
        text = fh.read().decode(errors="ignore")

    vectorstore = get_vector_store(collection_name=COLLECTION_NAME)
    docstore = get_document_store()
    retriever = MultiVectorRetriever(
        vectorstore=vectorstore, docstore=docstore, id_key=ID_KEY
    )

    doc_id = str(uuid.uuid4())
    retriever.vectorstore.add_documents(
        [Document(page_content=text, metadata={ID_KEY: doc_id})]
    )
    # Docstore values must be JSON-serializable dicts (not raw strings).
    retriever.docstore.mset([(doc_id, {"type": "text", "content": text})])

    return {"status": "ingested", "texts": 1, "tables": 0}
