"""Schema constants for RAG metadata stored in Chroma and Redis.

Single source of truth — every module that reads or writes RAG chunk
metadata (ingest pipeline, retrievers, management APIs) imports from here.
"""

# Chroma collection that holds all ingested document chunks
COLLECTION_NAME = "uploads"

# Chroma metadata keys (also mirrored in Redis docstore values)
ID_KEY = "doc_id"
DOC_NAME_KEY = "document_name"
INGEST_DATE_KEY = "ingestion_date"
CHUNK_TYPE_KEY = "chunk_type"
