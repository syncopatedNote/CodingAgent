NOMINATE_FILES_PROMPT = """\
You are mapping a code change onto an existing repository.

Below is the live repository file tree, followed by the change requirements and
any design details. Identify the EXISTING files most likely to be impacted by
this change — the ones worth reading in full before planning the work.

REPOSITORY TREE:
{repo_tree}

REQUIREMENTS:
{requirements}

DESIGN / ISSUE DETAILS:
{design}

Rules:
- Return ONLY paths that already appear in the tree above. Do NOT invent paths.
- Do NOT list files that will be newly created — only existing files to read.
- Prefer the smallest set that gives enough context to plan confidently
  (typically 3–10 files). Skip unrelated areas of the repo.
- Favour the files that will actually be edited, plus the few whose contents the
  edits must stay consistent with (callers, shared helpers, config).
"""
