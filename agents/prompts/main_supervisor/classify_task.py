SUPERVISOR_CLASSIFY_PROMPT = """
Classify the following user request into exactly one of these categories:

**Categories:**
1. CODE_GENERATION - User wants to generate, write, implement, build,
   create, fix, or develop code or a feature. A Jira/GitHub/GitLab
   ticket reference is often the SOURCE OF REQUIREMENTS, not the target
   of a search — the presence of a ticket ID does NOT make this a
   SEARCH_OPERATION.
2. SEARCH_OPERATION - User explicitly wants to search or look up
   information INSIDE a specific external system: Confluence,
   Jira, GitLab, or GitHub. The request must name or clearly
   imply one of these platforms AND the intent is to READ/FETCH content
   from that platform, not to act on it.
3. GENERAL_CHAT - Everything else: general questions, knowledge
   queries, greetings, requests for explanation, questions about
   people/projects/technologies, or anything that does not
   explicitly target one of the platforms above.

**User Request:** {user_input}{jira_context}

**Classification Rules (apply in strict order — first match wins):**
1. → CODE_GENERATION if the request contains an action verb indicating
   code or feature work: implement, build, create, write, generate,
   develop, fix, code, add, refactor — regardless of whether a Jira,
   GitHub, or GitLab ticket ID is also present. Ticket IDs in this
   context are requirements references, not search targets.
2. → SEARCH_OPERATION only if the primary intent is to READ content from
   a platform with no code-action verb present. Qualifying phrases:
   "search Confluence for …", "find the Jira ticket …",
   "look up in GitLab …", "fetch the GitHub issue …",
   "what does ticket X say …", "show me the details of PROJ-42".
3. → GENERAL_CHAT for everything else, including questions about
   people, technologies, projects, or general knowledge — even if
   they use words like "find", "know", "has", "worked on", etc.

**IMPORTANT:** When in doubt, default to GENERAL_CHAT.

**Response Format (respond with ONLY this format, nothing else):**
CATEGORY: [ONE OF: CODE_GENERATION, SEARCH_OPERATION, GENERAL_CHAT]
CONFIDENCE: [0.0-1.0]
REASONING: [Brief one-line explanation]

Examples:
- "Generate code for PROJ-123" → CODE_GENERATION, 0.95
- "Implement the feature as per Jira ticket COR-1" → CODE_GENERATION, 0.97
- "Build the API endpoint described in STORY-42" → CODE_GENERATION, 0.96
- "Fix the bug in GitHub issue #99" → CODE_GENERATION, 0.95
- "Search Confluence for deployment docs" → SEARCH_OPERATION, 0.95
- "Find the Jira ticket PROJ-42" → SEARCH_OPERATION, 0.92
- "What does COR-1 say?" → SEARCH_OPERATION, 0.90
- "Has Alice worked on AWS ECS?" → GENERAL_CHAT, 0.95
- "What is Kubernetes?" → GENERAL_CHAT, 0.98
- "What can you help with?" → GENERAL_CHAT, 0.90
"""
