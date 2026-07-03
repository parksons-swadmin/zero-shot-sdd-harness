"""Real-Gemini, real-SQLite Phase-3b anomaly test.

Proves the Phase-3b anomaly capability end to end against the real model:

1. A fixture CSV with (a) a CONSTANT column (`data_source`, single value on
   every row) and (b) a column with a deliberate NULL SPIKE (`region` null on a
   known fraction of rows), alongside a clean numeric `revenue` column, yields a
   non-empty `query_result.anomaly_flags` that contains at least a
   `constant_column` flag for `data_source` and a `null_values` flag for
   `region` — guaranteed by the deterministic `_profile_anomalies` check, so
   this assertion cannot flake on model behaviour. Each flag matches the
   `{type, column, severity, message}` shape.
2. RAW-DATA boundary: a spy over every prompt string passed to
   `LLMClient.call_model_with_usage` asserts no raw fixture row value ever
   reaches the model — only aggregate profile fields + capped structured
   results.
"""
import io

import pandas as pd
import pytest

from llm.client import LLMClient

# A distinctive sentinel that lives in exactly one row's free-text memo. It is
# never an aggregate, never a profile top-value (drowned out by the shared
# "note_*" memos), and never numeric — if it appears in a prompt, a raw row
# leaked into the model.
_SENTINEL_MEMO = "SENTINEL_ZZZ_DO_NOT_LEAK_42"


def _build_fixture() -> tuple[pd.DataFrame, dict]:
    """10,000 rows: a constant column, a null-spiked column, a clean numeric
    column with a pre-computed total, and a noisy memo column."""
    rows = 10_000
    revenue_per_row = 5.0
    regions = ["West", "East", "North", "South", "Central"]

    records = []
    for i in range(rows):
        # Null spike: every 4th row's region is missing (a genuine null spike).
        region = None if i % 4 == 0 else regions[i % len(regions)]
        records.append({
            "data_source": "crm_export_v1",   # constant on every row
            "region": region,                  # null spike
            "revenue": revenue_per_row,        # clean numeric
            "memo": f"note_{i % 50}",
            "row_uid": i,
        })
    df = pd.DataFrame(records)

    # Plant the sentinel in one row's memo.
    df.loc[0, "memo"] = _SENTINEL_MEMO

    expected_total = round(revenue_per_row * rows, 2)
    null_region_count = int(df["region"].isna().sum())
    return df, {"expected_total": expected_total, "null_region_count": null_region_count}


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _upload_csv(api_client, csv_bytes: bytes, filename: str) -> str:
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


@pytest.fixture
def _prompt_spy(monkeypatch):
    """Record every prompt+system string sent to the model, then delegate to
    the real call so the model still runs for real."""
    seen: list[str] = []
    original = LLMClient.call_model_with_usage

    def _spy(self, prompt, *args, **kwargs):
        seen.append(prompt)
        system = kwargs.get("system")
        if isinstance(system, str):
            seen.append(system)
        return original(self, prompt, *args, **kwargs)

    monkeypatch.setattr(LLMClient, "call_model_with_usage", _spy)
    return seen


@pytest.mark.usefixtures("_require_llm_key")
def test_phase3b_anomaly_flags(api_client, tmp_path, monkeypatch, _prompt_spy):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    df, meta = _build_fixture()
    dataset_id = _upload_csv(api_client, _csv_bytes(df), "sales_anomalous.csv")
    session_id = _create_session(api_client, [dataset_id])

    qr = _ask(api_client, session_id, "What is the total revenue?")
    assert qr["status"] in ("completed", "partial"), qr

    # --- 1. Anomaly flags present, correctly shaped, cover both signals ----- #
    flags = qr["anomaly_flags"]
    assert flags, f"expected non-empty anomaly_flags, got: {flags!r}"

    for flag in flags:
        assert set(flag.keys()) >= {"type", "column", "severity", "message"}, flag
        assert isinstance(flag["type"], str) and flag["type"]
        assert flag["column"] is None or isinstance(flag["column"], str)
        assert flag["severity"] in ("info", "warning", "critical"), flag
        assert isinstance(flag["message"], str) and flag["message"]

    constant_flags = [f for f in flags if f["type"] == "constant_column" and f["column"] == "data_source"]
    assert constant_flags, f"expected a constant_column flag for data_source: {flags}"

    null_flags = [f for f in flags if f["type"] == "null_values" and f["column"] == "region"]
    assert null_flags, f"expected a null_values flag for region: {flags}"

    # --- 2. RAW-DATA boundary: no raw row value ever reached the model ------ #
    assert _prompt_spy, "no prompts were captured — spy misconfigured"
    for prompt in _prompt_spy:
        assert _SENTINEL_MEMO not in prompt, "a raw fixture row value leaked into an LLM prompt"
