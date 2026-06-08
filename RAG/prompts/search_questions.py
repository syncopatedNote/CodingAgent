SEARCH_QUESTIONS_PROMPT = """You are generating synthetic search queries for a retrieval system.

Given a text passage, generate {n} questions that a person might ask if this passage contains the information they are looking for.

Requirements:

* Every question must be directly answerable from the passage.
* Do not invent, infer, or assume facts that are not explicitly supported by the passage.
* Use natural language that real users would search with.
* Cover different aspects of the passage when possible.
* Preserve important names, terms, roles, dates, policies, processes, requirements, conditions, and concepts mentioned in the text.
* Questions should be self-contained and understandable without additional context.
* Vary the phrasing and level of specificity.
* Output only the questions, one per line.
* Do not number the questions.

PASSAGE:
{chunk}
"""
