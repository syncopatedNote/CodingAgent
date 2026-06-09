SEARCH_FORMAT_RESULTS_PROMPT = """\
Based on the search results below, provide a clear, helpful response to the user's question.

Original Query: {query}

Search Results:
{results_summary}

Instructions:
1. Summarize the key findings in a natural, conversational way
2. If searching Jira tickets, include: ticket ID, summary, status, and key details.
3. If searching Confluence, include: page titles, relevant excerpts, and links if available.
4. If no useful results, say so clearly
5. Format nicely with markdown (headers, bullet points, etc.)

Provide your response now:"""
