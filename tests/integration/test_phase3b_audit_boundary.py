"""Real-Gemini, real-SQLite Phase-3b audit-boundary integration test.

Runs a full upload + ask flow against the real model, then reads the trail via
`GET /audit-log?session_id=<id>` and asserts:

1. the run's audit entries are returned in chronological order (created_at ASC),
   and the expected event types (`ask`, `code_exec`, `answer`) are present; and
2. the RAW-DATA BOUNDARY holds — no raw row value from the fixture appears
   anywhere in the serialized audit response body. The audit read path returns
   metadata only and never joins to the source file.
"""
import io

import pandas as pd
import pytest

# A distinctive sentinel planted in exactly one raw row's memo. If it ever shows
# up in the audit response body, a raw row value leaked through the read path.
_SENTINEL_MEMO = "SENTINEL_AUDIT_DO_NOT_LEAK_777"


def _build_fixture() -> pd.DataFrame:
    regions = ["West", "East", "North", "South", "Central"]
    per_region_revenue = {"West": 10.0, "East": 20.0, "North": 30.0, "South": 40.0, "Central": 50.0}
    rows_per_region = 400
    records = []
    for region in regions:
        for i in range(rows_per_region):
            records.append(
                {
                    "region": region,
                    "revenue": per_region_revenue[region],
                    "memo": f"note_{i % 50}",
                    "row_uid": len(records),
                }
            )
    df = pd.DataFrame(records)
    east_idx = df.index[df["region"] == "East"][0]
    df.loc[east_idx, "memo"] = _SENTINEL_MEMO
    return df


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


@pytest.mark.usefixtures("_require_llm_key")
def test_phase3b_audit_boundary(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    df = _build_fixture()

    upload = api_client.post(
        "/datasets", files={"file": ("sales.csv", _csv_bytes(df), "text/csv")}
    )
    assert upload.status_code == 200, upload.text
    dataset_id = upload.json()["data"]["dataset_id"]

    create = api_client.post("/sessions", json={"dataset_ids": [dataset_id]})
    assert create.status_code == 200, create.text
    session_id = create.json()["data"]["session_id"]

    ask = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"question": "What is the total revenue?"},
    )
    assert ask.status_code == 200, ask.text

    # --- Read the audit trail for this session --- #
    resp = api_client.get("/audit-log", params={"session_id": session_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    entries = data["entries"]
    assert entries, "expected audit entries for the run"
    assert data["total"] == len(entries)

    # Chronological order (created_at ASC).
    created = [e["created_at"] for e in entries]
    assert created == sorted(created), f"entries not chronological: {created}"

    # The run's core event types are present.
    event_types = {e["event_type"] for e in entries}
    for expected in ("ask", "code_exec", "answer"):
        assert expected in event_types, f"missing {expected!r} in {event_types}"

    # Every returned entry belongs to this session.
    for e in entries:
        assert e["session_id"] == session_id

    # --- RAW-DATA BOUNDARY: no raw row value leaked into the audit body --- #
    assert _SENTINEL_MEMO not in resp.text, "a raw fixture row value leaked into the audit response"
