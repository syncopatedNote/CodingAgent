#!/usr/bin/env python3
"""
Coding Pipeline

Thin orchestrator that chains the two focused agents:

    ContextCollectorAgent  →  LangGraphCodingAgent

The collector gathers requirements, design, and the mandatory development
guidelines into a :class:`ContextBundle`; the coding agent then runs a pure
generate → review → push loop over that bundle.

Only the collector can pause for ``ask_user`` interrupts, so the pipeline's
resume path always targets the collector. Once context is ready the coding agent
runs straight through to completion.

The return contract — ``{"response", "interrupt", "thread_id"}`` — matches what
callers (supervisor, sprint agent, AG-UI resume route) already expect from the
old coding agent, so wiring barely changes.
"""

import uuid
from typing import Any, Optional

from logger import setup_logger
from settings import settings
from .collector_agent import ContextCollectorAgent, ContextBundle
from .coding_agent.langgraph_coding_agent import LangGraphCodingAgent
from .coding_agent.deterministic_coding_agent import DeterministicCodingAgent

logger = setup_logger(__name__)


class CodingPipeline:
    """Chains context collection and code generation behind one ``run``."""

    def __init__(self) -> None:
        self.collector = ContextCollectorAgent()
        # Select the coding agent by flag. Both expose the same
        # run(bundle, mode=...) contract, so nothing else in the pipeline
        # changes. "deterministic" uses the explicit per-file graph; anything
        # else (default "supervisor") uses the improvised hub-and-spoke agent.
        if settings.coding_agent_mode.strip().lower() == "deterministic":
            logger.info("CodingPipeline using DeterministicCodingAgent")
            self.coding_agent = DeterministicCodingAgent()
        else:
            logger.info("CodingPipeline using LangGraphCodingAgent (supervisor)")
            self.coding_agent = LangGraphCodingAgent()

    @staticmethod
    def _failure_response(
        reason: str, mode: str, repo_source: str, thread_id: str
    ) -> dict:
        """Shape a terminal failure. Autonomous uses the parseable FAILURE
        format that ``SprintStartAgent`` keys on; interactive is conversational.
        """
        if mode == "autonomous":
            response = (
                f"FAILURE: {reason}\n"
                f"REF: {repo_source or 'unknown'}\n"
                "ATTEMPTED: context collection"
            )
        else:
            response = (
                "I couldn't gather enough context to start coding.\n\n"
                f"**Reason:** {reason}"
            )
        return {"response": response, "interrupt": None, "thread_id": thread_id}

    async def run(
        self,
        user_input: str,
        thread_id: Optional[str] = None,
        *,
        resume_value: Any = None,
        mode: str = "interactive",
    ) -> dict:
        """Collect context, then run the coding agent.

        Parameters mirror the old coding agent so callers need minimal changes.
        ``thread_id`` identifies the collector run (the only interruptible part).
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        # ── Step 0: owner guard (fail fast, no LLM/MCP calls) ─────────
        if not settings.coding_repository_owner:
            logger.error(
                "CODING_REPOSITORY_OWNER is not set — refusing to run the "
                "coding pipeline (GitHub MCP push requires an owner)."
            )
            reason = (
                "CODING_REPOSITORY_OWNER is not configured; the repository "
                "owner is required to push code."
            )
            return self._failure_response(reason, mode, "", thread_id)

        # ── Step 1: collect context (may interrupt / be resumed) ──────
        collected = await self.collector.run(
            user_input=user_input,
            thread_id=thread_id,
            resume_value=resume_value,
            mode=mode,
        )

        if collected.get("interrupt"):
            return {
                "response": None,
                "interrupt": collected["interrupt"],
                "thread_id": collected["thread_id"],
            }

        bundle: Optional[ContextBundle] = collected.get("context")

        # ── Step 2: validate the bundle ───────────────────────────────
        if bundle is None or not bundle.is_complete():
            reason = (
                bundle.failure_reason
                if bundle and bundle.failure_reason
                else "context collection did not produce a usable result"
            )
            ref = bundle.repo_source if bundle else ""
            logger.warning(f"Context collection failed: {reason}")
            return self._failure_response(reason, mode, ref, thread_id)

        # ── Step 3: run the coding agent to completion ────────────────
        logger.info(
            f"Context ready (ref={bundle.repo_source or 'n/a'}, "
            f"repo={bundle.repository_reference or 'n/a'}); "
            "starting code generation."
        )
        coding_result = await self.coding_agent.run(bundle=bundle, mode=mode)

        return {
            "response": coding_result.get("response"),
            "interrupt": None,
            "thread_id": thread_id,
        }
