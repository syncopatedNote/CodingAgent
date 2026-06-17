PLAN_FILES_PROMPT = """\
You are planning a code change file by file. Produce an explicit, ordered plan
of every file to create or modify — nothing more, nothing less.

REQUIREMENTS:
{requirements}

DESIGN / ISSUE DETAILS:
{design}

REPOSITORY TREE:
{repo_tree}

CONTENTS OF LIKELY-IMPACTED FILES:
{impacted_files}

Development guidelines are authoritative for this codebase and are provided in
the system message above — your plan must respect them.

Produce the plan as a list of files. For each file give:
- path: repository-root-relative path.
- intent: precisely what changes in THIS file and why (specific enough that a
  developer could implement it from the intent alone).
- is_new: true if the file does not exist yet, false if it already exists.

Rules:
- One entry per file. Do NOT bundle multiple files into one entry.
- Order the files in DEPENDENCY order: a file that others import or rely on
  comes before the files that depend on it (e.g. a new helper before its caller).
- Include test files and documentation files when the guidelines or requirements
  call for them.
- Do NOT include any file that does not need to change.

## Test file placement rule (MANDATORY)

Every test file MUST mirror the source file's path under the `tests/` directory
at the repository root. The `tests/` directory already exists — never plan tests
anywhere else (not alongside the source file, not flat in `tests/`).

Mapping rule:
  <source_path>  →  tests/<source_path_with_test_prefix_on_filename>

Concrete examples from this codebase:
  agents/coding_pipeline/coding_pipeline.py
      → tests/agents/coding_pipeline/test_coding_pipeline.py

  agents/coding_pipeline/coding_agent/custom_tools.py
      → tests/agents/coding_pipeline/coding_agent/test_custom_tools.py

  framework_base/llm_base.py
      → tests/framework_base/test_llm_base.py

  utils/time_utils.py
      → tests/utils/test_time_utils.py

Always add both the source file AND its corresponding test file as separate
entries in the plan. The source file entry comes first (dependency order);
the test file entry follows it.
"""
