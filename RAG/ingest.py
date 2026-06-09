import logging
import os
import tempfile

from .loaders.pdf_loader import ingest_pdf
from .loaders.text_loader import ingest_text_file
from .services.s3_service import download_object_to_file

logger = logging.getLogger(__name__)


def ingest_file(bucket: str, object_key: str) -> dict:
    """Download an object from S3, dispatch to the right loader, and store
    in Chroma + the docstore.

    PDFs go through `pdf_loader.ingest_pdf`.
    All other files go through `text_loader.ingest_text_file`.

    Both loaders apply the same multi-vector pipeline: chunking +
    summarization + HyDE questions + HyDE queries, producing 3 vectors
    per chunk pointing to the original content in the docstore.
    """
    _, ext = os.path.splitext(object_key)
    ext = ext.lower()
    # object_key has the form 'uploads/{uuid}/{filename}' — take the filename
    document_name = object_key.rsplit("/", 1)[-1] or object_key

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
        tmp_path = tf.name

    try:
        download_object_to_file(bucket, object_key, tmp_path)

        if ext == ".pdf":
            result = ingest_pdf(tmp_path, document_name=document_name)
        else:
            result = ingest_text_file(tmp_path, document_name=document_name)

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
