"""Real-Gemini, real-SQLite adaptive multi-step reasoning test (Phase 2).

Proves the headline Phase-2 capability: a genuinely multi-part question is
routed to a multi-step reasoning mode ("planned"/"iterative") by
classify_query and actually executes more than one analysis step end-to-end.
The question asks for TWO distinct things — an overall total AND a per-group
average — which cannot be answered by a single `result = ...` line. We assert
the STORED QueryResult escalated (reasoning_mode + step_count > 1) AND that the
answer contains both independently pre-computed values. This must NOT be tuned
to pass trivially: if the router refuses to escalate a legitimately hard
question, that is a real bug to fix in classify_query, not a test to weaken.
"""
import io

import pandas as pd
import pytest


def _upload_csv(api_client, csv_bytes: bytes, filename: str = "sales.csv") -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _normalize(text: str) -> str:
    return text.replace(",", "").replace("$", "").replace(" ", "")


@pytest.mark.usefixtures("_require_llm_key")
def test_multi_part_question_triggers_multistep_reasoning(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    # 3 regions x 3 rows: a single result line cannot cleanly answer BOTH
    # "overall revenue total" AND "average units_sold per region".
    df = pd.DataFrame({
        "region": ["West", "West", "West", "East", "East", "East", "North", "North", "North"],
        "revenue": [1000, 1500, 2000, 3000, 1000, 2000, 2000, 2500, 1500],
        "units_sold": [100, 150, 200, 300, 400, 500, 200, 250, 300],
    })
    total_revenue = int(df["revenue"].sum())                        # 16500
    east_avg_units = int(df[df["region"] == "East"]["units_sold"].mean())  # 400

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dataset_id = _upload_csv(api_client, buf.getvalue().encode("utf-8"))
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"question": "What is the total revenue overall, and separately what is the average units_sold per region?"},
    )
    assert resp.status_code == 200, resp.text
    query_result = resp.json()["data"]["query_result"]
    assert query_result["status"] in ("completed", "partial"), query_result

    # The multi-step path must have fired end-to-end.
    assert query_result["reasoning_mode"] in ("planned", "iterative"), (
        f"expected escalation, got reasoning_mode={query_result['reasoning_mode']}"
    )
    assert query_result["step_count"] > 1, (
        f"expected multiple steps, got step_count={query_result['step_count']}"
    )

    # Both correct, pre-computed values must appear in the answer.
    normalized = _normalize(query_result["summary_text"])
    assert _normalize(str(total_revenue)) in normalized, (
        f"overall revenue {total_revenue} missing from answer: {query_result['summary_text']}"
    )
    assert _normalize(str(east_avg_units)) in normalized, (
        f"East avg units {east_avg_units} missing from answer: {query_result['summary_text']}"
    )
