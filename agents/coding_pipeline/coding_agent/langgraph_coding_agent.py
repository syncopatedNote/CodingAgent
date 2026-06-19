#!/usr/bin/env python3
"""
Cyclical, Tool-Based Coding Agent powered by LangGraph

Architecture
~~~~~~~~~~~~
Uses a **supervisor-worker hub-and-spoke** model:

* **Supervisor (hub)** — An LLM-powered node that assesses the accumulated
  state, decides what to do next, and emits a tool call.
* **Tool executor (spoke)** — Runs whichever tool the supervisor chose and
  returns the result as a ``ToolMessage``.
* **Cycle** — supervisor → tool_executor → supervisor → … → END.

This agent does **not** gather context. It receives a fully-populated
:class:`ContextBundle` (requirements, design, mandatory guidelines, target
repo/branch) from the :class:`CodingPipeline` and runs a focused
generate → review → push loop. It has no ``ask_user`` — all clarification
happens earlier in the context collector.

The supervisor has access to:

* ``generate_code``  — focused LLM call for code generation / improvement.
* ``review_code``    — focused LLM call for code review / reflection.
* ``select_tools`` + **MCP tools** — dynamically loaded (GitHub/GitLab) for
  read-only repository searches and the final branch push.
"""

import re
import uuid
from typing import Any, Dict, Optional, TypedDict, Annotated

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

from framework_base.llm_base import LLMFactory
from framework_base.mcp_servers.multi_server_mcp_client import (
    loaded_server_names,
)
from logger import setup_logger
from settings import settings
from agents.prompts.coding_supervisor.system import (
    CODING_SUPERVISOR_SYSTEM_PROMPT,
)
from agents.prompts.coding_supervisor.autonomous import (
    CODING_SUPERVISOR_AUTONOMOUS_PROMPT,
)
from agents.prompts.coding_supervisor.nudge import CODING_SUPERVISOR_NUDGE_PROMPT
from ..common_helpers import (
    prune_tool_cycles,
    invoke_llm_with_retry,
    execute_tool_with_retry,
)
from ..collector_agent.context_bundle import ContextBundle
from .custom_tools import generate_code, review_code, select_tools
from .repo_mcp_helpers import fetch_existing_code, load_server_tools_cached

logger = setup_logger(__name__)


# ── Agent State ────────────────────────────────────────────────────


class CodingTaskState(TypedDict):
    """Shared memory for the supervisor-tool cycle."""

    messages: Annotated[list[BaseMessage], add_messages]
    mode: str  # "interactive" | "autonomous"
    active_mcp_server: str  # name of the currently active MCP server, "" if none
    coding_guidelines: str  # seeded from the bundle, injected into gen/review
    # Repository coordinates seeded from the bundle. The executor uses these to
    # fetch existing file contents (read-before-write) without the LLM's help.
    repo_source: str  # "github" | "gitlab"
    repo_owner: str
    repo_reference: str  # repo name (github) or project id (gitlab)
    repo_base_branch: str


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
    "now i need to",
    "now i will",
    "i'll analyze",
    "i will analyze",
    "i'll examine",
    "i will examine",
)


def _render_task(bundle: ContextBundle) -> str:
    """Render the collected context into the seed task message."""
    owner = (
        bundle.repository_owner
        or settings.coding_repository_owner
        or "(configured owner)"
    )
    design = bundle.confluence_design_details.strip() or "(none provided)"
    git_issue = bundle.git_issue_details.strip() or "(none provided)"
    base_branch = bundle.base_branch or settings.coding_base_branch
    return (
        "Implement the following change. All context has already been "
        "gathered for you — do NOT ask for more.\n\n"
        f"REPOSITORY PROVIDER: {bundle.repo_source or '(n/a)'}\n"
        f"REPOSITORY: {bundle.repository_reference or '(n/a)'}\n"
        f"REPOSITORY OWNER: {owner}\n"
        f"TARGET BASE BRANCH (branch FROM this): {base_branch}\n\n"
        f"REQUIREMENTS:\n{bundle.requirements}\n\n"
        f"LINKED ISSUE DETAILS:\n{git_issue}\n\n"
        f"DESIGN DETAILS:\n{design}\n\n"
        "Development guidelines are already loaded and are applied "
        "automatically to every generate_code and review_code call. The "
        "current contents of any existing file you target are injected "
        "automatically — do NOT fetch a file before editing it."
    )


