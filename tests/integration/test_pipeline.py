"""Integration tests for the FastAPI HTTP layer over the REAL AR pipeline.

No LLM, no DB, no network — the "real path" is the deterministic pandas pipeline
run against the committed ``ar_small.xlsx`` fixture, asserted against the
hand-authored oracle ``expected_small.json`` (see tests/fixtures/build_fixtures.py).

Aging depends on the reference date. The API has no ``as_of`` parameter (it is a
stateless "today" tool), so compute tests pin the clock to the fixture's anchor
``AS_OF = 2026-01-15`` via a scoped monkeypatch of ``graph.runner.date`` — the
sanctioned way tests inject a fixed ``as_of`` so buckets never go stale.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api import app

AS_OF = date(2026, 1, 15)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fixed_today(monkeypatch):
    """Pin ``graph.runner.date.today()`` to the fixture anchor date.

    The API path calls ``run_analysis`` without an ``as_of`` kwarg, so it falls
    back to ``date.today()``; pinning it makes the aging buckets reproducible and
    lets the response tie out exactly to ``expected_small.json``.
    """

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return AS_OF

    monkeypatch.setattr("graph.runner.date", _FixedDate)
    return AS_OF


def _mapping_from_preview(preview_data: dict) -> dict[str, str]:
    """Build the six-field mapping from preview's proposed matched columns."""
    mapping = {m["field"]: m["matched_column"] for m in preview_data["proposed_mapping"]}
    assert all(mapping[f] for f in mapping), "every field should auto-match on ar_small"
    return mapping


# --------------------------------------------------------------------------- #
# /api/preview — happy path
# --------------------------------------------------------------------------- #
def test_preview_proposes_mapping_and_flags(client, small_xlsx_bytes, expected_small):
    resp = client.post(
        "/api/preview",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    data = body["data"]

    # Six canonical fields proposed.
    proposed = data["proposed_mapping"]
    assert len(proposed) == 6
    status_by_field = {m["field"]: m["status"] for m in proposed}
    assert status_by_field["due_date"] == "low"
    for field in ("customer", "invoice_no", "invoice_date", "amount", "employee"):
        assert status_by_field[field] == "high", (field, status_by_field[field])

    # Parse-time flags include exactly the seeded bad rows (date-independent).
    seen = {(f["row_index"], f["reason"]) for f in data["parse_flags"]}
    for f in expected_small["flags"]:
        assert (f["row_index"], f["reason"]) in seen, f
    reasons = {f["reason"] for f in data["parse_flags"]}
    assert {"missing_due_date", "negative_amount", "zero_amount", "blank_employee"} <= reasons

    # Preview is capped at 10 rows.
    assert 0 < len(data["preview_rows"]) <= 10


# --------------------------------------------------------------------------- #
# /api/compute — exact tie-out to the oracle
# --------------------------------------------------------------------------- #
def test_compute_ties_out_to_oracle(client, small_xlsx_bytes, expected_small, fixed_today):
    # 1) Preview to obtain the mapping + sheet name, exactly like the frontend.
    pv = client.post(
        "/api/preview",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
    )
    assert pv.status_code == 200, pv.text
    preview_data = pv.json()["data"]
    mapping = _mapping_from_preview(preview_data)
    sheet_name = preview_data["sheet_name"]

    # 2) Compute with the confirmed mapping (file re-sent, per the stateless flow).
    resp = client.post(
        "/api/compute",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"sheet_name": sheet_name, "mapping": json.dumps(mapping)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    d = body["data"]

    # Exact tie-out to the hand-authored oracle.
    assert d["total_outstanding"] == expected_small["total_outstanding"]
    assert d["total_overdue"] == expected_small["total_overdue"]
    assert d["worst_bucket"] == "90+"
    assert d["customer_count"] == 5
    assert d["top_customers_by_overdue"][0]["customer"] == "Beacon & Co"

    # DashboardResult envelope fields.
    assert d["source_filename"] == "ar_small.xlsx"
    assert d["sheet_name"] == sheet_name
    assert d["as_of"] == AS_OF.isoformat()
    assert d["row_count"] == expected_small["row_count"]
    assert d["bucket_totals"] == expected_small["bucket_totals"]
    assert d["data_quality"]["flagged_row_count"] == expected_small["data_quality"]["flagged_row_count"]
    assert d["data_quality"]["by_reason"] == expected_small["data_quality"]["by_reason"]


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #
def _assert_error_shape(resp, expected_status: int, code: str | None = None):
    assert resp.status_code == expected_status, resp.text
    detail = resp.json()["detail"]
    assert set(detail.keys()) >= {"code", "message"}, detail
    assert isinstance(detail["message"], str) and detail["message"]
    if code is not None:
        assert detail["code"] == code
    return detail


def test_preview_rejects_csv(client):
    """A .csv is not a readable .xlsx workbook → 400 naming the accepted format."""
    resp = client.post(
        "/api/preview",
        files={"file": ("data.csv", b"a,b,c\n1,2,3\n4,5,6\n", "text/csv")},
    )
    detail = _assert_error_shape(resp, 400)
    assert ".xlsx" in detail["message"]


def test_preview_rejects_xls(client):
    """An old-format .xls is not openpyxl-readable → 400 naming .xlsx."""
    resp = client.post(
        "/api/preview",
        files={"file": ("legacy.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1garbage", "application/vnd.ms-excel")},
    )
    detail = _assert_error_shape(resp, 400)
    assert ".xlsx" in detail["message"]


def test_compute_rejects_missing_required_field(client, small_xlsx_bytes):
    """A mapping missing a required canonical field → 400 BAD_MAPPING."""
    incomplete = {
        "customer": "Cust Name",
        "invoice_no": "Invoice #",
        "invoice_date": "Inv. Date",
        "due_date": "Payable On",
        "amount": "Balance Outstanding",
        # employee intentionally omitted
    }
    resp = client.post(
        "/api/compute",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"mapping": json.dumps(incomplete)},
    )
    _assert_error_shape(resp, 400, "BAD_MAPPING")


def test_compute_rejects_duplicate_column(client, small_xlsx_bytes):
    """Mapping the same source column to two fields → 400 BAD_MAPPING."""
    dup = {
        "customer": "Cust Name",
        "invoice_no": "Invoice #",
        "invoice_date": "Inv. Date",
        "due_date": "Inv. Date",  # duplicate of invoice_date
        "amount": "Balance Outstanding",
        "employee": "Sales Person",
    }
    resp = client.post(
        "/api/compute",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"mapping": json.dumps(dup)},
    )
    _assert_error_shape(resp, 400, "BAD_MAPPING")


def test_compute_rejects_nonexistent_column(client, small_xlsx_bytes):
    """Mapping a field to a column not present in the sheet → 400 BAD_MAPPING."""
    bad = {
        "customer": "Cust Name",
        "invoice_no": "Invoice #",
        "invoice_date": "Inv. Date",
        "due_date": "No Such Column",  # not in the sheet
        "amount": "Balance Outstanding",
        "employee": "Sales Person",
    }
    resp = client.post(
        "/api/compute",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"mapping": json.dumps(bad)},
    )
    _assert_error_shape(resp, 400, "BAD_MAPPING")
