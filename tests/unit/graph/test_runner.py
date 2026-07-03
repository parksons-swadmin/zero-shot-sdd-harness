import threading
import time
from unittest.mock import patch

import pytest

from graph.runner import SessionBusyError, run_agent


def _slow_invoke(initial):
    time.sleep(0.3)
    return {**initial, "status": "completed", "message_id": "m", "query_result_id": "q"}


def test_run_agent_blocks_concurrent_run_for_same_session(_isolated_db):
    results = {}

    def worker(key):
        try:
            results[key] = run_agent("sess-lock", ["ds-1"], "q")
        except SessionBusyError as exc:
            results[key] = exc

    with patch("graph.runner.agentic_ai.invoke", side_effect=_slow_invoke):
        t1 = threading.Thread(target=worker, args=("a",))
        t1.start()
        time.sleep(0.05)  # ensure t1 has acquired the lock first
        t2 = threading.Thread(target=worker, args=("b",))
        t2.start()
        t1.join()
        t2.join()

    assert isinstance(results["b"], SessionBusyError)
    assert results["a"]["status"] == "completed"


def test_run_agent_different_sessions_do_not_block(_isolated_db):
    results = {}

    def worker(key, session_id):
        results[key] = run_agent(session_id, ["ds-1"], "q")

    with patch("graph.runner.agentic_ai.invoke", side_effect=_slow_invoke):
        t1 = threading.Thread(target=worker, args=("a", "sess-x"))
        t2 = threading.Thread(target=worker, args=("b", "sess-y"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert results["a"]["status"] == "completed"
    assert results["b"]["status"] == "completed"
