"""Real-Gemini, real-SQLite cross-file analysis test (Phase 2).

Proves the headline Phase-2 capability: a single session opened over TWO
distinct uploaded files can answer a question that requires COMBINING both
dataframes (df + df2). Two small CSVs with the same schema are uploaded, one
session is created over both dataset_ids, and the agent is asked for the
combined revenue total. The answer must contain the EXACT independently
pre-computed sum of both files' totals — proving both frames were actually
loaded and combined, not just one.
"""
import io

import pandas as pd
import pytest


def _upload_csv(api_client, csv_bytes: bytes, filename: str) -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _normalize(text: str) -> str:
    return text.replace(",", "").replace("$", "").replace(" ", "")


@pytest.mark.usefixtures("_require_llm_key")
def test_combined_total_across_two_files(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    # Two distinct files, SAME schema, each with an independently exact total.
    df_month1 = pd.DataFrame({
        "region": ["West", "East", "North", "South"],
        "revenue": [1200.50, 3400.25, 875.00, 2610.75],
    })
    df_month2 = pd.DataFrame({
        "region": ["West", "East", "North", "South"],
        "revenue": [980.00, 4500.60, 1725.40, 3050.00],
    })
    total1 = round(df_month1["revenue"].sum(), 2)   # 8086.50
    total2 = round(df_month2["revenue"].sum(), 2)   # 10256.00
    combined = round(total1 + total2, 2)            # 18342.50

    ds1 = _upload_csv(api_client, _csv_bytes(df_month1), "month1.csv")
    ds2 = _upload_csv(api_client, _csv_bytes(df_month2), "month2.csv")
    session_id = _create_session(api_client, [ds1, ds2])

    resp = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"question": "What is the combined total revenue across both files?"},
    )
    assert resp.status_code == 200, resp.text
    query_result = resp.json()["data"]["query_result"]
    assert query_result["status"] in ("completed", "partial"), query_result
    assert query_result["summary_text"]

    normalized = _normalize(query_result["summary_text"])
    variants = {
        _normalize(f"{combined:,.2f}"),   # 18342.50
        _normalize(f"{combined:.1f}"),    # 18342.5
        _normalize(str(round(combined))), # 18343
    }
    assert any(v in normalized for v in variants), (
        f"combined total {combined} not found in answer: {query_result['summary_text']}"
    )
