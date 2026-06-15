"""
Custom (non-MCP) tools for the coding agent supervisor.

These are module-level LangChain tools bound to the supervisor LLM each turn.
``select_tools`` is intercepted by ``_tool_executor_node`` before it reaches
this module's body — its implementation here is intentionally a no-op stub.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from logger import setup_logger
from agents.prompts.coding_supervisor.generate_code import GENERATE_CODE_PROMPT
from agents.prompts.coding_supervisor.review_code import REVIEW_CODE_PROMPT
from .coding_llm_singleton import code_llm

logger = setup_logger(__name__)


@tool
async def generate_code(
    target_path: str,
    requirements: str,
    context: str,
    existing_code: str = "",
    feedback: str = "",
    guidelines: str = "",
) -> str:
    """Generate or improve production-ready code for ONE file.

    Each call targets a single file given by ``target_path``. For the first
    generation pass supply ``requirements`` and ``context``. For subsequent
    reflection/improvement cycles also supply the ``feedback`` to address.

    The current contents of ``target_path`` (if the file already exists on the
    base branch) are fetched and injected as ``existing_code`` automatically —
    do NOT fetch the file yourself and do NOT pass ``existing_code`` manually.
    For a brand-new file nothing is injected and you generate it from scratch.

    Coding guidelines are injected automatically from stored state —
    do NOT pass them manually.

    Args:
        target_path: Path of the file to create or modify, relative to the
            repository root (e.g. "agents/supervisor_agent.py").
        requirements: What needs to be implemented in THIS file.
        context: Why the change is needed, related components, conventions.
        existing_code: Injected automatically — leave unset.
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
        target_path=target_path or "(unspecified)",
        requirements=requirements,
        context=context,
        extra=extra,
        feedback_instruction=(
            "6. Addresses every review-feedback point" if feedback else ""
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
async def select_tools(server_name: str) -> str:
    """Activate tools for a specific MCP server before calling its tools.

    The server's tools become available on your next turn.
    Call again with a different name to switch servers.

    Args:
        server_name: The server to activate (e.g. "github", "gitlab").
    """
    # Body is never executed — _tool_executor_node intercepts this call.
    return server_name
