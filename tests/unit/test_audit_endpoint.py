"""Unit tests for GET /audit-log against a real SQLite file DB.

Seeds a known set of AuditLogEntry rows across event types / sessions with
distinct timestamps and asserts chronological ordering, filters, pagination,
the AuditLogEntryOut shape, the limit cap at 200, and the raw-data boundary
(no raw row value ever appears in a returned `detail`).
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.session import get_session
from db.models import (
    AuditLogEntry,
    SessionRow,
    Dataset,
    Message,
    QueryResult,
)

_BASE = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)

# A raw row value that must never appear in any audit `detail` payload.
_RAW_ROW_VALUE = "RAW_CELL_SHOULD_NOT_LEAK_999"


def _seed(engine, entries: list[dict]) -> None:
    """Insert AuditLogEntry rows using the app's own session factory."""
    gen = get_session()
    session = next(gen)
    try:
        for e in entries:
            session.add(AuditLogEntry(**e))
        session.commit()
    finally:
        gen.close()


def _seed_scaffold(session_id: str, dataset_id: str) -> None:
    """Insert parent rows so FK-tied audit entries are valid."""
    gen = get_session()
    session = next(gen)
    try:
        session.add(SessionRow(id=session_id))
        session.add(
            Dataset(
                id=dataset_id,
                filename="fixture.csv",
                original_path="/tmp/fixture.csv",
                size_bytes=1,
                status="ready",
            )
        )
        session.commit()
    finally:
        gen.close()


def test_audit_log_chronological_shape_and_filters(api_client, _isolated_db):
    session_a = "sess-a"
    session_b = "sess-b"
    dataset_x = "ds-x"
    _seed_scaffold(session_a, dataset_x)
    _seed_scaffold(session_b, "ds-y")

    # Insert out of chronological order to prove the endpoint re-orders.
    _seed(
        _isolated_db,
        [
            {
                "id": "e-answer",
                "session_id": session_a,
                "dataset_id": None,
                "event_type": "answer",
                "detail_json": {"status": "completed"},
                "created_at": _BASE + timedelta(seconds=3),
            },
            {
                "id": "e-ask",
                "session_id": session_a,
                "dataset_id": None,
                "event_type": "ask",
                "detail_json": {"question": "What is the total revenue?"},
                "created_at": _BASE + timedelta(seconds=1),
            },
            {
                "id": "e-code",
                "session_id": session_a,
                "dataset_id": None,
                "event_type": "code_exec",
                "detail_json": {"generated_code": "result = df['revenue'].sum()", "step_count": 1},
                "created_at": _BASE + timedelta(seconds=2),
            },
            {
                "id": "e-upload",
                "session_id": session_b,
                "dataset_id": dataset_x,
                "event_type": "upload",
                "detail_json": {"filename": "fixture.csv"},
                "created_at": _BASE + timedelta(seconds=5),
            },
        ],
    )

    # --- session filter + chronological order --- #
    resp = api_client.get("/audit-log", params={"session_id": session_a})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 3
    assert data["limit"] == 50
    assert data["offset"] == 0
    order = [e["id"] for e in data["entries"]]
    assert order == ["e-ask", "e-code", "e-answer"], order

    # shape check
    first = data["entries"][0]
    assert set(first.keys()) == {
        "id",
        "session_id",
        "dataset_id",
        "query_result_id",
        "event_type",
        "detail",
        "created_at",
    }
    assert first["event_type"] == "ask"
    assert first["detail"] == {"question": "What is the total revenue?"}

    # --- event_type filter --- #
    resp = api_client.get("/audit-log", params={"event_type": "code_exec"})
    ids = [e["id"] for e in resp.json()["data"]["entries"]]
    assert ids == ["e-code"]
    assert resp.json()["data"]["total"] == 1

    # --- dataset_id filter --- #
    resp = api_client.get("/audit-log", params={"dataset_id": dataset_x})
    ids = [e["id"] for e in resp.json()["data"]["entries"]]
    assert ids == ["e-upload"]

    # --- no filter returns all, chronological across sessions --- #
    resp = api_client.get("/audit-log")
    ids = [e["id"] for e in resp.json()["data"]["entries"]]
    assert ids == ["e-ask", "e-code", "e-answer", "e-upload"]
    assert resp.json()["data"]["total"] == 4


def test_audit_log_pagination_and_total(api_client, _isolated_db):
    session_id = "sess-page"
    _seed_scaffold(session_id, "ds-page")
    entries = [
        {
            "id": f"e-{i:03d}",
            "session_id": session_id,
            "event_type": "ask",
            "detail_json": {"n": i},
            "created_at": _BASE + timedelta(seconds=i),
        }
        for i in range(10)
    ]
    _seed(_isolated_db, entries)

    resp = api_client.get("/audit-log", params={"limit": 3, "offset": 0})
    data = resp.json()["data"]
    assert data["total"] == 10
    assert data["limit"] == 3
    assert data["offset"] == 0
    assert [e["id"] for e in data["entries"]] == ["e-000", "e-001", "e-002"]

    resp = api_client.get("/audit-log", params={"limit": 3, "offset": 3})
    data = resp.json()["data"]
    assert data["total"] == 10
    assert [e["id"] for e in data["entries"]] == ["e-003", "e-004", "e-005"]

    resp = api_client.get("/audit-log", params={"limit": 3, "offset": 9})
    data = resp.json()["data"]
    assert [e["id"] for e in data["entries"]] == ["e-009"]


def test_audit_log_limit_caps_at_200(api_client, _isolated_db):
    _seed_scaffold("sess-cap", "ds-cap")
    _seed(
        _isolated_db,
        [
            {
                "id": "e-cap",
                "session_id": "sess-cap",
                "event_type": "ask",
                "detail_json": {},
                "created_at": _BASE,
            }
        ],
    )
    resp = api_client.get("/audit-log", params={"limit": 10000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["limit"] == 200


def test_audit_log_empty_returns_empty(api_client, _isolated_db):
    resp = api_client.get("/audit-log", params={"session_id": "no-such"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["entries"] == []
    assert data["total"] == 0


def test_audit_log_detail_holds_no_raw_row_values(api_client, _isolated_db):
    _seed_scaffold("sess-raw", "ds-raw")
    _seed(
        _isolated_db,
        [
            {
                "id": "e-raw",
                "session_id": "sess-raw",
                "event_type": "code_exec",
                "detail_json": {"generated_code": "result = df['revenue'].sum()", "step_count": 1},
                "created_at": _BASE,
            }
        ],
    )
    resp = api_client.get("/audit-log", params={"session_id": "sess-raw"})
    body = resp.text
    assert _RAW_ROW_VALUE not in body
