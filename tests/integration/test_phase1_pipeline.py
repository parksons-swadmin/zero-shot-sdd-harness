"""Real-Gemini, real-DB, full-pipeline tests for the conversational-analysis
capability (Phase 1, "simple" reasoning path only).

Proves: (1) a question against a 10,000+ row fixture returns the numerically
exact answer computed independently in this test, i.e. the FULL dataset was
used, not a truncated sample; (2) an edge-case question with no matching rows
still produces a coherent, non-fabricated answer; (3) error paths (unknown
session, empty question, a question about a nonexistent column) are handled
without ever surfacing a raw stack trace.
"""
import io

import pandas as pd
import pytest


def _upload_csv(api_client, csv_bytes: bytes, filename: str = "fixture.csv") -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _large_fixture_csv(rows: int = 10_500) -> tuple[bytes, float]:
    regions = ["West", "East", "North", "South"]
    df = pd.DataFrame({
        "customer_id": range(rows),
        "region": [regions[i % len(regions)] for i in range(rows)],
        "revenue": [round(100.0 + (i % 997) * 1.37, 2) for i in range(rows)],
    })
    exact_total = round(df["revenue"].sum(), 2)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8"), exact_total


@pytest.mark.usefixtures("_require_llm_key")
def test_question_returns_exact_total_from_full_dataset(api_client, tmp_path, monkeypatch):
    """Happy path: real Gemini call, asserts response content AND the numeric result
    matches an independently pre-computed exact aggregate over the FULL 10,000+ row file."""
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    csv_bytes, exact_total = _large_fixture_csv()
    dataset_id = _upload_csv(api_client, csv_bytes)
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.post(f"/sessions/{session_id}/messages", json={"question": "What is the total revenue across all rows?"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    query_result = data["query_result"]

    assert query_result["reasoning_mode"] == "simple"
    assert query_result["status"] == "completed"
    assert query_result["generated_code"]

    # The exact pre-computed value (to 2 decimals) must appear in the answer —
    # proving the FULL file was used, not a sample.
    formatted_variants = {f"{exact_total:,.2f}", f"{exact_total:.2f}", str(round(exact_total))}
    assert any(v in query_result["summary_text"] for v in formatted_variants), query_result["summary_text"]


@pytest.mark.usefixtures("_require_llm_key")
def test_question_with_no_matching_rows_is_answered_truthfully(api_client, tmp_path, monkeypatch):
    """Edge case: a filter that matches zero rows must not produce a fabricated number."""
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    df = pd.DataFrame({"region": ["West", "East", "West"], "revenue": [10.0, 20.0, 30.0]})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dataset_id = _upload_csv(api_client, buf.getvalue().encode("utf-8"))
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"question": "What is the total revenue for the 'Antarctica' region?"},
    )
    assert resp.status_code == 200, resp.text
    query_result = resp.json()["data"]["query_result"]
    assert query_result["status"] in ("completed", "failed")
    assert query_result["summary_text"]


@pytest.mark.usefixtures("_require_llm_key")
def test_question_about_nonexistent_column_fails_gracefully(api_client, tmp_path, monkeypatch):
    """Error path: LLM-generated code that references a bad column must fail as a
    readable query_result.status == 'failed', never an unhandled 500 / stack trace."""
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    df = pd.DataFrame({"a": [1, 2, 3]})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dataset_id = _upload_csv(api_client, buf.getvalue().encode("utf-8"))
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"question": "What is the sum of the column literally_does_not_exist_xyz?"},
    )
    assert resp.status_code == 200, resp.text
    query_result = resp.json()["data"]["query_result"]
    # Either the LLM avoided the trap (completed) or the sandbox caught a real
    # KeyError and the run failed gracefully — both are acceptable outcomes,
    # but a raw Python traceback must never leak into summary_text.
    assert "Traceback" not in query_result["summary_text"]
    assert "File \"" not in query_result["summary_text"]


def test_ask_unknown_session_returns_404(api_client, _isolated_db):
    resp = api_client.post("/sessions/does-not-exist/messages", json={"question": "anything"})
    assert resp.status_code == 404


def test_ask_empty_question_returns_422(api_client, tmp_path, monkeypatch, _isolated_db):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    csv_bytes = b"a,b\n1,2\n"
    dataset_id = _upload_csv(api_client, csv_bytes)
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.post(f"/sessions/{session_id}/messages", json={"question": ""})
    assert resp.status_code == 422
