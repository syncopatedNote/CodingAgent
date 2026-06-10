#!/usr/bin/env python3
"""
Cyclical, Tool-Based Coding Agent powered by LangGraph

Architecture
~~~~~~~~~~~~
Uses a **supervisor-worker hub-and-spoke** model:

* **Supervisor (hub)** — An LLM-powered node that assesses the
  accumulated state, decides what to do next, and emits a tool call.
* **Tool executor (spoke)** — Runs whichever tool the supervisor chose
  and returns the result as a ``ToolMessage``.
* **Cycle** — supervisor → tool_executor → supervisor → … → END.

The supervisor has access to:

* ``ask_user``       — pauses the graph (via ``interrupt()``) to collect
                       user input through the AG-UI middleware.
* ``generate_code``  — focused LLM call for code generation / improvement.
* ``review_code``    — focused LLM call for code review / reflection.
* **MCP tools**      — dynamically loaded from GitHub, Confluence, etc.
                       for repository and documentation operations.

The graph is compiled with a ``MemorySaver`` checkpointer so that
``interrupt()`` / ``Command(resume=…)`` round-trips work across
multiple HTTP requests.
"""

import asyncio
import json
import uuid
from typing import Any, Dict, Optional, TypedDict, Annotated

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from langchain_core.runnables.config import RunnableConfig

from framework_base.llm_base import LLMFactory
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from logger import setup_logger
from settings import settings
from agents.prompts.coding_supervisor.system import (
    CODING_SUPERVISOR_SYSTEM_PROMPT,
    CODING_SUPERVISOR_DEGRADED_SUFFIX,
)
from agents.prompts.coding_supervisor.autonomous import (
    CODING_SUPERVISOR_AUTONOMOUS_PROMPT,
)
from agents.prompts.coding_supervisor.nudge import CODING_SUPERVISOR_NUDGE_PROMPT
from agents.prompts.coding_supervisor.generate_code import GENERATE_CODE_PROMPT
from agents.prompts.coding_supervisor.review_code import REVIEW_CODE_PROMPT

logger = setup_logger(__name__)


# ── Agent State ────────────────────────────────────────────────────


