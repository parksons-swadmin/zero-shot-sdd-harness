"""Real-Gemini, real-SQLite Phase-3c streaming test.

Proves the headline Phase-3c streaming capability end to end against the real
model, per the roadmap gate:

1. `POST /sessions/{id}/messages/stream` emits >=1 `step` event (increasing
   `index`, human-readable `label`), >=1 `answer_chunk`, exactly one `result`
   event whose `query_result.summary_text` contains the pre-computed exact
   aggregate (full-data correctness) AND equals the concatenation of every
   `answer_chunk.text` (the stream reassembles to the final answer), then a
   terminal `done`.
2. The non-streaming `POST /sessions/{id}/messages` still answers the same
   question correctly (POST-path-unchanged regression).
3. RAW-DATA boundary: the concatenation of every SSE `data:` payload contains
   no raw fixture row value, and no prompt string sent to the model does either.
"""
import io
import json

import pandas as pd
import pytest

from llm.client import LLMClient

# A distinctive value planted in exactly one row's memo. It is never an
# aggregate and never a profile top-value (drowned out by the shared memos), so
# if it appears in any prompt or any SSE payload, a raw row leaked.
_SENTINEL_MEMO = "SENTINEL_STREAM_DO_NOT_LEAK_77"


def _fixture_csv(rows: int = 10_500) -> tuple[bytes, float]:
    df = pd.DataFrame({
        "customer_id": range(rows),
        "region": [["West", "East", "North", "South"][i % 4] for i in range(rows)],
        "revenue": [round(100.0 + (i % 997) * 1.37, 2) for i in range(rows)],
        "memo": [f"note_{i % 50}" for i in range(rows)],
    })
    df.loc[0, "memo"] = _SENTINEL_MEMO
    exact_total = round(df["revenue"].sum(), 2)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8"), exact_total


def _upload_csv(api_client, csv_bytes: bytes, filename: str = "stream.csv") -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse a raw SSE stream into a list of (event_type, data_dict)."""
    events: list[tuple[str, dict]] = []
    for frame in text.split("\n\n"):
        frame = frame.strip("\n")
        if not frame:
            continue
        event_type = None
        data_line = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data_line = line[len("data: "):]
        if event_type is not None and data_line is not None:
            events.append((event_type, json.loads(data_line)))
    return events


@pytest.fixture
def _prompt_spy(monkeypatch):
    """Record every prompt+system string sent to the model across BOTH the
    non-streaming and streaming LLM paths, then delegate to the real call."""
    seen: list[str] = []
    orig_usage = LLMClient.call_model_with_usage
    orig_stream = LLMClient.call_model_streaming

    def _spy_usage(self, prompt, *args, **kwargs):
        seen.append(prompt)
        if isinstance(kwargs.get("system"), str):
            seen.append(kwargs["system"])
        return orig_usage(self, prompt, *args, **kwargs)

    def _spy_stream(self, prompt, *args, **kwargs):
        seen.append(prompt)
        if isinstance(kwargs.get("system"), str):
            seen.append(kwargs["system"])
        return orig_stream(self, prompt, *args, **kwargs)

    monkeypatch.setattr(LLMClient, "call_model_with_usage", _spy_usage)
    monkeypatch.setattr(LLMClient, "call_model_streaming", _spy_stream)
    return seen


@pytest.mark.usefixtures("_require_llm_key")
def test_stream_reassembles_and_is_correct(api_client, tmp_path, monkeypatch, _prompt_spy):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    csv_bytes, exact_total = _fixture_csv()
    dataset_id = _upload_csv(api_client, csv_bytes)
    session_id = _create_session(api_client, [dataset_id])
    question = "What is the total revenue across all rows?"

    resp = api_client.post(f"/sessions/{session_id}/messages/stream", json={"question": question})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    types = [t for t, _ in events]

    steps = [d for t, d in events if t == "step"]
    chunks = [d for t, d in events if t == "answer_chunk"]
    results = [d for t, d in events if t == "result"]

    assert len(steps) >= 1, types
    assert [s["index"] for s in steps] == sorted(s["index"] for s in steps)
    assert steps[0]["index"] == 1
    assert all(s.get("label") for s in steps)

    assert len(chunks) >= 1, types
    assert len(results) == 1, types
    assert types[-1] == "done"

    query_result = results[0]["query_result"]
    summary = query_result["summary_text"]

    # Full-data correctness: the pre-computed exact aggregate appears in the answer.
    variants = {f"{exact_total:,.2f}", f"{exact_total:.2f}", str(round(exact_total))}
    assert any(v in summary for v in variants), summary

    # The stream reassembles to the final answer.
    assert "".join(c["text"] for c in chunks) == summary

    # Per-query cost rides the result event.
    assert query_result["cost"] is not None
    assert query_result["cost"]["estimated_cost_usd"] > 0

    # --- POST-path-unchanged regression --------------------------------- #
    resp2 = api_client.post(f"/sessions/{session_id}/messages", json={"question": question})
    assert resp2.status_code == 200, resp2.text
    summary2 = resp2.json()["data"]["query_result"]["summary_text"]
    assert any(v in summary2 for v in variants), summary2

    # --- RAW-DATA boundary ---------------------------------------------- #
    all_sse_data = "".join(json.dumps(d) for _, d in events)
    assert _SENTINEL_MEMO not in all_sse_data, "a raw row value leaked into an SSE payload"
    assert _prompt_spy, "no prompts captured — spy misconfigured"
    for prompt in _prompt_spy:
        assert _SENTINEL_MEMO not in prompt, "a raw row value leaked into an LLM prompt"


@pytest.mark.usefixtures("_require_llm_key")
def test_stream_unknown_session_returns_404(api_client, _isolated_db):
    resp = api_client.post("/sessions/nope/messages/stream", json={"question": "x"})
    assert resp.status_code == 404


@pytest.mark.usefixtures("_require_llm_key")
def test_stream_empty_question_returns_422(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    dataset_id = _upload_csv(api_client, b"a,b\n1,2\n")
    session_id = _create_session(api_client, [dataset_id])
    resp = api_client.post(f"/sessions/{session_id}/messages/stream", json={"question": "   "})
    assert resp.status_code == 422
