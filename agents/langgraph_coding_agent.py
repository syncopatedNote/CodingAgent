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

import json
import uuid
from typing import Any, Dict, Optional, TypedDict, Annotated

from langchain_core.messages import (
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

logger = setup_logger(__name__)


# ── Agent State ────────────────────────────────────────────────────


class CodingTaskState(TypedDict):
    """
    Shared memory for the supervisor-tool cycle.

    Uses LangGraph's ``add_messages`` reducer so every node can
    *append* messages without overwriting history.
    """

    messages: Annotated[list[BaseMessage], add_messages]


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

    prompt = f"""\
You are an expert software developer.  {action} production-ready code.

REQUIREMENTS:
{requirements}

CODEBASE CONTEXT:
{context}

DEVELOPMENT GUIDELINES:
{guidelines}

{extra}

Provide complete, production-ready code that:
1. Follows the development guidelines strictly
2. Implements all requirements
3. Includes proper error handling, logging, and documentation
4. Follows best practices for the target technology stack
{"5. Addresses every review-feedback point" if feedback else ""}

Structure your response as file-by-file code blocks with clear paths, e.g.

### `src/utils/helper.py`
```python
...
```
"""
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

    prompt = f"""\
You are a senior code reviewer. Provide specific, actionable feedback.

CODE TO REVIEW:
{code}

REQUIREMENTS:
{requirements}

DEVELOPMENT GUIDELINES:
{guidelines}

Review for:
1. Requirements compliance — does it implement everything asked?
2. Guidelines adherence — does it follow the coding standards?
3. Code quality — naming, structure, DRY, SOLID principles
4. Error handling — edge cases, input validation, graceful failures
5. Security — injection risks, auth issues, data exposure
6. Performance — algorithmic efficiency, unnecessary allocations
7. Maintainability — readability, documentation, testability

Return a numbered list of concrete improvements.  Reference exact
locations and suggest fixes.
"""
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


# ── Supervisor System Prompt ──────────────────────────────────────


SUPERVISOR_SYSTEM_PROMPT = """\
You are an expert coding agent that helps users implement code in GitHub \
repositories.  You orchestrate a multi-step workflow by calling the right \
tools at the right time.

## Your Workflow

Follow this flow.  Skip any step whose answer the user has already provided.

### Phase 1 — Information Gathering  (use `ask_user`)

1. **Requirements** — Ask what the user wants to implement.  They may give:
   - A Confluence page link  (you will fetch it with Confluence tools later)
   - A design-specification summary pasted inline
   - A brief natural-language description
2. **Development guidelines** — Ask if they have coding guidelines:
   - A path to a file in a GitHub repo + branch  (you will fetch it)
   - Guidelines pasted directly
   - "none" → use general best practices
3. **Implementation strategy** (optional) — Ask if they have a preferred
   approach, specific files to modify, or architectural preferences.
4. **Target branch** — Ask which branch to base the work on.
   Default to `main` or `master` if unspecified.

### Phase 2 — Context Gathering  (use GitHub / Confluence MCP tools)

5. If the user provided a Confluence link, fetch the page content.
6. If the user pointed to a guidelines file in a repo, fetch it.
7. Explore the repository structure and read relevant source files to
   understand conventions, tech stack, and existing patterns.
   - If the user mentioned specific files or an implementation strategy,
     start there.
   - Otherwise, read the top-level tree and a few key files.

### Phase 3 — Code Generation & Reflection  (3 cycles)

8.  Call `generate_code` with all gathered context.
9.  Call `review_code` on the generated code.
10. Call `generate_code` again with the review feedback.
    Repeat steps 9-10 so you complete **exactly 3 review → improve cycles**.

### Phase 4 — Push & Report  (use GitHub MCP tools)

11. Create a new feature branch from the target branch.
12. Push (create / update) the final code files to the new branch.
13. Respond with a **final summary** including the new branch name.
    Do NOT make any tool calls in this final message.

## Rules

- Be conversational and helpful when asking questions.
- Do NOT re-ask for information the user already provided.
- Always call `ask_user` ALONE — never combine it with other tools.
- Always complete exactly 3 reflection cycles before pushing.
- When finished, reply with a clear summary and the branch name.
  Make NO tool calls in your final message.
- To interact with GitHub, Confluence, or other external services,
  use the `run_mcp_tool` tool with the exact tool name and a JSON
  arguments string.
- **NEVER send a text-only message in the middle of the workflow.**
  Every response MUST contain at least one tool call UNLESS it is
  your final summary (Phase 4, step 13).  If you just fetched
  information and need to process it, immediately call the next
  tool — do NOT narrate what you plan to do next.
"""


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

    async def _load_tools(self) -> list:
        """Load MCP tools behind a single gateway tool.

        Instead of binding every MCP tool individually to the
        LLM (which can exceed the context window), all MCP
        tools are exposed through one ``run_mcp_tool`` gateway.
        The LLM sees only 4 bound tools regardless of how many
        MCP tools are available.
        """
        self._mcp_tool_map: dict[str, Any] = {}
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

        combined = list(self._custom_tools)
        if self._mcp_tool_map:
            combined.append(self._make_mcp_gateway())

        logger.info(
            f"Coding agent has {len(combined)} bound tools: "
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
                        f"Failed to parse args_schema for tool %s: %s - skipping schema",
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

    async def _supervisor_node(self, state: CodingTaskState) -> dict:
        """The hub: assess state and pick the next tool call."""
        if self._tools is None:
            self._tools = await self._load_tools()

        llm_with_tools = self.llm.bind_tools(self._tools)

        # Build system prompt, appending MCP status if degraded
        system_prompt = SUPERVISOR_SYSTEM_PROMPT
        if getattr(self, "_mcp_load_error", None):
            system_prompt += (
                "\n\n## ⚠️ Degraded Mode\n"
                f"{self._mcp_load_error}\n"
                "You can still ask the user questions and generate/"
                "review code, but you CANNOT access GitHub, "
                "Confluence, or Jira. Inform the user of this "
                "limitation and ask them to provide information "
                "directly (paste content, describe structure, etc)."
            )

        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        try:
            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}
        except Exception as exc:
            logger.error(f"Supervisor LLM call failed: {exc}", exc_info=True)
            from langchain_core.messages import AIMessage

            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I'm having trouble connecting to the AI service "
                            "right now. This may be a temporary issue.\n\n"
                            f"**Error:** {exc}\n\n"
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
        return {
            "messages": [
                SystemMessage(
                    content=(
                        "You just described what you plan to do "
                        "instead of doing it. Do NOT narrate — "
                        "call the appropriate tool NOW. Every "
                        "response must contain a tool call unless "
                        "it is your final summary."
                    )
                )
            ]
        }

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
                result = await self.graph.ainvoke(Command(resume=resume_value), config)
            else:
                result = await self.graph.ainvoke(
                    {"messages": [HumanMessage(content=user_input)]},
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
