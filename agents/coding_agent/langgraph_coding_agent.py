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
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.types import Command
from langchain_core.runnables.config import RunnableConfig

from framework_base.llm_base import LLMFactory
from framework_base.mcp_servers.multi_server_mcp_client import (
    multi_server_mcp_client,
    loaded_server_names,
)
from logger import setup_logger
from settings import settings
from agents.prompts.coding_supervisor.system import CODING_SUPERVISOR_SYSTEM_PROMPT
from agents.prompts.coding_supervisor.autonomous import (
    CODING_SUPERVISOR_AUTONOMOUS_PROMPT,
)
from agents.prompts.coding_supervisor.nudge import CODING_SUPERVISOR_NUDGE_PROMPT
from .custom_tools import (
    ask_user,
    generate_code,
    review_code,
    select_tools,
    store_coding_guidelines,
)

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
    active_mcp_server: str  # name of the currently active MCP server, "" if none
    coding_guidelines: str  # fetched once, injected into every generate/review call


# Phrases that signal the LLM is narrating intent rather than acting.
# Used by _route_after_supervisor to catch premature exits.
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
        # Per-server tool cache: populated lazily the first time each server
        # is activated via select_tools.  Never evicted — tools are stable
        # for the lifetime of the agent instance.
        self._mcp_tools_by_server: dict[str, list] = {}
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

        # Stamp live server names into the module-level select_tools description
        # so the LLM knows exactly which server names are valid.
        # loaded_server_names comes from multi_server_mcp_client — single source of truth.
        servers_str = (
            ", ".join(loaded_server_names) if loaded_server_names else "none configured"
        )
        select_tools.description = (
            "Activate tools for a specific MCP server before calling any of its tools. "
            "The server's tools become available on your next turn. "
            "Call again with a different name to switch servers.\n\n"
            f"Available servers: {servers_str}\n\n"
            "Args:\n"
            f"    server_name: The server to activate. One of: {servers_str}."
        )

        self._custom_tools = [
            ask_user,
            generate_code,
            review_code,
            store_coding_guidelines,
            select_tools,
        ]
        self.graph = self._build_graph()

    async def _load_server_tools(self, server_name: str) -> list:
        """Return tools for *server_name*, loading from the MCP client once.

        Results are cached in ``_mcp_tools_by_server`` so every subsequent
        call for the same server is a pure dict lookup — no network call.
        """
        if server_name in self._mcp_tools_by_server:
            logger.debug(f"Using cached tools for MCP server '{server_name}'")
            return self._mcp_tools_by_server[server_name]

        try:
            tools = await multi_server_mcp_client.get_tools(server_name=server_name)
            self._mcp_tools_by_server[server_name] = tools
            logger.info(
                f"Loaded and cached {len(tools)} tools for MCP server '{server_name}': "
                f"{[t.name for t in tools]}"
            )
            return tools
        except Exception as exc:
            logger.error(
                f"Failed to load tools for MCP server '{server_name}': {exc}",
                exc_info=True,
            )
            return []

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

        # Base custom tools — drop ask_user in autonomous mode
        if mode == "autonomous":
            base_tools = [t for t in self._custom_tools if t.name != "ask_user"]
        else:
            base_tools = list(self._custom_tools)

        # Extend with the active server's tools (cached, no network call)
        active_server = state.get("active_mcp_server", "")
        server_tools = self._mcp_tools_by_server.get(active_server, [])
        tools = base_tools + server_tools

        logger.debug(
            f"Supervisor bound tools ({mode}): "
            f"{[t.name for t in base_tools]} + {len(server_tools)} from '{active_server}'"
        )

        llm_with_tools = self.llm.bind_tools(tools)

        system_prompt = (
            CODING_SUPERVISOR_AUTONOMOUS_PROMPT
            if mode == "autonomous"
            else CODING_SUPERVISOR_SYSTEM_PROMPT
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

    # Maximum attempts per tool call. ValueError (bad input) exits immediately;
    # transient errors (network, timeout, unexpected) use the full budget.
    _MAX_TOOL_ATTEMPTS = 3

    async def _tool_executor_node(self, state: CodingTaskState) -> dict:
        """The spoke: execute every tool call from the supervisor.

        Each tool call gets up to ``_MAX_TOOL_ATTEMPTS`` attempts:
        - ``ValueError`` (bad input: invalid JSON, missing params, tool not
          found) — fails immediately, no retry.
        - ``ConnectionError`` / ``TimeoutError`` — retried with exponential
          back-off up to the attempt budget.
        - Any other exception — retried once, then fails.

        On exhaustion the tool call result is a ``TERMINAL TOOL FAILURE``
        message so the supervisor knows not to retry.
        """
        last_message = state["messages"][-1]

        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}

        results: list[ToolMessage] = []
        # Carries any state fields updated during this batch (e.g. active_mcp_server).
        state_update: dict = {"messages": results}

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            call_id = tc["id"]

            logger.info(
                f"Executing tool: {name} | "
                f"args snippet: {json.dumps(args, default=str)[:300]}"
            )

            # ── store_coding_guidelines: persist guidelines in state ──────────
            if name == "store_coding_guidelines":
                guidelines_content = args.get("content", "").strip()
                if guidelines_content:
                    state_update["coding_guidelines"] = guidelines_content
                    result_content = (
                        f"Coding guidelines stored ({len(guidelines_content)} chars). "
                        "They will be automatically applied to all "
                        "generate_code and review_code calls."
                    )
                    logger.info(
                        f"Stored coding guidelines ({len(guidelines_content)} chars)"
                    )
                else:
                    result_content = "No guidelines content provided — nothing stored."
                results.append(
                    ToolMessage(content=result_content, tool_call_id=call_id)
                )
                continue

            # ── select_tools: activate a server and cache its tools ───────────
            if name == "select_tools":
                server_name = args.get("server_name", "").strip()
                server_tools = await self._load_server_tools(server_name)
                if server_tools:
                    state_update["active_mcp_server"] = server_name
                    tool_names = "\n".join(f"  - {t.name}" for t in server_tools)
                    content = (
                        f"Activated {len(server_tools)} tools for server '{server_name}':\n"
                        f"{tool_names}\n\n"
                        "Call these tools directly in your next response."
                    )
                    logger.info(
                        f"Activated MCP server '{server_name}' "
                        f"({len(server_tools)} tools)"
                    )
                else:
                    known = list(self._mcp_tools_by_server.keys())
                    content = (
                        f"TERMINAL TOOL FAILURE — server '{server_name}' could not "
                        "be loaded or has no tools. "
                        f"Previously loaded servers: {known or 'none'}. "
                        "Do NOT retry this call."
                    )
                    logger.error(f"Failed to activate MCP server '{server_name}'")
                results.append(ToolMessage(content=content, tool_call_id=call_id))
                continue

            # ── all other tools: search custom tools then active server ───────
            active_server = state_update.get(
                "active_mcp_server", state.get("active_mcp_server", "")
            )
            all_tools = list(self._custom_tools) + self._mcp_tools_by_server.get(
                active_server, []
            )
            matched = next((t for t in all_tools if t.name == name), None)

            if not matched:
                content = (
                    f"TERMINAL TOOL FAILURE — '{name}' is not available. "
                    f"Active server: '{active_server}'. "
                    "Call select_tools with the correct server name first, "
                    "then retry the tool call. Do NOT retry without switching servers."
                )
                logger.error(
                    f"Tool not found: '{name}' (active server: '{active_server}')"
                )
                results.append(ToolMessage(content=content, tool_call_id=call_id))
                continue

            # Inject guidelines from state so the LLM doesn't need to pass them
            if name in {"generate_code", "review_code"}:
                args = {
                    **args,
                    "guidelines": state_update.get(
                        "coding_guidelines",
                        state.get("coding_guidelines", ""),
                    ),
                }

            content = ""
            for attempt in range(self._MAX_TOOL_ATTEMPTS):
                try:
                    result = await matched.ainvoke(args)
                    content = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, default=str)
                    )
                    break  # success

                except GraphInterrupt:
                    raise

                except ValueError as exc:
                    # Bad input — retrying with identical args will not help.
                    content = (
                        f"TERMINAL TOOL FAILURE — '{name}' rejected the request: "
                        f"{exc}. "
                        "Do NOT retry with the same arguments."
                    )
                    logger.error(
                        f"Non-retryable error for tool '{name}': {exc}",
                        exc_info=True,
                    )
                    break

                except (ConnectionError, TimeoutError) as exc:
                    if attempt < self._MAX_TOOL_ATTEMPTS - 1:
                        delay = 2**attempt
                        logger.warning(
                            f"Transient error for tool '{name}' "
                            f"(attempt {attempt + 1}/{self._MAX_TOOL_ATTEMPTS}), "
                            f"retrying in {delay}s: {exc}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    content = (
                        f"TERMINAL TOOL FAILURE — '{name}' failed after "
                        f"{self._MAX_TOOL_ATTEMPTS} attempts due to a connection "
                        f"or timeout error: {exc}. "
                        "Do NOT retry this tool call."
                    )
                    logger.error(
                        f"Tool '{name}' exhausted retries: {exc}", exc_info=True
                    )

                except Exception as exc:
                    if attempt == 0:
                        logger.warning(
                            f"Unexpected error for tool '{name}' "
                            f"(attempt 1/{self._MAX_TOOL_ATTEMPTS}), retrying: {exc}"
                        )
                        continue
                    content = (
                        f"TERMINAL TOOL FAILURE — '{name}' encountered an "
                        f"unexpected error: {exc}. "
                        "Do NOT retry this tool call."
                    )
                    logger.error(
                        f"Tool '{name}' failed after retry: {exc}", exc_info=True
                    )
                    break

            results.append(ToolMessage(content=content, tool_call_id=call_id))

        return state_update

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
            if isinstance(prev, ToolMessage) or getattr(prev, "type", None) == "tool":
                lower = content.lower()
                if any(m in lower for m in _NARRATION_MARKERS):
                    return "nudge"

        return "end"

    async def _nudge_node(self, state: CodingTaskState) -> dict:
        """Re-prompt the supervisor when it narrated its plan
        instead of making tool calls."""
        logger.warning("Supervisor narrated instead of acting — nudging")
        return {"messages": [SystemMessage(content=CODING_SUPERVISOR_NUDGE_PROMPT)]}

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
            "recursion_limit": 20,
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
                        "active_mcp_server": "",
                        "coding_guidelines": "",
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
