from pathlib import Path
from langchain_chroma import Chroma 
from langchain_ollama.embeddings import OllamaEmbeddings


# This function will create a new collection if it doesn't exist, or load an existing one if it does
def get_vector_store(
    store_type: str = "chroma",
    collection_name: str = "langchain"
):
    base_dir = Path(__file__).parent.absolute()
    print(f"base dir is {base_dir}")
    if store_type == "chroma":
        embedding_function = OllamaEmbeddings(model="nomic-embed-text")
        # Create/load persistent Chroma DB
        return Chroma(
            collection_name=collection_name,
            persist_directory="chroma_db",  # Data will be saved to this directory
            embedding_function=embedding_function
        )
    else:
        raise RuntimeError("No db found.")
