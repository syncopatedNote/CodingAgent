"""
Custom (non-MCP) tools bound to the context-collector supervisor LLM.

``ask_user`` pauses the graph via ``interrupt()`` so the collector can ask the
user for missing context (interactive mode only). ``submit_context`` is the
collector's terminal tool: the supervisor calls it once it has gathered
everything, and the tool-executor intercepts it to build the ``ContextBundle``
and end the run. Both bodies that are intercepted are no-op stubs.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt

from logger import setup_logger

logger = setup_logger(__name__)


@tool
async def ask_user(question: str) -> str:
    """Ask the user a question and wait for their response.

    Use this whenever you need information, clarification, or approval from the
    user. The question should be clear and specific.

    IMPORTANT: Always call this tool ALONE — never combine it with other tool
    calls in the same turn.

    Args:
        question: The question to present to the user.
    """
    response = interrupt({"question": question})
    return str(response)


@tool
async def submit_context(
    requirements: str,
    repository_reference: str,
    development_guidelines: str,
    confluence_design_details: str = "",
    source_ref: str = "",
    target_branch: str = "",
) -> str:
    """Submit the fully-gathered context and finish context collection.

    Call this ONCE, only after you have gathered everything you can. The three
    required fields must be non-empty; ``development_guidelines`` is mandatory —
    if you cannot fetch the guidelines file, do NOT call this tool, emit a
    FAILURE report instead (autonomous) or ask the user (interactive).

    Args:
        requirements: The core task — the ticket/issue description or the user's
            pasted requirements.
        repository_reference: The repository to work in (URL, slug, or project
            path) discovered from the ticket/issue.
        development_guidelines: Full text of the development-guidelines file.
        confluence_design_details: Design-doc content, if any was linked.
        source_ref: The entry-point reference (e.g. "PROJ-123", "owner/repo#42").
        target_branch: Branch to base work on; defaults to the configured base
            branch when omitted.
    """
    # Body is never executed — the collector's tool-executor intercepts this
    # call to build the ContextBundle and route the graph to END.
    return "context submitted"
