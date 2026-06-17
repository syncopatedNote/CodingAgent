#!/usr/bin/env python3
"""
Deterministic, per-file Coding Agent powered by LangGraph.

Where :class:`LangGraphCodingAgent` lets the supervisor LLM improvise the whole
workflow via free-form tool calls, this agent moves the *orchestration* into
explicit graph nodes and conditional edges. The LLM still does all the thinking
inside each step (nominate, plan, generate, review); the graph decides which file
is next, how many review cycles to run, and when to push.

Flow::

    explore_repo → plan_work → select_next_file ─┐
                                   │              │ (queue drained)
                                   ▼              ▼
              ┌────────── generate_code_node   push_branch_node → END
              │                │
              │                ▼
              │          review_code_node
              │                │
              │   ┌── route_after_review ──┐
              │  approved OR             not approved
              │  iter >= max             AND iter < max
              │       │                     │
              │       ▼                     └── (regenerate, feedback =
              │   stage_file                     blocking_issues)
              └───────┘ (loop back to select_next_file)

Per-file scratch (``current_file``, ``draft_content``, ``review_iteration``,
``last_review``) is RESET in ``select_next_file`` every time a new file is
popped — plan-level and accumulator fields (``plan``, ``plan_cursor``,
``pending_files``) persist for the whole run.

Routing keys on ``approved`` only. ``confidence`` is recorded for reporting. A
file that never gets approved within ``settings.coding_max_review_cycles`` is
staged with a warning carrying its unresolved blocking issues, which are then
listed in the final push report.

Git is touched in exactly one place — ``push_branch_node`` — which creates one
work branch (name chosen in code, not by the LLM) and pushes every staged file
to it via the provider's MCP write tool.
"""

import operator
import uuid
from typing import Any, Dict, List, Optional, TypedDict, Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from framework_base.llm_base import LLMFactory
from logger import setup_logger
from settings import settings
from agents.prompts.coding_supervisor.deterministic.nominate_files import (
    NOMINATE_FILES_PROMPT,
)
from agents.prompts.coding_supervisor.deterministic.plan_files import (
    PLAN_FILES_PROMPT,
)
from agents.prompts.coding_supervisor.deterministic.review_code_structured import (
    REVIEW_CODE_STRUCTURED_PROMPT,
)
from agents.prompts.coding_supervisor.generate_code import GENERATE_CODE_PROMPT
from ..collector_agent.context_bundle import ContextBundle
from ..collector_agent.mcp_fetch import result_to_text
from .coding_llm_singleton import code_llm
from .deterministic_models import CodeReview, NominatedFiles, WorkPlan
from .repo_mcp_helpers import (
    PROVIDER_TOOLS,
    fetch_existing_code,
    find_tool,
    load_server_tools_cached,
)

logger = setup_logger(__name__)


# ── State ──────────────────────────────────────────────────────────


class FinalizedFile(TypedDict):
    """A staged file ready to push. ``staged_with_warning`` is set when the file
    hit the review ceiling without approval; ``unresolved_blocking_issues`` then
    carries what the reviewer never saw fixed."""

    path: str
    content: str
    commit_message: str
    staged_with_warning: bool
    unresolved_blocking_issues: List[str]


class PlannedFileState(TypedDict):
    """A single planned file, popped into ``current_file`` for the per-file loop."""

    path: str
    intent: str
    is_new: bool


class DeterministicCodingState(TypedDict):
    """Shared memory for the deterministic per-file pipeline."""

    # ── inputs (seeded once, read-only) ──
    mode: str
    requirements: str
    design_details: str
    coding_guidelines: str
    repo_source: str  # "github" | "gitlab"
    repo_owner: str
    repo_reference: str
    repo_base_branch: str

    # ── plan-level (persist across files) ──
    repo_tree: str
    impacted_files: Dict[str, str]  # path -> current content
    plan: List[PlannedFileState]
    plan_cursor: int

    # ── per-file scratch (RESET in select_next_file) ──
    current_file: Optional[PlannedFileState]
    draft_content: str
    review_iteration: int
    last_review: Optional[CodeReview]

    # ── accumulator (NOT reset) ──
    pending_files: Annotated[List[FinalizedFile], operator.add]

    # ── final ──
    branch_name: str
    push_report: str