class CodingTaskState(TypedDict):
    """
    Shared memory for the supervisor-tool cycle.

    Uses LangGraph's ``add_messages`` reducer so every node can
    *append* messages without overwriting history.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    mode: str  # "interactive" | "autonomous"


# ── Custom Tools (non-MCP) ─────────────────────────────────────────


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
    guidelines: str,
    existing_code: str = "",
    feedback: str = "",
) -> str:
    """Generate or improve production-ready code.

    For the first generation pass only ``requirements``, ``context``,
    and ``guidelines``.  For subsequent reflection/improvement cycles
    also supply ``existing_code`` and the ``feedback`` to address.

    Args:
        requirements: What needs to be implemented.
        context: Repository structure, existing code patterns, etc.
        guidelines: Development rules / coding standards to follow.
        existing_code: Previously generated code to improve.
        feedback: Review feedback to address.
    """
    llm = _create_code_llm()
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
        guidelines=guidelines,
        extra=extra,
        feedback_instruction=(
            "5. Addresses every review-feedback point" if feedback else ""
        ),
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
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
    guidelines: str,
) -> str:
    """Review generated code and return specific, actionable feedback.

    Args:
        code: The generated code to review.
        requirements: Original requirements to validate against.
        guidelines: Development guidelines to check compliance with.
    """
    llm = _create_code_llm()

    prompt = REVIEW_CODE_PROMPT.format(
        code=code,
        requirements=requirements,
        guidelines=guidelines,
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return str(response.content)
    except Exception as exc:
        logger.error(f"Code review LLM call failed: {exc}", exc_info=True)
        return (
            f"Code review failed: {exc}\n\n"
            "The LLM service may be temporarily unavailable. "
            "Please retry or check the service configuration."
        )


def _create_code_llm():
    """Create an LLM tuned for code-generation tasks (lower temperature)."""
    kwargs: dict[str, Any] = {"temperature": 0.3}
    if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
        kwargs["base_url"] = settings.ollama_base_url
    return LLMFactory.create_llm(
        provider=settings.llm_provider,
        model_name=settings.llm_model_name,
        model_type=settings.llm_model_type,
        **kwargs,
    )


# ── Agent ──────────────────────────────────────────────────────────


class LangGraphCodingAgent:
    """
    Cyclical coding agent using the supervisor-worker pattern.

    The supervisor LLM observes the accumulated message history,
    picks the next tool, the tool executor runs it, and the result
    loops back.  ``ask_user`` triggers a LangGraph ``interrupt()``
    so the graph can pause, return control to the caller, and
    resume when the user replies.
    """

    def __init__(self):
        self._tools: Optional[list] = None
        self._tools_autonomous: Optional[list] = None
        self._mcp_tool_map: Optional[dict] = None
        self._custom_tools = [ask_user, generate_code, review_code]
        self.checkpointer = MemorySaver()

        llm_kwargs: dict[str, Any] = {"temperature": 0.5}
        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        self.graph = self._build_graph()

    # ── Tool loading ───────────────────────────────────────

    # Maximum chars for the MCP gateway tool description.
    # Keeps the tool schema within a reasonable token budget.
    _MAX_GATEWAY_DESC_CHARS = 4000

    async def _ensure_mcp_tools_loaded(self) -> None:
        """Load MCP tools once; subsequent calls are no-ops."""
        if self._mcp_tool_map is not None:
            return
        self._mcp_tool_map = {}
        self._mcp_load_error: Optional[str] = None
        try:
            raw_tools = await multi_server_mcp_client.get_tools()
            self._mcp_tool_map = {t.name: t for t in raw_tools}
            logger.info(
                f"Loaded {len(raw_tools)} MCP tools: "
                f"{list(self._mcp_tool_map.keys())}"
            )
        except Exception as exc:
            error_msg = (
                f"MCP tool servers are currently unavailable: "
                f"{exc}. GitHub, Confluence, and Jira tools "
                "will not be accessible during this session."
            )
            self._mcp_load_error = error_msg
            logger.error(error_msg)

    async def _load_tools(self, mode: str = "interactive") -> list:
        """Build the bound tool list for the given mode.

        In ``autonomous`` mode ``ask_user`` is excluded so the LLM
        cannot pause for human input even if it tries.  MCP tools
        are loaded once and reused across both modes.
        """
        await self._ensure_mcp_tools_loaded()

        if mode == "autonomous":
            combined = [t for t in self._custom_tools if t.name != "ask_user"]
        else:
            combined = list(self._custom_tools)

        if self._mcp_tool_map:
            combined.append(self._make_mcp_gateway())

        logger.info(
            f"Coding agent ({mode}) has {len(combined)} bound tools: "
            f"{[t.name for t in combined]}"
        )
        return combined

    def _make_mcp_gateway(self):
        """Build a single gateway tool for all MCP tools.

        Collapses N MCP tool schemas into one bound tool so
        the LLM's context window is not overwhelmed.  The
        gateway's description lists every available MCP tool
        with required/optional parameter info.
        """
        lines: list[str] = []
        for t in self._mcp_tool_map.values():
            params = ""
            if hasattr(t, "args_schema") and t.args_schema:
                try:
                    schema_dict = (
                        t.args_schema.model_json_schema()
                        if hasattr(t.args_schema, "model_json_schema")
                        else t.args_schema if isinstance(t.args_schema, dict) else {}
                    )
                    props = schema_dict.get("properties", {})
                    req_set = set(schema_dict.get("required", []))
                    parts: list[str] = []
                    for pname, pinfo in props.items():
                        tags: list[str] = []
                        if pname in req_set:
                            tags.append("required")
                        enum_vals = pinfo.get("enum")
                        if enum_vals:
                            tags.append("enum: " + "|".join(str(v) for v in enum_vals))
                        tag_str = f" [{', '.join(tags)}]" if tags else ""
                        parts.append(f"{pname}{tag_str}")
                    params = "(" + ", ".join(parts) + ")"
                except (AttributeError, TypeError, ValueError, KeyError) as e:
                    logger.warning(
                        "Failed to parse args_schema for tool %s: %s - skipping schema",
                        getattr(t, "name", str(t)),
                        e,
                        exc_info=True,
                    )
            desc = (t.description or "")[:100]
            lines.append(f"  - {t.name}{params}: {desc}")

        tool_listing = "\n".join(lines)

        # Truncate if the listing is very large
        if len(tool_listing) > self._MAX_GATEWAY_DESC_CHARS:
            cut = tool_listing[: self._MAX_GATEWAY_DESC_CHARS].rsplit("\n", 1)[0]
            shown = cut.count("\n") + 1
            remaining = len(lines) - shown
            tool_listing = cut + f"\n  ... and {remaining} more tools"

        mcp_map = self._mcp_tool_map  # closure capture

        @tool
        async def run_mcp_tool(tool_name: str, arguments: str = "{}") -> str:
            """Execute an MCP tool by name."""
            matched = mcp_map.get(tool_name)
            if not matched:
                return (
                    f"Tool '{tool_name}' not found. "
                    f"Available: {list(mcp_map.keys())}"
                )
            try:
                args = (
                    json.loads(arguments) if isinstance(arguments, str) else arguments
                )
            except json.JSONDecodeError as e:
                return (
                    f"Invalid JSON in arguments: {e}. "
                    "Pass a valid JSON object string."
                )

            # Pre-validate required parameters
            schema = getattr(matched, "args_schema", None)
            if schema:
                try:
                    schema_dict = (
                        schema.model_json_schema()
                        if hasattr(schema, "model_json_schema")
                        else schema if isinstance(schema, dict) else {}
                    )
                    required = schema_dict.get("required", [])
                    missing = [k for k in required if k not in args]
                    if missing:
                        # Build hint with enum values
                        props = schema_dict.get("properties", {})
                        hints: list[str] = []
                        for m in missing:
                            pinfo = props.get(m, {})
                            enum_vals = pinfo.get("enum")
                            if enum_vals:
                                hints.append(
                                    f"{m} (enum: "
                                    + "|".join(str(v) for v in enum_vals)
                                    + ")"
                                )
                            else:
                                hints.append(m)
                        return (
                            f"Missing required parameter(s) "
                            f"for '{tool_name}': "
                            f"{hints}. "
                            f"Received: {list(args.keys())}"
                        )
                except (AttributeError, TypeError, ValueError, KeyError) as e:
                    logger.warning(
                        "Failed to validate required params for tool %s: %s",
                        getattr(matched, "name", str(matched)),
                        e,
                        exc_info=True,
                    )

            try:
                result = await matched.ainvoke(args)
                return (
                    result
                    if isinstance(result, str)
                    else json.dumps(result, default=str)
                )
            except Exception as exc:
                # Surface required params in error message
                hint = ""
                if schema:
                    try:
                        schema_dict = (
                            schema.model_json_schema()
                            if hasattr(schema, "model_json_schema")
                            else schema if isinstance(schema, dict) else {}
                        )
                        req = schema_dict.get("required", [])
                        hint = f" Required params: {req}."
                    except (AttributeError, TypeError, ValueError, KeyError) as e:
                        logger.warning(
                            "Failed to inspect schema required params for tool %s: %s",
                            getattr(matched, "name", str(matched)),
                            e,
                            exc_info=True,
                        )
                return f"Error running '{tool_name}': " f"{exc}.{hint}"

        # Override description with the dynamic tool listing
        run_mcp_tool.description = (
            "Execute an MCP tool for GitHub, Confluence, "
            "or other external service operations.\n\n"
            "IMPORTANT: Include ALL [required] parameters "
            "in the arguments JSON. For parameters with "
            "enum constraints, use ONLY the listed values "
            "(case-sensitive).\n\n"
            f"Available tools:\n{tool_listing}\n\n"
            "Pass the exact tool_name and a JSON object "
            "string for arguments."
        )
        return run_mcp_tool

    # ── Graph nodes ────────────────────────────────────────

    @staticmethod
    def _prune_messages(messages: list, max_cycles: int = 15) -> list:
        """
        Limit accumulated tool-call/result cycles to ``max_cycles`` to
        prevent context explosion that causes smaller modes like Nova Lite
        to produce malformed tool-use output.

        Pruning respects Bedrock's constraint that every toolUse block
        in an AIMessage must have a matching toolResult immediately after
        it — so we drop complete (AIMessage + ToolMessages) groups as a
        unit rather than cutting at an arbitrary index.
        """
        if not messages:
            return messages

        # Always keep the first message (the user's original task)
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

    # Errors Bedrock raises when the model itself misbehaves; safe to retry
    _RETRYABLE_ERROR_SUBSTRINGS = (
        "ModelErrorException",
        "ModelTimeoutException",
        "ThrottlingException",
        "ServiceUnavailableException",
    )

    async def _supervisor_node(self, state: CodingTaskState) -> dict:
        """The hub: assess state and pick the next tool call."""
        mode = state.get("mode", "interactive")

        if mode == "autonomous":
            if self._tools_autonomous is None:
                self._tools_autonomous = await self._load_tools(mode="autonomous")
            tools = self._tools_autonomous
        else:
            if self._tools is None:
                self._tools = await self._load_tools()
            tools = self._tools

        llm_with_tools = self.llm.bind_tools(tools)

        # Select system prompt for the current mode
        if mode == "autonomous":
            system_prompt = CODING_SUPERVISOR_AUTONOMOUS_PROMPT
        else:
            system_prompt = CODING_SUPERVISOR_SYSTEM_PROMPT

        if getattr(self, "_mcp_load_error", None):
            system_prompt += CODING_SUPERVISOR_DEGRADED_SUFFIX.format(
                mcp_load_error=self._mcp_load_error
            )

        pruned = self._prune_messages(state["messages"])
        messages = [SystemMessage(content=system_prompt)] + pruned

        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = await llm_with_tools.ainvoke(messages)
                return {"messages": [response]}
            except Exception as exc:
                exc_repr = repr(exc)
                is_retryable = any(
                    s in exc_repr for s in self._RETRYABLE_ERROR_SUBSTRINGS
                )
                if is_retryable and attempt < max_retries - 1:
                    delay = 2**attempt  # 1s, 2s
                    logger.warning(
                        f"Transient model error (attempt {attempt + 1}/"
                        f"{max_retries}), retrying in {delay}s: {exc}"
                    )
                    await asyncio.sleep(delay)
                    last_exc = exc
                    continue
                last_exc = exc
                break

        logger.error(f"Supervisor LLM call failed: {last_exc}", exc_info=True)
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I'm having trouble connecting to the AI service "
                        "right now. This may be a temporary issue.\n\n"
                        f"**Error:** {last_exc}\n\n"
                        "Please try again in a moment. If the issue "
                        "persists, check that the LLM service is "
                        "configured and running."
                    )
                )
            ]
        }

    async def _tool_executor_node(self, state: CodingTaskState) -> dict:
        """The spoke: execute every tool call from the supervisor."""
        last_message = state["messages"][-1]

        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}

        results: list[ToolMessage] = []

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            call_id = tc["id"]

            logger.info(
                f"Executing tool: {name} | "
                f"args snippet: {json.dumps(args, default=str)[:300]}"
            )

            try:
                all_tools = self._tools or []
                matched = next((t for t in all_tools if t.name == name), None)
                if matched:
                    result = await matched.ainvoke(args)
                    content = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, default=str)
                    )
                else:
                    content = (
                        f"Tool '{name}' is not available. "
                        "This may mean the required MCP server "
                        "(GitHub, Confluence, etc.) is not "
                        "connected. Ask the user to provide the "
                        "information directly instead."
                    )
                    logger.error(f"Tool not found: {name}")
            except GraphInterrupt:
                raise
            except ConnectionError as exc:
                content = (
                    f"Connection to '{name}' failed: {exc}. "
                    "The service may be down or unreachable. "
                    "Ask the user if they can provide the "
                    "information directly."
                )
                logger.error(content, exc_info=True)
            except TimeoutError as exc:
                content = (
                    f"Tool '{name}' timed out: {exc}. "
                    "The request took too long to complete. "
                    "You may retry once, or ask the user to "
                    "provide the information directly."
                )
                logger.error(content, exc_info=True)
            except Exception as exc:
                content = (
                    f"Tool '{name}' encountered an error: {exc}. "
                    "Try an alternative approach or ask the user "
                    "to provide the information directly."
                )
                logger.error(f"Error executing {name}: {exc}", exc_info=True)

            results.append(ToolMessage(content=content, tool_call_id=call_id))

        return {"messages": results}

    # ── Routing ────────────────────────────────────────────

    # Phrases that signal the LLM is narrating intent rather
    # than acting.  Used by _route_after_supervisor to catch
    # premature exits.
    _NARRATION_MARKERS = (
        "i will now",
        "i'll now",
        "let me now",
        "next, i will",
        "next i will",
        "i'm going to",
        "i am going to",
        "let me proceed",
        "i'll proceed",
        "now i need to",
        "now i will",
        "i'll analyze",
        "i will analyze",
        "i'll examine",
        "i will examine",
    )

    @staticmethod
    def _route_after_supervisor(state: CodingTaskState) -> str:
        """Route after supervisor: tools → execute, end → finish,
        or nudge → re-prompt the LLM if it narrated instead of
        acting.
        """
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"

        # Check if the supervisor just received tool results
        # and responded with narration instead of acting.
        content = getattr(last, "content", "") or ""
        msgs = state["messages"]
        if len(msgs) >= 2:
            prev = msgs[-2]
            is_after_tool = (
                isinstance(prev, ToolMessage) or getattr(prev, "type", None) == "tool"
            )
            if is_after_tool:
                lower = content.lower()
                if any(m in lower for m in LangGraphCodingAgent._NARRATION_MARKERS):
                    return "nudge"

        return "end"

    async def _nudge_node(self, state: CodingTaskState) -> dict:
        """Re-prompt the supervisor when it narrated its plan
        instead of making tool calls."""
        logger.warning("Supervisor narrated instead of acting — nudging")
        return {"messages": [SystemMessage(content=CODING_SUPERVISOR_NUDGE_PROMPT)]}

    # ── Graph construction ─────────────────────────────────

    def _build_graph(self):
        """Build the cyclical supervisor → tools → supervisor graph."""
        workflow = StateGraph(CodingTaskState)

        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("tools", self._tool_executor_node)
        workflow.add_node("nudge", self._nudge_node)

        workflow.set_entry_point("supervisor")

        workflow.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {"tools": "tools", "nudge": "nudge", "end": END},
        )

        workflow.add_edge("tools", "supervisor")
        workflow.add_edge("nudge", "supervisor")

        return workflow.compile(checkpointer=self.checkpointer)

    # ── Public API ─────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        thread_id: Optional[str] = None,
        *,
        resume_value: Any = None,
        mode: str = "interactive",
    ) -> Dict[str, Any]:
        """Start or resume the coding agent.

        Parameters
        ----------
        user_input : str
            The user's message (used on first invocation;
            ignored when *resume_value* is supplied).
        thread_id : str, optional
            Conversation thread ID for checkpointing.
            A new UUID is generated when omitted.
        resume_value : Any, optional
            The user's response when resuming from an interrupt.
        mode : str
            ``"interactive"`` (default) enables ``ask_user`` and
            the interactive system prompt.  ``"autonomous"``
            excludes ``ask_user`` from the tool list and uses the
            autonomous prompt — suitable for unattended processing.

        Returns
        -------
        dict
            ``response``  — final text (str or None)
            ``interrupt`` — interrupt payload (dict or None)
            ``thread_id`` — same thread_id (pass back on resume)
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100,
        }

        try:
            if resume_value is not None:
                # mode is restored from the checkpoint — no need to re-pass
                result = await self.graph.ainvoke(Command(resume=resume_value), config)
            else:
                result = await self.graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "mode": mode,
                    },
                    config,
                )

            # — Check for a pending interrupt ———————————
            snapshot = self.graph.get_state(config)

            if snapshot.tasks:
                for task in snapshot.tasks:
                    if getattr(task, "interrupts", None):
                        interrupt_payload = task.interrupts[0].value
                        logger.info(
                            f"Coding agent interrupted: " f"{interrupt_payload}"
                        )
                        return {
                            "response": None,
                            "interrupt": interrupt_payload,
                            "thread_id": thread_id,
                        }

            # — No interrupt → task completed ——————————
            final_msg = result["messages"][-1]
            return {
                "response": getattr(final_msg, "content", str(final_msg)),
                "interrupt": None,
                "thread_id": thread_id,
            }

        except RecursionError:
            logger.error("Graph hit recursion limit", exc_info=True)
            return {
                "response": (
                    "The coding workflow exceeded its maximum "
                    "number of steps. This usually means the "
                    "agent got stuck in a loop.\n\n"
                    "Please start a new conversation and try "
                    "simplifying your request."
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }

        except Exception as exc:
            logger.error(f"Coding agent error: {exc}", exc_info=True)
            error_type = type(exc).__name__
            return {
                "response": (
                    "Something went wrong during the coding "
                    f"workflow.\n\n"
                    f"**{error_type}:** {exc}\n\n"
                    "This may be a temporary issue. You can "
                    "try again, or start a new conversation "
                    "if the problem persists."
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }
