"""Unit tests for the Phase-3c streaming runner and compose_answer sink-gating.

The LLM is mocked at ``LLMClient`` (no network) and the compiled graph is
replaced with a lightweight fake for the runner tests. Proves:

  * ``run_agent_streaming`` emits ``step`` events in node order with a
    monotonically increasing 1-based ``index``, at least one ``answer_chunk``,
    exactly one ``result`` (the last non-sentinel event), then a ``done``.
  * ``format_sse_event`` produces well-formed ``event:``/``data:`` frames.
  * ``compose_answer`` makes the NON-streaming call when no event sink is set
    (POST-path-unchanged guard) and the STREAMING call when a sink is set,
    with the concatenated chunks reassembling to the final summary_text.
"""
import json
from unittest.mock import patch

import graph.runner as runner_module
from graph.nodes import compose_answer
from graph.runner import (
    _answer_chunk_sink,
    format_sse_event,
    get_answer_chunk_sink,
    run_agent_streaming,
)


# --------------------------------------------------------------------------- #
# format_sse_event
# --------------------------------------------------------------------------- #

def test_format_sse_event_is_well_formed():
    frame = format_sse_event("step", {"index": 1, "node": "load_context"})
    assert frame.startswith("event: step\n")
    assert "\ndata: " in frame
    assert frame.endswith("\n\n")
    data_line = frame.split("\ndata: ", 1)[1].rstrip("\n")
    assert json.loads(data_line) == {"index": 1, "node": "load_context"}
    # The data payload must be a single line so the client can split on \n\n.
    assert "\n" not in data_line


# --------------------------------------------------------------------------- #
# run_agent_streaming event emission
# --------------------------------------------------------------------------- #

class _FakeGraph:
    """Stands in for the compiled LangGraph: yields one {node: delta} update
    per node on `.stream(...)`, pushing two answer chunks while 'composing'."""

    def stream(self, initial, stream_mode="updates"):
        yield {"load_context": {}}
        yield {"classify_query": {"reasoning_mode": "simple"}}
        yield {"generate_code": {}}
        yield {"execute_code": {}}
        sink = get_answer_chunk_sink()
        assert sink is not None, "the answer-chunk sink must be active during the run"
        sink("Hello ")
        sink("world")
        yield {"compose_answer": {}}
        yield {"finalize": {"message_id": "m1", "query_result_id": "qr1", "status": "completed"}}


def _collect(session_id="sess-stream"):
    return list(run_agent_streaming(session_id, ["ds-1"], "q"))


def test_run_agent_streaming_emits_steps_chunks_result_done(monkeypatch):
    monkeypatch.setattr(runner_module, "agentic_ai", _FakeGraph())
    events = _collect()

    steps = [e for e in events if e["event"] == "step"]
    chunks = [e for e in events if e["event"] == "answer_chunk"]
    results = [e for e in events if e["event"] == "result"]

    assert [s["data"]["node"] for s in steps] == [
        "load_context", "classify_query", "generate_code",
        "execute_code", "compose_answer", "finalize",
    ]
    # 1-based, strictly increasing index; each has a human-readable label.
    assert [s["data"]["index"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert all(s["data"]["label"] for s in steps)
    assert all(s["data"]["total_estimate"] >= 1 for s in steps)

    assert len(chunks) >= 1
    assert "".join(c["data"]["text"] for c in chunks) == "Hello world"

    assert len(results) == 1
    assert results[0]["query_result_id"] == "qr1"
    assert results[0]["message_id"] == "m1"

    # Terminal frame is exactly one `done`, and it is last.
    assert events[-1]["event"] == "done"
    assert sum(1 for e in events if e["event"] == "done") == 1
    # The result is the last non-sentinel event.
    assert events[-2]["event"] == "result"


class _FailingGraph:
    def stream(self, initial, stream_mode="updates"):
        yield {"load_context": {}}
        yield {"handle_error": {"status": "failed", "error": "Something readable went wrong."}}


def test_run_agent_streaming_emits_error_on_failed_run(monkeypatch):
    monkeypatch.setattr(runner_module, "agentic_ai", _FailingGraph())
    events = _collect("sess-fail")

    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["data"]["status"] == "failed"
    assert errors[0]["data"]["message"] == "Something readable went wrong."
    assert not any(e["event"] == "result" for e in events)
    assert events[-1]["event"] == "done"


def test_run_agent_streaming_lock_released_between_runs(monkeypatch):
    """A second stream for the same session succeeds after the first drains —
    proving the per-session lock is released in the worker's finally block."""
    monkeypatch.setattr(runner_module, "agentic_ai", _FakeGraph())
    _collect("sess-reuse")
    events = _collect("sess-reuse")  # would raise SessionBusyError if not released
    assert any(e["event"] == "result" for e in events)


# --------------------------------------------------------------------------- #
# compose_answer sink-gating
# --------------------------------------------------------------------------- #

_COMPOSE_STATE = {
    "run_id": "r1", "question": "What is the total?", "accumulated_summaries": [],
    "conversation_history": [], "profiles": [], "execution_result": {}, "cost_records": [],
}

_ANSWER = "The total revenue is **$6.00**.\n---FOLLOW-UPS---\n- What about by region?"


def _mock_with_usage(self, prompt, *, system=None, model=None):
    return _ANSWER, {"model": "gemini-3.1-pro", "prompt_tokens": 5, "completion_tokens": 3}


def _mock_streaming(self, prompt, *, system=None, model=None, on_chunk=None):
    # Simulate token streaming of the full response, including the trailing
    # follow-ups block that must NOT leak into answer_chunks.
    for piece in ["The total ", "revenue is **$6.00**.", "\n---FOLLOW-UPS---\n- What about by region?"]:
        if on_chunk is not None:
            on_chunk(piece)
    return _ANSWER, {"model": "gemini-3.1-pro", "prompt_tokens": 5, "completion_tokens": 3}


def test_compose_answer_uses_non_streaming_when_no_sink():
    def _must_not_stream(self, *a, **k):
        raise AssertionError("streaming path must not run without an event sink")

    assert get_answer_chunk_sink() is None
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_with_usage), \
         patch("llm.client.LLMClient.call_model_streaming", _must_not_stream):
        result = compose_answer(dict(_COMPOSE_STATE))
    assert result.get("error") is None
    assert result["answer_text"] == "The total revenue is **$6.00**."
    assert result["follow_up_questions"] == ["What about by region?"]


def test_compose_answer_streams_prose_only_when_sink_set():
    captured: list[str] = []
    token = _answer_chunk_sink.set(lambda text: captured.append(text))
    try:
        def _must_not_call_sync(self, *a, **k):
            raise AssertionError("non-streaming path must not run when a sink is set")

        with patch("llm.client.LLMClient.call_model_streaming", _mock_streaming), \
             patch("llm.client.LLMClient.call_model_with_usage", _must_not_call_sync):
            result = compose_answer(dict(_COMPOSE_STATE))
    finally:
        _answer_chunk_sink.reset(token)

    assert result.get("error") is None
    assert result["answer_text"] == "The total revenue is **$6.00**."
    # Concatenated chunks reassemble to the summary_text exactly — the trailing
    # ---FOLLOW-UPS--- block never leaks into a chunk.
    assert "".join(captured) == result["answer_text"]
    assert "---FOLLOW-UPS---" not in "".join(captured)
