GENERATE_CODE_PROMPT = """\
You are an expert software developer.  {action} production-ready code.

REQUIREMENTS:
{requirements}

CODEBASE CONTEXT:
{context}

{extra}

Provide complete, production-ready code that:
1. Follows the development guidelines strictly
2. Implements all requirements
3. Includes proper error handling, logging, and documentation
4. Follows best practices for the target technology stack
{feedback_instruction}
Structure your response as file-by-file code blocks with clear paths, e.g.

### `src/utils/helper.py`
```python
...
```
"""
