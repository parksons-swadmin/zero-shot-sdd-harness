"""Invokes the compiled graph for one question against one session.

Concurrency (see spec/architecture.md -> Concurrency): one in-flight graph
run per session_id is enforced by an in-process lock keyed by session_id. A
concurrent request for the same session while one is already running raises
SessionBusyError, which src/api/sessions.py maps to HTTP 409.

Streaming (Phase 3c): `run_agent_streaming` runs the graph on a background
worker thread holding the SAME per-session lock, drains a queue.Queue of
progress events (`step`/`answer_chunk`/`result`/`error`/`done`), and yields
them to the SSE route. `answer_chunk` events originate inside compose_answer
(src/graph/nodes.py) via the run-scoped `_answer_chunk_sink` ContextVar set by
the worker; when that sink is unset (every non-streaming run) compose_answer
behaves identically to today, so `run_agent` (below) is provably unchanged.
"""
import contextvars
import json
import queue
import threading
from collections.abc import Callable, Iterator
from uuid import uuid4

from graph.agent import agentic_ai
from graph.state import AgentState

_locks_guard = threading.Lock()
_session_locks: dict[str, threading.Lock] = {}

# Run-scoped sink read by compose_answer: a callable taking one prose chunk
# string. Set only inside a streaming worker thread; default None means the
# non-streaming path (identical to pre-3c behaviour).
_answer_chunk_sink: contextvars.ContextVar = contextvars.ContextVar(
    "answer_chunk_sink", default=None
)

# Fixed human-readable labels for the "Step N of ~M: <label>" display.
_NODE_LABELS: dict[str, str] = {
    "load_context": "Loading dataset profiles",
    "classify_query": "Analyzing the question",
    "plan_steps": "Planning the analysis",
    "generate_code": "Writing analysis code",
    "execute_code": "Running the analysis",
    "check_result": "Checking the result",
    "advance_plan": "Advancing to the next step",
    "compose_answer": "Composing the answer",
    "finalize": "Finalizing",
    "handle_error": "Handling an error",
}

# Honest best-effort node-count estimates per reasoning mode, for the
# "Step N of ~M" display (never a fabricated percentage). Starts at the
# simple-path length and is revised once classify_query resolves the mode.
_ESTIMATE_BY_MODE: dict[str, int] = {"simple": 6, "iterative": 8, "planned": 10}
_DEFAULT_ESTIMATE = 6


class SessionBusyError(Exception):
    """Raised when a run is already in flight for the given session_id."""


def _get_lock(session_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock


def get_answer_chunk_sink() -> Callable[[str], None] | None:
    """Return the run-scoped answer-chunk sink for the current context, or None
    when no streaming run is active (compose_answer reads this)."""
    return _answer_chunk_sink.get()


def format_sse_event(event: str, data: dict) -> str:
    """Format one Server-Sent-Events frame: `event: <type>\\ndata: <json>\\n\\n`.

    The JSON payload is always a single line (json.dumps has no embedded
    newlines by default) so a client can split the stream on `\\n\\n`.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _initial_state(session_id: str, dataset_ids: list[str], question: str) -> AgentState:
    return {
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


def run_agent(session_id: str, dataset_ids: list[str], question: str) -> AgentState:
    """Runs the graph for one question. Returns the final AgentState (a dict)."""
    lock = _get_lock(session_id)
    if not lock.acquire(blocking=False):
        raise SessionBusyError(
            f"A question is already being answered for session {session_id} — wait for it to finish"
        )
    try:
        return agentic_ai.invoke(_initial_state(session_id, dataset_ids, question))
    finally:
        lock.release()


def run_agent_streaming(
    session_id: str, dataset_ids: list[str], question: str,
) -> Iterator[dict]:
    """Run the graph on a background worker thread and yield progress events.

    Holds the SAME per-session lock as `run_agent` (so a stream cannot overlap
    another run for the same session — a busy session raises SessionBusyError,
    which the SSE route maps to a single `error` event). Yields event dicts:

      {"event": "step", "data": {index, node, label, total_estimate}}
      {"event": "answer_chunk", "data": {"text": ...}}
      {"event": "result", "query_result_id": ..., "message_id": ...}
      {"event": "error", "data": {"message": ..., "status": "failed"}}
      {"event": "done", "data": {}}

    The `result` event carries only IDs; the SSE route loads the finalized
    QueryResult (with per-query cost) and expands it into the full payload.
    """
    lock = _get_lock(session_id)
    if not lock.acquire(blocking=False):
        raise SessionBusyError(
            f"A question is already being answered for session {session_id} — wait for it to finish"
        )

    q: queue.Queue = queue.Queue()

    def _worker() -> None:
        token = _answer_chunk_sink.set(
            lambda text: q.put({"event": "answer_chunk", "data": {"text": text}})
        )
        try:
            merged: dict = dict(_initial_state(session_id, dataset_ids, question))
            index = 0
            total_estimate = _DEFAULT_ESTIMATE
            try:
                for update in agentic_ai.stream(merged, stream_mode="updates"):
                    for node_name, delta in update.items():
                        index += 1
                        if isinstance(delta, dict):
                            merged.update(delta)
                            if node_name == "classify_query":
                                total_estimate = _ESTIMATE_BY_MODE.get(
                                    delta.get("reasoning_mode"), total_estimate
                                )
                        q.put({
                            "event": "step",
                            "data": {
                                "index": index,
                                "node": node_name,
                                "label": _NODE_LABELS.get(node_name, node_name),
                                "total_estimate": total_estimate,
                            },
                        })
            except Exception:  # graph blew up outside handle_error's sanitized path
                q.put({
                    "event": "error",
                    "data": {"message": "The analysis failed due to an unexpected error. Please try again.",
                             "status": "failed"},
                })
                return

            query_result_id = merged.get("query_result_id")
            if merged.get("status") == "failed" or not query_result_id:
                message = merged.get("error") or "The question could not be answered."
                q.put({"event": "error", "data": {"message": message, "status": "failed"}})
            else:
                q.put({
                    "event": "result",
                    "query_result_id": query_result_id,
                    "message_id": merged.get("message_id"),
                })
        finally:
            q.put({"event": "done", "data": {}})
            _answer_chunk_sink.reset(token)
            lock.release()

    thread = threading.Thread(target=_worker, name=f"stream-{session_id}", daemon=True)
    thread.start()

    while True:
        item = q.get()
        yield item
        if item.get("event") == "done":
            break
