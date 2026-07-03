"""Unit tests for GET /cost-summary against a real SQLite file DB.

Seeds QueryResult + CostRecord rows across two sessions, then asserts:
- all_time totals equal an independently-summed total of every CostRecord;
- a session_id filter scopes to that session's rows only;
- an empty / over-filtered result returns zeroed totals (no error case);
- the raw-data boundary: no raw row value ever appears in the payload
  (only token counts / cost figures / call counts).
"""
from decimal import Decimal

from db.session import get_session
from db.models import CostRecord, QueryResult, Message, SessionRow

# A raw row value that must never appear in any cost-summary payload.
_RAW_ROW_VALUE = "RAW_CELL_SHOULD_NOT_LEAK_999"

_IN_PRICE = 0.000075  # AGENT_GEMINI_INPUT_PRICE_PER_1K (settings default)
_OUT_PRICE = 0.0003   # AGENT_GEMINI_OUTPUT_PRICE_PER_1K (settings default)


def _price(prompt: int, completion: int) -> float:
    """Estimated USD cost from the Gemini price table (per 1K tokens)."""
    return round(prompt / 1000 * _IN_PRICE + completion / 1000 * _OUT_PRICE, 10)


def _seed_scaffold(session_id: str) -> None:
    gen = get_session()
    session = next(gen)
    try:
        session.add(SessionRow(id=session_id))
        session.commit()
    finally:
        gen.close()


def _seed_query_result(qr_id: str, session_id: str) -> None:
    gen = get_session()
    session = next(gen)
    try:
        msg_id = f"msg-{qr_id}"
        session.add(
            Message(id=msg_id, session_id=session_id, role="assistant", content="answer")
        )
        session.add(
            QueryResult(
                id=qr_id,
                message_id=msg_id,
                session_id=session_id,
                reasoning_mode="simple",
                summary_text="answer",
                generated_code="result = df['revenue'].sum()",
                step_count=1,
                status="completed",
            )
        )
        session.commit()
    finally:
        gen.close()


def _seed_cost(records: list[dict]) -> None:
    gen = get_session()
    session = next(gen)
    try:
        for r in records:
            session.add(CostRecord(**r))
        session.commit()
    finally:
        gen.close()


def test_cost_summary_all_time_and_session_totals(api_client, _isolated_db):
    _seed_scaffold("sess-a")
    _seed_scaffold("sess-b")
    _seed_query_result("qr-a1", "sess-a")
    _seed_query_result("qr-a2", "sess-a")
    _seed_query_result("qr-b1", "sess-b")

    records = [
        # sess-a
        {"id": "c1", "query_result_id": "qr-a1", "provider": "gemini",
         "model": "gemini-2.5-flash", "prompt_tokens": 1000, "completion_tokens": 100,
         "estimated_cost_usd": Decimal(str(_price(1000, 100)))},
        {"id": "c2", "query_result_id": "qr-a1", "provider": "gemini",
         "model": "gemini-2.5-flash", "prompt_tokens": 2000, "completion_tokens": 200,
         "estimated_cost_usd": Decimal(str(_price(2000, 200)))},
        {"id": "c3", "query_result_id": "qr-a2", "provider": "gemini",
         "model": "gemini-2.5-flash", "prompt_tokens": 500, "completion_tokens": 40,
         "estimated_cost_usd": Decimal(str(_price(500, 40)))},
        # sess-b
        {"id": "c4", "query_result_id": "qr-b1", "provider": "gemini",
         "model": "gemini-2.5-flash", "prompt_tokens": 300, "completion_tokens": 30,
         "estimated_cost_usd": Decimal(str(_price(300, 30)))},
        # untied (failed run — no query_result_id): counts toward all_time only
        {"id": "c5", "query_result_id": None, "provider": "gemini",
         "model": "gemini-2.5-flash", "prompt_tokens": 700, "completion_tokens": 0,
         "estimated_cost_usd": Decimal(str(_price(700, 0)))},
    ]
    _seed_cost(records)

    # --- independent sums --- #
    all_prompt = sum(r["prompt_tokens"] for r in records)
    all_completion = sum(r["completion_tokens"] for r in records)
    all_cost = float(sum(r["estimated_cost_usd"] for r in records))
    all_count = len(records)

    sess_a = [r for r in records if r["query_result_id"] in ("qr-a1", "qr-a2")]
    a_prompt = sum(r["prompt_tokens"] for r in sess_a)
    a_completion = sum(r["completion_tokens"] for r in sess_a)
    a_cost = float(sum(r["estimated_cost_usd"] for r in sess_a))
    a_count = len(sess_a)

    # --- all_time only (no session_id) --- #
    resp = api_client.get("/cost-summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["session"] is None
    at = data["all_time"]
    assert at["prompt_tokens"] == all_prompt
    assert at["completion_tokens"] == all_completion
    assert at["call_count"] == all_count
    assert at["estimated_cost_usd"] == round(all_cost, 10)

    # --- session-scoped --- #
    resp = api_client.get("/cost-summary", params={"session_id": "sess-a"})
    data = resp.json()["data"]
    assert data["all_time"]["call_count"] == all_count  # unchanged
    s = data["session"]
    assert s["prompt_tokens"] == a_prompt
    assert s["completion_tokens"] == a_completion
    assert s["call_count"] == a_count  # 3 rows — excludes untied c5 and sess-b
    assert s["estimated_cost_usd"] == round(a_cost, 10)


def test_cost_summary_empty_db_returns_zeros(api_client, _isolated_db):
    resp = api_client.get("/cost-summary")
    assert resp.status_code == 200, resp.text
    at = resp.json()["data"]["all_time"]
    assert at == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "call_count": 0,
    }
    assert resp.json()["data"]["session"] is None


def test_cost_summary_unknown_session_returns_zeros(api_client, _isolated_db):
    _seed_scaffold("sess-a")
    _seed_query_result("qr-a1", "sess-a")
    _seed_cost(
        [
            {"id": "c1", "query_result_id": "qr-a1", "provider": "gemini",
             "model": "gemini-2.5-flash", "prompt_tokens": 100, "completion_tokens": 10,
             "estimated_cost_usd": Decimal(str(_price(100, 10)))},
        ]
    )
    resp = api_client.get("/cost-summary", params={"session_id": "no-such-session"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["session"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "call_count": 0,
    }
    # all_time still reflects the one real row
    assert data["all_time"]["call_count"] == 1


def test_cost_summary_payload_holds_no_raw_row_values(api_client, _isolated_db):
    _seed_scaffold("sess-raw")
    _seed_query_result("qr-raw", "sess-raw")
    _seed_cost(
        [
            {"id": "c-raw", "query_result_id": "qr-raw", "provider": "gemini",
             "model": "gemini-2.5-flash", "prompt_tokens": 100, "completion_tokens": 10,
             "estimated_cost_usd": Decimal(str(_price(100, 10)))},
        ]
    )
    resp = api_client.get("/cost-summary", params={"session_id": "sess-raw"})
    body = resp.text
    assert _RAW_ROW_VALUE not in body
    # payload keys are strictly token/cost/count — no row-shaped fields
    s = resp.json()["data"]["session"]
    assert set(s.keys()) == {
        "prompt_tokens",
        "completion_tokens",
        "estimated_cost_usd",
        "call_count",
    }
