#!/usr/bin/env python3
"""
Context Collector Agent

A focused supervisor-worker agent whose only job is to gather everything the
coding agent needs and pack it into a :class:`ContextBundle`.

Unlike the coding agent it binds a **fixed** set of coarse, per-platform
sub-collector tools (``jira_collector``, ``confluence_collector``,
``gitlab_collector``, ``github_collector``) — no dynamic MCP-server activation.
The supervisor LLM picks which sub-collector to call based on the references in
the user's prompt; each sub-collector runs a deterministic MCP sequence and
returns text. When everything is gathered the LLM calls ``submit_context``,
which the tool-executor intercepts to build the bundle and end the run.

* Interactive mode binds ``ask_user`` (pauses via ``interrupt()``).
* Autonomous mode omits ``ask_user`` and fails gracefully instead.
"""

import uuid
from typing import Any, Optional, TypedDict, Annotated

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.types import Command

from framework_base.llm_base import LLMFactory
from logger import setup_logger
from settings import settings
from agents.prompts.context_collector.system import (
    CONTEXT_COLLECTOR_SYSTEM_PROMPT,
)
from agents.prompts.context_collector.autonomous import (
    CONTEXT_COLLECTOR_AUTONOMOUS_PROMPT,
)
from agents.prompts.context_collector.nudge import (
    CONTEXT_COLLECTOR_NUDGE_PROMPT,
)
from ..common_helpers import (
    prune_tool_cycles,
    invoke_llm_with_retry,
    execute_tool_with_retry,
)
from .context_bundle import ContextBundle
from .collector_tools import ask_user, submit_context
from .jira_collector import jira_collector
from .confluence_collector import confluence_collector
from .gitlab_collector import gitlab_collector
from .github_collector import github_collector

logger = setup_logger(__name__)


# Phrases that signal the LLM is narrating intent rather than acting.
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
    "now i will",
)


class CollectorState(TypedDict):
    """Shared memory for the collector supervisor-tool cycle."""

    messages: Annotated[list[BaseMessage], add_messages]
    mode: str  # "interactive" | "autonomous"
    context_bundle: Optional[ContextBundle]


