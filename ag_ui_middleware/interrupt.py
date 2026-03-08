"""
AG-UI Middleware — Interrupt Manager

Tracks outstanding interrupts per thread so that a resumed run
can retrieve the saved agent state and continue execution.

The default implementation is **in-memory** (suitable for a
single-process deployment).  Swap in a persistent backend by
subclassing :class:`InterruptManager` and overriding the
storage methods.

Usage::

    mgr = InterruptManager()

    # Agent decides to interrupt
    mgr.create(
        thread_id="t1",
        run_id="r1",
        interrupt=InterruptData(
            id="int-abc",
            reason="human_approval",
            payload={...},
        ),
        agent_state={"partial_work": "..."},
    )

    # Client resumes
    state = mgr.resolve("t1", "int-abc")
    # state.agent_state → {"partial_work": "..."}
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from .types import InterruptData, InterruptState

from logger import setup_logger

logger = setup_logger(__name__)


class InterruptManager:
    """
    Thread-safe, in-memory store for pending interrupts.

    Keyed by *thread_id* — only one outstanding interrupt per
    conversation thread at a time.
    """

    def __init__(self) -> None:
        self._pending: Dict[str, InterruptState] = {}
        self._lock = threading.Lock()

    # ── Write ──────────────────────────────────────────────

    def create(
        self,
        thread_id: str,
        run_id: str,
        interrupt: InterruptData,
        agent_state: Optional[Dict] = None,
    ) -> InterruptState:
        """
        Register a pending interrupt for *thread_id*.

        Any previously pending interrupt on the same thread
        is silently replaced.
        """
        state = InterruptState(
            thread_id=thread_id,
            run_id=run_id,
            interrupt=interrupt,
            agent_state=agent_state or {},
        )
        with self._lock:
            self._pending[thread_id] = state
        logger.info(
            f"Interrupt created: thread={thread_id} "
            f"id={interrupt.id} reason={interrupt.reason}"
        )
        return state

    # ── Read ───────────────────────────────────────────────

    def get(self, thread_id: str) -> Optional[InterruptState]:
        """Return the pending interrupt for *thread_id*, if any."""
        with self._lock:
            return self._pending.get(thread_id)

    def has_pending(self, thread_id: str) -> bool:
        """Check whether *thread_id* has an outstanding interrupt."""
        with self._lock:
            return thread_id in self._pending

    # ── Resolve / clear ────────────────────────────────────

    def resolve(
        self,
        thread_id: str,
        interrupt_id: str,
    ) -> Optional[InterruptState]:
        """
        Resolve (consume) the pending interrupt.

        Returns the :class:`InterruptState` if the *interrupt_id*
        matches, otherwise ``None``.  A successful resolve removes
        the interrupt from the store.
        """
        with self._lock:
            state = self._pending.get(thread_id)
            if state and state.interrupt.id == interrupt_id:
                del self._pending[thread_id]
                logger.info(
                    f"Interrupt resolved: thread={thread_id} " f"id={interrupt_id}"
                )
                return state
        logger.warning(
            f"Interrupt resolve failed: thread={thread_id} "
            f"id={interrupt_id} (not found or id mismatch)"
        )
        return None

    def clear(self, thread_id: str) -> bool:
        """
        Unconditionally remove a pending interrupt.

        Returns ``True`` if one was cleared, ``False`` otherwise.
        """
        with self._lock:
            removed = self._pending.pop(thread_id, None)
        if removed:
            logger.info(
                f"Interrupt cleared: thread={thread_id} " f"id={removed.interrupt.id}"
            )
        return removed is not None

    # ── Diagnostics ────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def list_pending(self) -> Dict[str, InterruptState]:
        """Snapshot of all pending interrupts (for debugging)."""
        with self._lock:
            return dict(self._pending)