class LangGraphCodingAgent:
    """Cyclical coding agent using the supervisor-worker pattern.

    Consumes a :class:`ContextBundle` and runs generate → review → push.
    """

    def __init__(self):
        # Per-server tool cache: populated lazily the first time each server
        # is activated via select_tools. Never evicted — tools are stable for
        # the lifetime of the agent instance.
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

        # Stamp live server names into the select_tools description so the LLM
        # knows exactly which server names are valid.
        servers_str = (
            ", ".join(loaded_server_names) if loaded_server_names else "none configured"
        )
        select_tools.description = (
            "Activate tools for a specific MCP server before calling any of "
            "its tools. The server's tools become available on your next "
            "turn. Call again with a different name to switch servers.\n\n"
            f"Available servers: {servers_str}\n\n"
            "Args:\n"
            f"    server_name: The server to activate. One of: {servers_str}."
        )

        self._custom_tools = [generate_code, review_code, select_tools]
        self.graph = self._build_graph()

    async def _load_server_tools(self, server_name: str) -> list:
        """Return tools for *server_name*, loading from the MCP client once."""
        return await load_server_tools_cached(server_name, self._mcp_tools_by_server)

    async def _supervisor_node(self, state: CodingTaskState) -> dict:
        """The hub: assess state and pick the next tool call."""
        mode = state.get("mode", "interactive")

        # Extend custom tools with the active server's tools (cached).
        active_server = state.get("active_mcp_server", "")
        server_tools = self._mcp_tools_by_server.get(active_server, [])
        tools = list(self._custom_tools) + server_tools
        if not server_tools:
            logger.debug("No server tools bound to llm for coding supervisor")

        logger.debug(
            f"Supervisor bound tools ({mode}): "
            f"{[t.name for t in self._custom_tools]} + "
            f"{len(server_tools)} from '{active_server}'"
        )

        llm_with_tools = self.llm.bind_tools(tools)
        system_prompt = (
            CODING_SUPERVISOR_AUTONOMOUS_PROMPT
            if mode == "autonomous"
            else CODING_SUPERVISOR_SYSTEM_PROMPT
        )

        pruned = prune_tool_cycles(state["messages"])
        messages = [SystemMessage(content=system_prompt)] + pruned
        response = await invoke_llm_with_retry(llm_with_tools, messages)
        return {"messages": [response]}

    async def _tool_executor_node(self, state: CodingTaskState) -> dict:
        """The spoke: execute every tool call from the supervisor."""
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}

        results: list[ToolMessage] = []
        # Carries state fields updated during this batch (e.g. active server).
        state_update: dict = {"messages": results}

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            call_id = tc["id"]

            logger.info(f"Executing tool: {name} | args snippet: {str(args)[:300]}")

            # ── select_tools: activate a server and cache its tools ──────
            if name == "select_tools":
                server_name = args.get("server_name", "").strip()
                server_tools = await self._load_server_tools(server_name)
                if server_tools:
                    state_update["active_mcp_server"] = server_name
                    tool_names = "\n".join(f"  - {t.name}" for t in server_tools)
                    content = (
                        f"Activated {len(server_tools)} tools for server "
                        f"'{server_name}':\n{tool_names}\n\n"
                        "Call these tools directly in your next response."
                    )
                    logger.info(
                        f"Activated MCP server '{server_name}' "
                        f"({len(server_tools)} tools)"
                    )
                else:
                    known = list(self._mcp_tools_by_server.keys())
                    content = (
                        f"TERMINAL TOOL FAILURE — server '{server_name}' "
                        "could not be loaded or has no tools. Previously "
                        f"loaded servers: {known or 'none'}. Do NOT retry "
                        "this call."
                    )
                    logger.error(f"Failed to activate MCP server '{server_name}'")
                results.append(ToolMessage(content=content, tool_call_id=call_id))
                continue

            # ── all other tools: custom tools then active server ─────────
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
                    f"Active server: '{active_server}'. Call select_tools "
                    "with the correct server name first, then retry. Do NOT "
                    "retry without switching servers."
                )
                logger.error(f"Tool not found: '{name}' (active: '{active_server}')")
                results.append(ToolMessage(content=content, tool_call_id=call_id))
                continue

            # Inject guidelines from state so the LLM needn't pass them.
            if name in {"generate_code", "review_code"}:
                args = {
                    **args,
                    "guidelines": state.get("coding_guidelines", ""),
                }

            # Read-before-write: for generate_code on an existing file, fetch
            # the real contents and force them into existing_code so the LLM
            # edits the file instead of regenerating it from scratch.
            if name == "generate_code":
                existing = await self._fetch_existing_code(
                    state, (args.get("target_path") or "").strip()
                )
                if existing is not None:
                    args = {**args, "existing_code": existing}

            content = await execute_tool_with_retry(matched, args)
            results.append(ToolMessage(content=content, tool_call_id=call_id))

        return state_update

    async def _fetch_existing_code(
        self, state: CodingTaskState, target_path: str
    ) -> Optional[str]:
        """Fetch current contents of *target_path* from the repo, or None.

        Thin wrapper over :func:`fetch_existing_code` using this agent's repo
        coordinates and per-server tool cache.
        """
        return await fetch_existing_code(
            self._mcp_tools_by_server,
            provider=state.get("repo_source", ""),
            owner=state.get("repo_owner", ""),
            repo_reference=state.get("repo_reference", ""),
            base_branch=state.get("repo_base_branch", ""),
            target_path=target_path,
        )

    @staticmethod
    def _route_after_supervisor(state: CodingTaskState) -> str:
        """tools → execute, end → finish, or nudge → re-prompt on narration."""
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"

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
        """Re-prompt the supervisor when it narrated instead of acting."""
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
        bundle: ContextBundle,
        thread_id: Optional[str] = None,
        *,
        mode: str = "interactive",
    ) -> Dict[str, Any]:
        """Generate, review, and push code for the gathered *bundle*.

        Returns ``response`` (final text), ``interrupt`` (always None — this
        agent never pauses), and ``thread_id``.
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 20,
        }

        # Resolve repo coordinates from the bundle (with settings fallbacks).
        provider = (bundle.repo_source or "").strip().lower()
        owner = bundle.repository_owner or settings.coding_repository_owner or ""
        repo_reference = bundle.repository_reference
        base_branch = bundle.base_branch or settings.coding_base_branch

        try:
            # Pre-load the repo server's tools so the executor can fetch
            # existing files (read-before-write) before generation — independent
            # of when the LLM first calls select_tools. Branch creation and
            # pushing are driven by the supervisor LLM itself in Phase 4.
            if provider:
                await self._load_server_tools(provider)
            # Pre-load Context7 so the LLM can call select_tools("context7")
            # immediately without a round-trip to activate it first.
            await self._load_server_tools("context7")

            result = await self.graph.ainvoke(
                {
                    "messages": [HumanMessage(content=_render_task(bundle))],
                    "mode": mode,
                    "active_mcp_server": provider,
                    "coding_guidelines": bundle.development_guidelines,
                    "repo_source": provider,
                    "repo_owner": owner,
                    "repo_reference": repo_reference,
                    "repo_base_branch": base_branch,
                },
                config,
            )
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
                    "The coding workflow exceeded its maximum number of "
                    "steps. This usually means the agent got stuck in a "
                    "loop.\n\nPlease try again with a simpler request."
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }
        except Exception as exc:
            logger.error(f"Coding agent error: {exc}", exc_info=True)
            error_type = type(exc).__name__
            return {
                "response": (
                    "Something went wrong during the coding workflow.\n\n"
                    f"**{error_type}:** {exc}\n\n"
                    "This may be a temporary issue. You can try again."
                ),
                "interrupt": None,
                "thread_id": thread_id,
            }
