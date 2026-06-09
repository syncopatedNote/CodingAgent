SUPERVISOR_CLASSIFY_PROMPT = """
Classify the following user request into exactly one of these categories:

**Categories:**
1. CODE_GENERATION - User explicitly wants to generate, write,
   implement, or develop code.
2. SEARCH_OPERATION - User explicitly wants to search or look up
   information INSIDE a specific external system: Confluence,
   Jira, GitLab, or GitHub. The request must name or clearly
   imply one of these platforms.
3. GENERAL_CHAT - Everything else: general questions, knowledge
   queries, greetings, requests for explanation, questions about
   people/projects/technologies, or anything that does not
   explicitly target one of the platforms above.

**User Request:** {user_input}{jira_context}

**Classification Rules (apply in order):**
- → CODE_GENERATION only if the user wants code to be written or
  generated (e.g. "write a function", "implement PROJ-123").
- → SEARCH_OPERATION only if the user explicitly names or clearly
  implies Confluence, Jira, GitLab, or GitHub AND is asking to
  search/fetch/look up content within that platform.
  Examples of qualifying phrases: "search Confluence for …",
  "find the Jira ticket …", "look up in GitLab …", "fetch the
  GitHub issue …".
- → GENERAL_CHAT for everything else, including questions about
  people, technologies, projects, or general knowledge — even if
  they use words like "find", "know", "has", "worked on", etc.
  A question like "has Alice worked on AWS ECS?" is GENERAL_CHAT
  because it is a knowledge question, not an explicit request to
  query a platform.

**IMPORTANT:** When in doubt, default to GENERAL_CHAT.

**Response Format (respond with ONLY this format, nothing else):**
CATEGORY: [ONE OF: CODE_GENERATION, SEARCH_OPERATION, GENERAL_CHAT]
CONFIDENCE: [0.0-1.0]
REASONING: [Brief one-line explanation]

Examples:
- "Generate code for PROJ-123" → CODE_GENERATION, 0.95
- "Search Confluence for deployment docs" → SEARCH_OPERATION, 0.95
- "Find the Jira ticket PROJ-42" → SEARCH_OPERATION, 0.92
- "Has Alice worked on AWS ECS?" → GENERAL_CHAT, 0.95
- "What is Kubernetes?" → GENERAL_CHAT, 0.98
- "What can you help with?" → GENERAL_CHAT, 0.90
"""
