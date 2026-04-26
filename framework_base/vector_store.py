from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from settings import settings

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    _chromadb_available = True
except ImportError:
    _chromadb_available = False


def get_vector_store(store_type: str = "chroma", collection_name: str = "langchain"):
    """Return a Chroma vector store.

    Connect to a hosted Chroma HTTP server using settings.CHROMA_SERVER_HOST and
    settings.CHROMA_SERVER_HTTP_PORT. This module no longer supports a
    file-based persistent fallback; if the hosted Chroma settings are not
    configured the function will raise an error.
    """
    if store_type != "chroma":
        raise RuntimeError("No db found.")

    embed_model = settings.hf_embed_model
    embedding_function = HuggingFaceEmbeddings(
        model_name=embed_model,
        model_kwargs={"device": settings.embed_device},
        encode_kwargs={"normalize_embeddings": True},
    )

    chroma_host = settings.chroma_server_host
    chroma_http_port = settings.chroma_server_http_port

    if not chroma_host or not chroma_http_port:
        raise RuntimeError(
            "Hosted Chroma is not configured. Set CHROMA_SERVER_HOST and CHROMA_SERVER_HTTP_PORT in your environment/settings."
        )

    if not _chromadb_available:
        raise RuntimeError(
            "chromadb package is not installed; cannot connect to hosted Chroma."
        )

    try:
        client = chromadb.HttpClient(
            host=chroma_host,
            port=int(chroma_http_port),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding_function,
            client=client,
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to connect to hosted Chroma at {chroma_host}:{chroma_http_port}: {e}"
        )
