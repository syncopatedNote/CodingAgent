SEARCH_CLASSIFY_PROMPT = """\
You are a search-routing assistant.  Classify the following search query into
exactly one category based on WHERE the information is most likely stored.

Categories:
  atlassian  — Confluence pages, Jira issues, epics, sprints, design docs
               stored in Atlassian products
  github     — GitHub repositories, pull requests, GitHub issues, commits,
               branches, GitHub Actions workflows
  gitlab     — GitLab repositories, merge requests, GitLab CI pipelines
  context7   — Library documentation, framework docs, package API references,
               technical how-to guides for open-source software
  unknown    — Cannot be determined from the query alone

Query: {query}

Respond with a JSON object matching this schema:
{format_instructions}

Important:
- Choose "unknown" only if the query is genuinely ambiguous across multiple
  categories, or refers to no specific system at all.
- Do NOT infer "github" just because code is mentioned; only use it when
  the query clearly targets a GitHub resource.
"""
