from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_community.document_compressors import FlashrankRerank

from logger import setup_logger
from settings import settings

logger = setup_logger(__name__)

_SUPPORTED_PROVIDERS = ("flashrank",)


class RerankerFactory:
    @staticmethod
    def create_reranker() -> BaseDocumentCompressor:
        """Return a configured reranker compressor for the provider in settings.

        The returned object implements BaseDocumentCompressor and can be passed
        directly to ContextualCompressionRetriever as base_compressor.

        Supported RERANKER_PROVIDER values:
          - "flashrank"  local ONNX model, no API key, ~50-100ms (default)
        """
        provider = settings.reranker_provider.lower()
        top_n = settings.reranker_top_n

        if provider == "flashrank":
            logger.info(f"Initialising FlashrankRerank reranker (top_n={top_n})")
            return FlashrankRerank(top_n=top_n)

        raise ValueError(
            f"Unsupported reranker provider: '{provider}'. "
            f"Supported values: {_SUPPORTED_PROVIDERS}"
        )
