GENERATE_CODE_PROMPT = """\
You are an expert software developer.  {action} production-ready code for a
SINGLE file.

TARGET FILE: {target_path}

REQUIREMENTS:
{requirements}

CODEBASE CONTEXT:
{context}

{extra}

Provide the complete, production-ready contents of `{target_path}` that:
1. Follows the development guidelines strictly
2. Implements all requirements for this file
3. Includes proper error handling, logging, and documentation
4. Follows best practices for the target technology stack
5. When CURRENT CODE is provided, modifies it in place — preserve everything
   not related to this change; do NOT rewrite the file from scratch
{feedback_instruction}
Return the full final contents of the file in a single code block headed by
its path, e.g.

### `{target_path}`
```
...
```
"""