class ContextCollectorAgent:
    """Gathers requirements, design, and guidelines into a ContextBundle."""

    def __init__(self) -> None:
        self.checkpointer = MemorySaver()

        llm_kwargs: dict[str, Any] = {"temperature": 0.3}
        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        # Fixed tool set — the four sub-collectors plus the terminal
        # submit_context. ask_user is added per-mode in the supervisor node.
        self._collector_tools = [
            jira_collector,
            confluence_collector,
            gitlab_collector,
            github_collector,
            submit_context,
        ]
        self.graph = self._build_graph()

    # ── Nodes ───────────────────────────────────────────────────────

    async def _supervisor_node(self, state: CollectorState) -> dict:
        """Assess gathered context and pick the next sub-collector call."""
        mode = state.get("mode", "interactive")

        tools = list(self._collector_tools)
        if mode != "autonomous":
            tools = tools + [ask_user]

        llm_with_tools = self.llm.bind_tools(tools)
        system_prompt = (
            CONTEXT_COLLECTOR_AUTONOMOUS_PROMPT
            if mode == "autonomous"
            else CONTEXT_COLLECTOR_SYSTEM_PROMPT
        )

        pruned = prune_tool_cycles(state["messages"])
        messages = [SystemMessage(content=system_prompt)] + pruned
        response = await invoke_llm_with_retry(llm_with_tools, messages)
        return {"messages": [response]}

    async def _tool_executor_node(self, state: CollectorState) -> dict:
        """Execute the supervisor's tool calls; intercept submit_context."""
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}

        results: list[ToolMessage] = []
        state_update: dict = {"messages": results}

        # All tools that could be invoked (incl. ask_user, regardless of mode —
        # if the LLM emitted it in autonomous mode we simply won't find it).
        all_tools = list(self._collector_tools) + [ask_user]

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            call_id = tc["id"]

            # ── submit_context: build the bundle and end ─────────────
            if name == "submit_context":
                bundle = ContextBundle(
                    requirements=(args.get("requirements") or "").strip(),
                    repository_reference=(
                        args.get("repository_reference") or ""
                    ).strip(),
                    development_guidelines=(
                        args.get("development_guidelines") or ""
                    ).strip(),
                    confluence_design_details=(
                        args.get("confluence_design_details") or ""
                    ).strip(),
                    source_ref=(args.get("source_ref") or "").strip(),
                    target_branch=(args.get("target_branch") or "").strip()
                    or settings.coding_base_branch,
                    status="complete",
                )
                state_update["context_bundle"] = bundle
                results.append(
                    ToolMessage(
                        content="Context captured — collection complete.",
                        tool_call_id=call_id,
                    )
                )
                logger.info(
                    "Context collected: repo="
                    f"{bundle.repository_reference or '(none)'}, "
                    f"guidelines={len(bundle.development_guidelines)} chars, "
                    f"design={len(bundle.confluence_design_details)} chars"
                )
                continue

            matched = next((t for t in all_tools if t.name == name), None)
            if not matched:
                results.append(
                    ToolMessage(
                        content=(
                            f"TERMINAL TOOL FAILURE — '{name}' is not an "
                            "available collector tool. Use one of: "
                            f"{[t.name for t in all_tools]}."
                        ),
                        tool_call_id=call_id,
                    )
                )
                continue

            content = await execute_tool_with_retry(matched, args)
            results.append(ToolMessage(content=content, tool_call_id=call_id))

        return state_update

    async def _nudge_node(self, state: CollectorState) -> dict:
        """Re-prompt when the supervisor narrated instead of acting."""
        logger.warning("Collector narrated instead of acting — nudging")
        return {"messages": [SystemMessage(content=CONTEXT_COLLECTOR_NUDGE_PROMPT)]}

    # ── Routing ─────────────────────────────────────────────────────

    @staticmethod
    def _route_after_supervisor(state: CollectorState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"

        content = (getattr(last, "content", "") or "").lower()
        msgs = state["messages"]
        if len(msgs) >= 2:
            prev = msgs[-2]
            is_tool = isinstance(prev, ToolMessage) or (
                getattr(prev, "type", None) == "tool"
            )
            if is_tool and any(m in content for m in _NARRATION_MARKERS):
                return "nudge"
        return "end"

    @staticmethod
    def _route_after_tools(state: CollectorState) -> str:
        # submit_context populated the bundle → finish; otherwise loop back.
        return "end" if state.get("context_bundle") is not None else "supervisor"

    def _build_graph(self):
        workflow = StateGraph(CollectorState)
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("tools", self._tool_executor_node)
        workflow.add_node("nudge", self._nudge_node)

        workflow.set_entry_point("supervisor")
        workflow.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {"tools": "tools", "nudge": "nudge", "end": END},
        )
        workflow.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"supervisor": "supervisor", "end": END},
        )
        workflow.add_edge("nudge", "supervisor")
        return workflow.compile(checkpointer=self.checkpointer)

    # ── Entry point ─────────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        thread_id: Optional[str] = None,
        *,
        resume_value: Any = None,
        mode: str = "interactive",
    ) -> dict:
        """Collect context for *user_input*.

        Returns a dict with:
            ``context``   — a ContextBundle (status "complete"/"failed") or None
                            when the run is paused on an interrupt.
            ``interrupt`` — interrupt payload (dict) or None.
            ``thread_id`` — pass back on resume.
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25,
        }

        try:
            if resume_value is not None:
                result = await self.graph.ainvoke(Command(resume=resume_value), config)
            else:
                result = await self.graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "mode": mode,
                        "context_bundle": None,
                    },
                    config,
                )

            # — Pending interrupt (ask_user) ————————————
            snapshot = self.graph.get_state(config)
            if snapshot.tasks:
                for task in snapshot.tasks:
                    if getattr(task, "interrupts", None):
                        payload = task.interrupts[0].value
                        logger.info(f"Collector interrupted: {payload}")
                        return {
                            "context": None,
                            "interrupt": payload,
                            "thread_id": thread_id,
                        }

            bundle = result.get("context_bundle")
            if bundle is None:
                # Ended without submitting — treat the final text as the reason.
                final = result["messages"][-1]
                reason = (
                    getattr(final, "content", "")
                    or "Context collection ended without a result."
                )
                bundle = ContextBundle(status="failed", failure_reason=str(reason))
            return {
                "context": bundle,
                "interrupt": None,
                "thread_id": thread_id,
            }

        except RecursionError:
            logger.error("Collector hit recursion limit", exc_info=True)
            return {
                "context": ContextBundle(
                    status="failed",
                    failure_reason=(
                        "Context collection exceeded its maximum number of "
                        "steps (possible loop)."
                    ),
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }
        except Exception as exc:
            logger.error(f"Context collector error: {exc}", exc_info=True)
            return {
                "context": ContextBundle(
                    status="failed",
                    failure_reason=f"{type(exc).__name__}: {exc}",
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }
