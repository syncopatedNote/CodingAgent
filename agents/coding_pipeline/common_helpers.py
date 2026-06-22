"""
Shared helpers for the supervisor-worker agents in this package.

Both the context collector and the coding agent run the same LangGraph
supervisor → tool-executor loop, so the genuinely-identical, fiddly bits
live here as plain functions (no base class, no hooks):

* ``prune_tool_cycles``       — cap accumulated tool-call cycles to keep
                                context small and Bedrock's
                                toolUse/toolResult pairing intact.
* ``execute_tool_with_retry`` — run a single tool call with the retry
                                ladder (no retry on bad input, back-off
                                on transient errors).
* ``invoke_llm_with_retry``   — call a tool-bound LLM with retries on
                                transient model errors.
"""

import asyncio
import random

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.errors import GraphInterrupt

from logger import setup_logger

logger = setup_logger(__name__)


# ── Message pruning ────────────────────────────────────────────────


def prune_tool_cycles(messages: list, max_cycles: int = 15) -> list:
    """
    Limit accumulated tool-call/result cycles to ``max_cycles`` to prevent
    context explosion that causes smaller models like Nova Lite to produce
    malformed tool-use output.

    Pruning respects Bedrock's constraint that every toolUse block in an
    AIMessage must have a matching toolResult immediately after it — so we
    drop complete (AIMessage + ToolMessages) groups as a unit rather than
    cutting at an arbitrary index.
    """
    if not messages:
        return messages

    # Always keep the first message (the original task)
    anchor = messages[:1]
    rest = messages[1:]

    # Group rest into tool-call cycles and plain messages
    groups: list[list] = []
    i = 0
    while i < len(rest):
        msg = rest[i]
        if getattr(msg, "tool_calls", None):
            # AIMessage with tool calls — collect it + its ToolMessages
            group = [msg]
            i += 1
            while i < len(rest) and isinstance(rest[i], ToolMessage):
                group.append(rest[i])
                i += 1
            groups.append(group)
        else:
            groups.append([msg])
            i += 1

    if len(groups) > max_cycles:
        groups = groups[-max_cycles:]

    return anchor + [m for g in groups for m in g]


# ── LLM invocation with retry ──────────────────────────────────────

# Errors from Bedrock, OpenAI, and other providers that are safe to
# retry — transient service/capacity issues, not bad inputs or logic
# errors.
RETRYABLE_MODEL_ERRORS = (
    "ModelTimeoutException",
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "overloaded",
    "rate limit",
    "rate_limit",
    "too many requests",
    "529",  # Anthropic overloaded HTTP status
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
)

# ModelErrorException covers both transient failures AND structural
# problems with the message history (e.g. "invalid sequence as part of
# ToolUse"). The latter cannot be fixed by retrying with the same
# messages, so we exclude those phrases from the retryable set.
_NON_RETRYABLE_MODEL_ERROR_PHRASES = (
    "invalid sequence",
    "invalid tool use",
    "malformed tool",
)


def _is_retryable_model_error(exc: Exception) -> bool:
    exc_repr = repr(exc).lower()
    if "modelerrorexception" in exc_repr:
        return not any(p in exc_repr for p in _NON_RETRYABLE_MODEL_ERROR_PHRASES)
    return any(s.lower() in exc_repr for s in RETRYABLE_MODEL_ERRORS)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with ±25% jitter: 2s, 4s, 8s, 16s, …"""
    base = 2 ** (attempt + 1)
    return base * (0.75 + random.random() * 0.5)  # nosec B311


def _extract_bedrock_status_code(exc: Exception) -> str:
    """Return a log-ready string with originalStatusCode if present."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error", {})
    code = error.get("originalStatusCode") or (
        response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    )
    return f" [originalStatusCode={code}]" if code else ""


async def invoke_llm_with_retry(
    llm_with_tools,
    messages: list[BaseMessage],
    max_retries: int = 5,
) -> AIMessage:
    """Invoke a tool-bound LLM, retrying transient model errors with
    back-off.

    Returns the model's ``AIMessage`` on success. On exhaustion returns
    a plain ``AIMessage`` describing the failure so the caller can
    surface it rather than crashing the graph.

    Backoff schedule (with ±25% jitter): 2s, 4s, 8s, 16s across 5
    attempts, giving ~30s of total wait time before giving up — enough
    for Bedrock throttling windows to clear.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await llm_with_tools.ainvoke(messages)
        except Exception as exc:
            status = _extract_bedrock_status_code(exc)
            retryable = _is_retryable_model_error(exc)
            if retryable and attempt < max_retries - 1:
                delay = _backoff_delay(attempt)
                logger.warning(
                    f"Transient model error (attempt {attempt + 1}/"
                    f"{max_retries}){status}, "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                await asyncio.sleep(delay)
                last_exc = exc
                continue
            if not retryable:
                logger.error(
                    f"Non-retryable model error{status}: {exc}",
                    exc_info=True,
                )
            last_exc = exc
            break

    logger.error(
        f"LLM call failed after {max_retries} attempts: {last_exc}",
        exc_info=True,
    )
    return AIMessage(
        content=(
            "I'm having trouble connecting to the AI service right now."
            " This may be a temporary issue.\n\n"
            f"**Error:** {last_exc}\n\n"
            "Please try again in a moment. If the issue persists, check"
            " that the LLM service is configured and running."
        )
    )


# ── Per-tool execution with retry ──────────────────────────────────

# Maximum attempts per tool call. ValueError (bad input) exits
# immediately; transient errors (network, timeout, unexpected) use the
# full budget.
MAX_TOOL_ATTEMPTS = 3


async def execute_tool_with_retry(
    matched_tool, args: dict, max_attempts: int = MAX_TOOL_ATTEMPTS
) -> str | dict:
    """Invoke ``matched_tool`` with ``args``, applying the retry ladder.

    - ``GraphInterrupt`` propagates (it is how ``ask_user`` pauses the
      graph).
    - ``ValueError`` (bad input) fails immediately — retrying won't
      help.
    - ``ConnectionError`` / ``TimeoutError`` retry with exponential
      back-off.
    - Any other exception retries once, then fails.

    On exhaustion the returned string is prefixed with
    ``TERMINAL TOOL FAILURE`` so the supervisor LLM knows not to retry.
    """
    name = getattr(matched_tool, "name", "tool")
    content = ""
    for attempt in range(max_attempts):
        try:
            result = await matched_tool.ainvoke(args)
            if isinstance(result, (str, dict)):
                return result
            return __import__("json").dumps(result, default=str)

        except GraphInterrupt:
            raise

        except ValueError as exc:
            logger.error(
                f"Non-retryable error for tool '{name}': {exc}",
                exc_info=True,
            )
            return (
                f"TERMINAL TOOL FAILURE — '{name}' rejected the"
                f" request: {exc}. "
                "Do NOT retry with the same arguments."
            )

        except (ConnectionError, TimeoutError) as exc:
            if attempt < max_attempts - 1:
                delay = 2**attempt
                logger.warning(
                    f"Transient error for tool '{name}' "
                    f"(attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {delay}s: {exc}"
                )
                await asyncio.sleep(delay)
                continue
            logger.error(
                f"Tool '{name}' exhausted retries: {exc}",
                exc_info=True,
            )
            content = (
                f"TERMINAL TOOL FAILURE — '{name}' failed after"
                f" {max_attempts} attempts due to a connection or"
                f" timeout error: {exc}. "
                "Do NOT retry this tool call."
            )

        except Exception as exc:
            if attempt == 0:
                logger.warning(
                    f"Unexpected error for tool '{name}' "
                    f"(attempt 1/{max_attempts}), retrying: {exc}"
                )
                continue
            logger.error(
                f"Tool '{name}' failed after retry: {exc}",
                exc_info=True,
            )
            content = (
                f"TERMINAL TOOL FAILURE — '{name}' encountered an"
                f" unexpected error: {exc}. "
                "Do NOT retry this tool call."
            )
            break

    return content
