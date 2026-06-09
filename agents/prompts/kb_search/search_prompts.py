KB_SEARCH_WITH_CONTEXT_PROMPT = (
    "You are a helpful AI assistant. Use the relevant documents\n"
    "retrieved from the knowledge base below to answer the "
    "user's question.\n"
    "If the retrieved documents do not contain enough information,"
    " supplement\nwith your general knowledge and say so.\n\n"
    "**Relevant context from knowledge base:**\n{rag_context}\n\n"
    "**User question:** {query}\n\n"
    "Provide a clear, accurate answer grounded in the context"
    " above.\n"
    "Cite which document(s) support your answer where applicable."
)

KB_SEARCH_NO_CONTEXT_PROMPT = (
    "You are a helpful AI assistant with access to a knowledge"
    " base.\n"
    "No relevant documents were found in the knowledge base for"
    " this query.\n\n"
    "**User question:** {query}\n\n"
    "Answer using your general knowledge and clearly state that"
    " no matching\n"
    "documents were found in the knowledge base."
)