# Strip a leading "### `path`" header and surrounding ``` fences from a
# generate_code result, leaving raw file content suitable for pushing.
def _strip_code_block(text: str) -> str:
    body = text.strip()
    lines = body.splitlines()
    # Drop a leading markdown header line (e.g. "### `path/to/file.py`").
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    # Drop matching opening/closing code fences.
    while lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].rstrip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip("\n")


class DeterministicCodingAgent:
    """Explicit explore → plan → per-file generate/review → push agent.

    Consumes a :class:`ContextBundle` and exposes the same ``run`` contract as
    :class:`LangGraphCodingAgent`, so :class:`CodingPipeline` can swap between
    them on a settings flag with no other changes.
    """

    def __init__(self) -> None:
        # Per-server MCP tool cache, owned by this instance and threaded through
        # the shared repo_mcp_helpers functions.
        self._mcp_tools_by_server: dict[str, list] = {}
        self.checkpointer = MemorySaver()
        self.max_cycles = max(1, settings.coding_max_review_cycles)

        llm_kwargs: dict[str, Any] = {"temperature": 0.3}
        if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
            llm_kwargs["base_url"] = settings.ollama_base_url

        # A reasoning LLM for nominate/plan/review (structured output bound
        # per-call). code_llm (temp 0.3) is reused for raw generation.
        self.llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            **llm_kwargs,
        )

        self.graph = self._build_graph()

    # ── helpers ────────────────────────────────────────────────────

    async def _structured(self, model_cls, system: Optional[str], user: str):
        """Invoke the LLM with structured output for *model_cls*.

        Returns a parsed model instance, or ``None`` if the call/parse fails so
        callers can fall back rather than crash the graph.
        """
        messages: list = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=user))
        try:
            structured_llm = self.llm.with_structured_output(model_cls)
            return await structured_llm.ainvoke(messages)
        except Exception as exc:
            logger.error(
                f"Structured output for {model_cls.__name__} failed: {exc}",
                exc_info=True,
            )
            return None

    # ── nodes ──────────────────────────────────────────────────────

    async def _explore_repo(self, state: DeterministicCodingState) -> dict:
        """Pull the repo tree, nominate likely-impacted files, read them."""
        provider = state["repo_source"]
        tools_map = PROVIDER_TOOLS.get(provider, {})
        tree_tool_name = tools_map.get("tree")

        await load_server_tools_cached(provider, self._mcp_tools_by_server)
        tree_tool = find_tool(self._mcp_tools_by_server, provider, tree_tool_name or "")

        repo_tree = ""
        if tree_tool is not None:
            try:
                raw = await tree_tool.ainvoke(
                    {
                        "owner": state["repo_owner"],
                        "repo": state["repo_reference"],
                        "ref": state["repo_base_branch"],
                        "recursive": True,
                    }
                )
                repo_tree = result_to_text(raw).strip()
            except Exception as exc:
                logger.warning(f"Repo tree fetch failed for '{provider}': {exc}")
        else:
            logger.warning(f"No tree tool available for provider '{provider}'")

        # Nominate likely-impacted existing files from the tree.
        impacted: dict[str, str] = {}
        if repo_tree:
            nominated = await self._structured(
                NominatedFiles,
                system=None,
                user=NOMINATE_FILES_PROMPT.format(
                    repo_tree=repo_tree,
                    requirements=state["requirements"],
                    design=state["design_details"] or "(none provided)",
                ),
            )
            paths = nominated.paths if nominated else []
            logger.info(f"Explore nominated {len(paths)} files: {paths}")
            for path in paths:
                existing = await fetch_existing_code(
                    self._mcp_tools_by_server,
                    provider=provider,
                    owner=state["repo_owner"],
                    repo_reference=state["repo_reference"],
                    base_branch=state["repo_base_branch"],
                    target_path=path,
                )
                if existing is not None:
                    impacted[path] = existing

        return {"repo_tree": repo_tree, "impacted_files": impacted}

    async def _plan_work(self, state: DeterministicCodingState) -> dict:
        """Produce an ordered, file-by-file work plan via structured output."""
        impacted_blob = (
            "\n\n".join(
                f"### {path}\n{content}"
                for path, content in state["impacted_files"].items()
            )
            or "(no existing files read)"
        )
        guidelines = state["coding_guidelines"]
        plan = await self._structured(
            WorkPlan,
            system=f"CODING GUIDELINES:\n{guidelines}" if guidelines else None,
            user=PLAN_FILES_PROMPT.format(
                requirements=state["requirements"],
                design=state["design_details"] or "(none provided)",
                repo_tree=state["repo_tree"] or "(unavailable)",
                impacted_files=impacted_blob,
            ),
        )
        files: List[PlannedFileState] = []
        if plan:
            files = [
                {"path": f.path, "intent": f.intent, "is_new": f.is_new}
                for f in plan.files
                if f.path.strip()
            ]
        logger.info(f"Plan produced {len(files)} files: {[f['path'] for f in files]}")
        return {"plan": files, "plan_cursor": 0}

    def _select_next_file(self, state: DeterministicCodingState) -> dict:
        """Pop the next planned file and RESET all per-file scratch.

        Plan-level fields (plan, plan_cursor accumulation) and the pending_files
        accumulator are deliberately NOT reset here — only the four scratch
        fields that describe the file currently being worked on.
        """
        cursor = state["plan_cursor"]
        plan = state["plan"]
        if cursor >= len(plan):
            return {"current_file": None}
        return {
            "current_file": plan[cursor],
            "plan_cursor": cursor + 1,
            # ── scratch reset ──
            "draft_content": "",
            "review_iteration": 0,
            "last_review": None,
        }

    async def _generate_code_node(self, state: DeterministicCodingState) -> dict:
        """Generate or improve the current file (read-before-write + feedback)."""
        current = state["current_file"]
        path = current["path"]

        existing = ""
        if not current["is_new"]:
            # Prefer the contents already read during explore; otherwise fetch.
            existing = state["impacted_files"].get(path, "")
            if not existing:
                fetched = await fetch_existing_code(
                    self._mcp_tools_by_server,
                    provider=state["repo_source"],
                    owner=state["repo_owner"],
                    repo_reference=state["repo_reference"],
                    base_branch=state["repo_base_branch"],
                    target_path=path,
                )
                existing = fetched or ""

        # On a regeneration pass, feed the unresolved blocking issues as feedback.
        review = state["last_review"]
        feedback = ""
        if review and not review.approved and review.blocking_issues:
            feedback = "\n".join(f"- {issue}" for issue in review.blocking_issues)

        action = "Generate" if not existing else "Improve"
        extra_sections: list[str] = []
        if existing:
            extra_sections.append(f"CURRENT CODE TO IMPROVE:\n{existing}")
        if feedback:
            extra_sections.append(
                f"REVIEW FEEDBACK TO ADDRESS:\n{feedback}\n\n"
                "You MUST address every feedback point."
            )
        extra = "\n\n".join(extra_sections)

        prompt = GENERATE_CODE_PROMPT.format(
            action=action,
            target_path=path,
            requirements=current["intent"],
            context=(
                f"Overall requirements:\n{state['requirements']}\n\n"
                f"Design details:\n{state['design_details'] or '(none)'}"
            ),
            extra=extra,
            feedback_instruction=(
                "6. Addresses every review-feedback point" if feedback else ""
            ),
        )
        messages: list = []
        guidelines = state["coding_guidelines"]
        if guidelines:
            messages.append(SystemMessage(content=f"CODING GUIDELINES:\n{guidelines}"))
        messages.append(HumanMessage(content=prompt))

        try:
            response = await code_llm.ainvoke(messages)
            draft = str(response.content)
        except Exception as exc:
            logger.error(f"generate_code failed for '{path}': {exc}", exc_info=True)
            # Keep any prior draft; an empty draft would otherwise stage nothing.
            draft = state["draft_content"]

        logger.info(f"Generated draft for '{path}' ({len(draft)} chars)")
        return {"draft_content": draft}

    async def _review_code_node(self, state: DeterministicCodingState) -> dict:
        """Review the current draft into a structured CodeReview."""
        current = state["current_file"]
        guidelines = state["coding_guidelines"]
        review = await self._structured(
            CodeReview,
            system=f"CODING GUIDELINES:\n{guidelines}" if guidelines else None,
            user=REVIEW_CODE_STRUCTURED_PROMPT.format(
                code=_strip_code_block(state["draft_content"]),
                requirements=current["intent"],
            ),
        )
        if review is None:
            # Fail safe: force a regeneration rather than silently approving.
            review = CodeReview(
                approved=False,
                confidence=0.0,
                blocking_issues=["Automated review failed to produce a result."],
            )

        iteration = state["review_iteration"] + 1
        logger.info(
            f"Review of '{current['path']}' (cycle {iteration}/{self.max_cycles}): "
            f"approved={review.approved} confidence={review.confidence:.2f} "
            f"blocking={len(review.blocking_issues)} "
            f"non_blocking={len(review.non_blocking_issues)}"
        )
        return {"last_review": review, "review_iteration": iteration}

    def _stage_file(self, state: DeterministicCodingState) -> dict:
        """Append the finalised current file to pending_files (no git call)."""
        current = state["current_file"]
        review = state["last_review"]
        warned = bool(review and not review.approved)
        unresolved = review.blocking_issues if warned else []

        finalized: FinalizedFile = {
            "path": current["path"],
            "content": _strip_code_block(state["draft_content"]),
            "commit_message": f"cortex: {current['intent'][:72]}",
            "staged_with_warning": warned,
            "unresolved_blocking_issues": unresolved,
        }
        if warned:
            logger.warning(
                f"Staging '{current['path']}' WITH WARNING after "
                f"{self.max_cycles} cycles; unresolved: {unresolved}"
            )
        else:
            logger.info(f"Staged '{current['path']}' (approved)")
        return {"pending_files": [finalized]}

    async def _push_branch_node(self, state: DeterministicCodingState) -> dict:
        """Create one work branch and push every staged file to it via MCP."""
        provider = state["repo_source"]
        owner = state["repo_owner"]
        repo = state["repo_reference"]
        base = state["repo_base_branch"]
        pending = state["pending_files"]
        tools_map = PROVIDER_TOOLS.get(provider, {})

        if not pending:
            return {"push_report": "No files were staged; nothing to push."}

        branch_name = f"cortex/auto-{uuid.uuid4().hex[:8]}"

        branch_tool = find_tool(
            self._mcp_tools_by_server, provider, tools_map.get("branch", "")
        )
        write_tool = find_tool(
            self._mcp_tools_by_server, provider, tools_map.get("write", "")
        )
        if branch_tool is None or write_tool is None:
            msg = (
                f"FAILURE: push tools unavailable for provider '{provider}' "
                f"(branch={branch_tool is not None}, write={write_tool is not None})."
            )
            logger.error(msg)
            return {"push_report": msg, "branch_name": branch_name}

        # Create the branch off the base.
        try:
            await branch_tool.ainvoke(
                {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch_name,
                    "from_branch": base,
                }
            )
            logger.info(f"Created branch '{branch_name}' off '{base}'")
        except Exception as exc:
            msg = f"FAILURE: could not create branch '{branch_name}': {exc}"
            logger.error(msg, exc_info=True)
            return {"push_report": msg, "branch_name": branch_name}

        # Push each staged file to the single branch.
        pushed: list[str] = []
        failed: list[str] = []
        for f in pending:
            try:
                await write_tool.ainvoke(
                    {
                        "owner": owner,
                        "repo": repo,
                        "branch": branch_name,
                        "path": f["path"],
                        "content": f["content"],
                        "message": f["commit_message"],
                    }
                )
                pushed.append(f["path"])
            except Exception as exc:
                logger.error(f"Push failed for '{f['path']}': {exc}", exc_info=True)
                failed.append(f["path"])

        return {
            "branch_name": branch_name,
            "push_report": self._build_report(branch_name, pending, pushed, failed),
        }

    @staticmethod
    def _build_report(
        branch_name: str,
        pending: List[FinalizedFile],
        pushed: List[str],
        failed: List[str],
    ) -> str:
        """Human-readable summary, surfacing unresolved blocking issues per file."""
        lines = [f"Branch: {branch_name}", ""]
        lines.append(f"Pushed {len(pushed)}/{len(pending)} file(s).")
        if failed:
            lines.append(f"Failed to push: {', '.join(failed)}")
        lines.append("")
        lines.append("Files:")
        for f in pending:
            mark = "⚠️ staged with warning" if f["staged_with_warning"] else "✅"
            lines.append(f"  {mark} {f['path']}")
            if f["staged_with_warning"] and f["unresolved_blocking_issues"]:
                for issue in f["unresolved_blocking_issues"]:
                    lines.append(f"      - UNRESOLVED: {issue}")
        return "\n".join(lines)

    # ── routers ────────────────────────────────────────────────────

    @staticmethod
    def _route_after_select(state: DeterministicCodingState) -> str:
        return "generate" if state.get("current_file") is not None else "push"

    def _route_after_review(self, state: DeterministicCodingState) -> str:
        review = state["last_review"]
        if review and review.approved:
            return "stage"
        if state["review_iteration"] < self.max_cycles:
            return "regenerate"
        return "stage"  # ceiling hit → stage with warning

    # ── graph ──────────────────────────────────────────────────────

    def _build_graph(self):
        workflow = StateGraph(DeterministicCodingState)
        workflow.add_node("explore_repo", self._explore_repo)
        workflow.add_node("plan_work", self._plan_work)
        workflow.add_node("select_next_file", self._select_next_file)
        workflow.add_node("generate_code_node", self._generate_code_node)
        workflow.add_node("review_code_node", self._review_code_node)
        workflow.add_node("stage_file", self._stage_file)
        workflow.add_node("push_branch_node", self._push_branch_node)

        workflow.set_entry_point("explore_repo")
        workflow.add_edge("explore_repo", "plan_work")
        workflow.add_edge("plan_work", "select_next_file")
        workflow.add_conditional_edges(
            "select_next_file",
            self._route_after_select,
            {"generate": "generate_code_node", "push": "push_branch_node"},
        )
        workflow.add_edge("generate_code_node", "review_code_node")
        workflow.add_conditional_edges(
            "review_code_node",
            self._route_after_review,
            {"regenerate": "generate_code_node", "stage": "stage_file"},
        )
        workflow.add_edge("stage_file", "select_next_file")
        workflow.add_edge("push_branch_node", END)
        return workflow.compile(checkpointer=self.checkpointer)

    # ── entry point ────────────────────────────────────────────────

    async def run(
        self,
        bundle: ContextBundle,
        thread_id: Optional[str] = None,
        *,
        mode: str = "interactive",
    ) -> Dict[str, Any]:
        """Run explore → plan → per-file generate/review → push for *bundle*.

        Returns ``response`` (the push report), ``interrupt`` (always None —
        this agent never pauses), and ``thread_id``.
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        provider = (bundle.repo_source or "").strip().lower()
        owner = bundle.repository_owner or settings.coding_repository_owner or ""
        repo_reference = bundle.repository_reference
        base_branch = bundle.base_branch or settings.coding_base_branch

        design = "\n\n".join(
            part
            for part in (
                bundle.confluence_design_details.strip(),
                (
                    f"LINKED ISSUE:\n{bundle.git_issue_details.strip()}"
                    if bundle.git_issue_details.strip()
                    else ""
                ),
            )
            if part
        )

        # Recursion budget: each file costs up to ~(2·max_cycles + 2) super-steps
        # (generate+review per cycle, plus select+stage), plus a fixed prologue.
        # The plan size is unknown until plan_work runs, so allow a generous
        # ceiling sized off the configured cycle count (≈40 files worst case).
        recursion_limit = 20 + 40 * (2 * self.max_cycles + 2)

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": recursion_limit,
        }

        try:
            if provider:
                await load_server_tools_cached(provider, self._mcp_tools_by_server)

            result = await self.graph.ainvoke(
                {
                    "mode": mode,
                    "requirements": bundle.requirements,
                    "design_details": design,
                    "coding_guidelines": bundle.development_guidelines,
                    "repo_source": provider,
                    "repo_owner": owner,
                    "repo_reference": repo_reference,
                    "repo_base_branch": base_branch,
                    "repo_tree": "",
                    "impacted_files": {},
                    "plan": [],
                    "plan_cursor": 0,
                    "current_file": None,
                    "draft_content": "",
                    "review_iteration": 0,
                    "last_review": None,
                    "pending_files": [],
                    "branch_name": "",
                    "push_report": "",
                },
                config,
            )
            return {
                "response": result.get("push_report") or "Coding run completed.",
                "interrupt": None,
                "thread_id": thread_id,
            }

        except Exception as exc:
            logger.error(f"Deterministic coding agent error: {exc}", exc_info=True)
            error_type = type(exc).__name__
            response = (
                f"FAILURE: {error_type}: {exc}\nREF: {provider or 'unknown'}\n"
                "ATTEMPTED: deterministic code generation"
                if mode == "autonomous"
                else (
                    "Something went wrong during the coding workflow.\n\n"
                    f"**{error_type}:** {exc}\n\nYou can try again."
                )
            )
            return {"response": response, "interrupt": None, "thread_id": thread_id}
