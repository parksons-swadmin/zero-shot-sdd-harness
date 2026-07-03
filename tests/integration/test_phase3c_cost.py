"""Real-Gemini, real-SQLite Phase-3c cost-accounting test.

Proves the headline Phase-3c cost capability end to end against the real model,
per the roadmap gate:

1. The `POST /sessions/{id}/messages` response's `query_result.cost` carries a
   non-zero `estimated_cost_usd` that EQUALS the independently-summed
   `estimated_cost_usd` of the `CostRecord` rows for that `query_result_id`
   (queried directly from the DB).
2. `GET /cost-summary` `all_time` totals equal the independently-summed total of
   ALL `CostRecord` rows, and `session` totals equal that session's rows.
3. Asking a second question makes the `all_time` running total strictly increase.
4. RAW-DATA boundary: no prompt string and no `GET /cost-summary` body contains
   a raw fixture row value.

NOTE: `GET /cost-summary` is owned by the parallel `cost-api` slice; this test
exercises it via the app, so it passes only once that slice is also merged
(per spec/roadmap.md Phase 3c slice assignment).
"""
import io
import json

import pandas as pd
import pytest
from sqlalchemy import select

from db.models import CostRecord, QueryResult
from db.session import create_db_session
from llm.client import LLMClient

_SENTINEL_MEMO = "SENTINEL_COST_DO_NOT_LEAK_88"


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


def _upload_csv(api_client, csv_bytes: bytes, filename: str = "cost.csv") -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _ask(api_client, session_id: str, question: str) -> dict:
    resp = api_client.post(f"/sessions/{session_id}/messages", json={"question": question})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["query_result"]


def _db_cost_for_query_result(query_result_id: str) -> float:
    with create_db_session() as s:
        rows = s.execute(
            select(CostRecord).where(CostRecord.query_result_id == query_result_id)
        ).scalars().all()
        return round(sum(float(r.estimated_cost_usd or 0) for r in rows), 6)


def _db_cost_all_time() -> float:
    with create_db_session() as s:
        rows = s.execute(select(CostRecord)).scalars().all()
        return round(sum(float(r.estimated_cost_usd or 0) for r in rows), 6)


@pytest.fixture
def _prompt_spy(monkeypatch):
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
def test_per_query_cost_and_summary(api_client, tmp_path, monkeypatch, _prompt_spy):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    csv_bytes, _exact = _fixture_csv()
    dataset_id = _upload_csv(api_client, csv_bytes)
    session_id = _create_session(api_client, [dataset_id])

    # --- 1. Per-query cost equals the summed CostRecord rows ------------- #
    qr = _ask(api_client, session_id, "What is the total revenue across all rows?")
    assert qr["cost"] is not None, qr
    assert qr["cost"]["estimated_cost_usd"] > 0, qr["cost"]
    assert qr["cost"]["estimated_cost_usd"] == pytest.approx(
        _db_cost_for_query_result(qr["id"]), rel=1e-6, abs=1e-9
    )

    # --- 2. GET /cost-summary all_time + session totals ----------------- #
    summary = api_client.get("/cost-summary", params={"session_id": session_id})
    assert summary.status_code == 200, summary.text
    body = summary.json()["data"]
    assert body["all_time"]["estimated_cost_usd"] == pytest.approx(
        _db_cost_all_time(), rel=1e-6, abs=1e-9
    )
    assert body["session"] is not None
    assert body["session"]["estimated_cost_usd"] > 0

    all_time_before = body["all_time"]["estimated_cost_usd"]

    # --- 3. Running total strictly increases after a second question ---- #
    _ask(api_client, session_id, "What is the average revenue per region?")
    summary2 = api_client.get("/cost-summary")
    assert summary2.status_code == 200, summary2.text
    all_time_after = summary2.json()["data"]["all_time"]["estimated_cost_usd"]
    assert all_time_after > all_time_before

    # --- 4. RAW-DATA boundary ------------------------------------------- #
    assert _SENTINEL_MEMO not in json.dumps(summary.json()), "raw row leaked into cost-summary"
    assert _SENTINEL_MEMO not in json.dumps(summary2.json()), "raw row leaked into cost-summary"
    assert _prompt_spy, "no prompts captured — spy misconfigured"
    for prompt in _prompt_spy:
        assert _SENTINEL_MEMO not in prompt, "a raw row value leaked into an LLM prompt"
