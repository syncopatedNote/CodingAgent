# This file makes the RAG directory a Python package.

# Explicitly import submodules so they are available as attributes of the RAG package.
# This allows the rq worker to resolve function paths like 'RAG.ingest.ingest_file'.
from . import ingest
from . import settings
