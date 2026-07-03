"""Invokes the compiled graph for one question against one session.

Concurrency (see spec/architecture.md -> Concurrency): one in-flight graph
run per session_id is enforced by an in-process lock keyed by session_id. A
concurrent request for the same session while one is already running raises
SessionBusyError, which src/api/sessions.py maps to HTTP 409.
"""
import threading
from uuid import uuid4

from graph.agent import agentic_ai
from graph.state import AgentState

_locks_guard = threading.Lock()
_session_locks: dict[str, threading.Lock] = {}


class SessionBusyError(Exception):
    """Raised when a run is already in flight for the given session_id."""


def _get_lock(session_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock


def run_agent(session_id: str, dataset_ids: list[str], question: str) -> AgentState:
    """Runs the graph for one question. Returns the final AgentState (a dict)."""
    lock = _get_lock(session_id)
    if not lock.acquire(blocking=False):
        raise SessionBusyError(
            f"A question is already being answered for session {session_id} — wait for it to finish"
        )
    try:
        initial: AgentState = {
            "run_id": str(uuid4()),
            "session_id": session_id,
            "dataset_ids": dataset_ids,
            "question": question,
            "conversation_history": [],
            "profiles": [],
            "reasoning_mode": "",
            "iteration_count": 0,
            "step_count": 0,
            "generated_code": "",
            "execution_result": {},
            "accumulated_summaries": [],
            "cost_records": [],
            "error": None,
            "status": "running",
        }
        return agentic_ai.invoke(initial)
    finally:
        lock.release()
