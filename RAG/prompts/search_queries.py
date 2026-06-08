SEARCH_QUERIES_PROMPT = """You are generating synthetic search queries for a retrieval system.

Given a text passage, generate {n} realistic search queries that would lead someone to this passage.

Requirements:

* Queries must be answerable by the passage.
* Do not introduce information not present in the passage.
* Mix query styles:

  * short keyword searches
  * natural-language questions
  * partial phrases
  * topic-oriented searches
* Preserve important names, entities, policies, roles, dates, and terminology from the passage.
* Cover different information contained in the passage.
* Each query should represent a distinct retrieval path.
* Output one query per line.
* Do not number the queries.

PASSAGE:
{chunk}
"""
