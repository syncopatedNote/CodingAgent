QUESTION_ENHANCEMENT_PROMPT = """\
Your task is to rephrase a question to add useful context from the immediately \
preceding conversation exchange — but ONLY when the current question is a genuine \
follow-up to that exchange.

Rules (follow strictly):
1. If the current question targets a DIFFERENT system, service, or topic than the \
previous exchange, return it UNCHANGED.
2. If the current question is already self-contained and specific, return it UNCHANGED.
3. Only add context when the current question is a direct follow-up (e.g. "what about \
the other one?" or "give me more detail on that").
4. Never merge two unrelated topics together.
5. Return ONLY the (possibly enhanced) question — no explanation, no preamble.

Example of when NOT to enhance:
  Previous: "get broadband design docs from Confluence"
  Current:  "get details of the abc repository on GitLab"
  → Return unchanged: "get details of the abc repository on GitLab"
  (Different systems, unrelated topics.)

Example of when TO enhance:
  Previous: "get details of the abc repository on GitLab"
  Current:  "what open merge requests does it have?"
  → Enhanced: "what open merge requests does the abc repository on GitLab have?"

Recent conversation:
{context}

Current question: {last_message}

Enhanced question:"""
