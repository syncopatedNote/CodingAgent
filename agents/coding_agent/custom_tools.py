"""
Custom (non-MCP) tools for the coding agent supervisor.

These are module-level LangChain tools bound to the supervisor LLM each turn.
``select_tools`` is intercepted by ``_tool_executor_node`` before it reaches
this module's body — its implementation here is intentionally a no-op stub.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import interrupt

from logger import setup_logger
from agents.prompts.coding_supervisor.generate_code import GENERATE_CODE_PROMPT
from agents.prompts.coding_supervisor.review_code import REVIEW_CODE_PROMPT
from .coding_llm_singleton import code_llm

logger = setup_logger(__name__)


@tool
async def ask_user(question: str) -> str:
    """Ask the user a question and wait for their response.

    Use this whenever you need information, clarification, or approval
    from the user.  The question should be clear and specific.

    IMPORTANT: Always call this tool ALONE — never combine it with
    other tool calls in the same turn.

    Args:
        question: The question to present to the user.
    """
    response = interrupt({"question": question})
    return str(response)


@tool
async def generate_code(
    requirements: str,
    context: str,
    existing_code: str = "",
    feedback: str = "",
    guidelines: str = "",
) -> str:
    """Generate or improve production-ready code.

    For the first generation pass supply ``requirements`` and ``context``.
    For subsequent reflection/improvement cycles also supply
    ``existing_code`` and the ``feedback`` to address.

    Coding guidelines are injected automatically from stored state —
    do NOT pass them manually.

    Args:
        requirements: What needs to be implemented.
        context: Repository structure, existing code patterns, etc.
        existing_code: Previously generated code to improve.
        feedback: Review feedback to address.
    """
    action = "Generate" if not existing_code else "Improve"

    extra_sections: list[str] = []
    if existing_code:
        extra_sections.append(f"CURRENT CODE TO IMPROVE:\n{existing_code}")
    if feedback:
        extra_sections.append(
            f"REVIEW FEEDBACK TO ADDRESS:\n{feedback}\n\n"
            "You MUST address every feedback point."
        )
    extra = "\n\n".join(extra_sections)

    prompt = GENERATE_CODE_PROMPT.format(
        action=action,
        requirements=requirements,
        context=context,
        extra=extra,
        feedback_instruction=(
            "5. Addresses every review-feedback point" if feedback else ""
        ),
    )
    messages = []
    if guidelines:
        messages.append(SystemMessage(content=f"CODING GUIDELINES:\n{guidelines}"))
    messages.append(HumanMessage(content=prompt))

    try:
        response = await code_llm.ainvoke(messages)
        return str(response.content)
    except Exception as exc:
        logger.error(f"Code generation LLM call failed: {exc}", exc_info=True)
        return (
            f"Code generation failed: {exc}\n\n"
            "The LLM service may be temporarily unavailable. "
            "Please retry or check the service configuration."
        )


@tool
async def review_code(
    code: str,
    requirements: str,
    guidelines: str = "",
) -> str:
    """Review generated code and return specific, actionable feedback.

    Coding guidelines are injected automatically from stored state —
    do NOT pass them manually.

    Args:
        code: The generated code to review.
        requirements: Original requirements to validate against.
    """
    prompt = REVIEW_CODE_PROMPT.format(
        code=code,
        requirements=requirements,
    )
    messages = []
    if guidelines:
        messages.append(SystemMessage(content=f"CODING GUIDELINES:\n{guidelines}"))
    messages.append(HumanMessage(content=prompt))

    try:
        response = await code_llm.ainvoke(messages)
        return str(response.content)
    except Exception as exc:
        logger.error(f"Code review LLM call failed: {exc}", exc_info=True)
        return (
            f"Code review failed: {exc}\n\n"
            "The LLM service may be temporarily unavailable. "
            "Please retry or check the service configuration."
        )


@tool
async def store_coding_guidelines(content: str) -> str:
    """Store fetched coding guidelines so they are automatically applied to
    every generate_code and review_code call in this session.

    Call this once after fetching the guidelines file — do NOT pass
    guidelines directly to generate_code or review_code.

    Args:
        content: Full text of the guidelines file.
    """
    # Body is never executed — _tool_executor_node intercepts this call.
    return content


@tool
async def select_tools(server_name: str) -> str:
    """Activate tools for a specific MCP server before calling its tools.

    The server's tools become available on your next turn.
    Call again with a different name to switch servers.

    Args:
        server_name: The server to activate (e.g. "github", "atlassian").
    """
    # Body is never executed — _tool_executor_node intercepts this call.
    return server_name
