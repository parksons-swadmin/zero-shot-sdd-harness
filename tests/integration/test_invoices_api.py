"""Integration tests for ``POST /api/invoices`` — invoice-level drill-down.

Runs the REAL deterministic pipeline (no LLM / DB / network) over the committed
``ar_small.xlsx`` fixture via FastAPI's ``TestClient``. The drill-down reuses the
canonical normalize (with embedded summary/total exclusion), so:

- an unfiltered list's ``subtotal_amount`` ties out to the dashboard's
  ``total_outstanding`` exactly, and its ``total_count`` equals the non-summary
  row count,
- ``customer`` / ``employee`` filters scope the list exactly (ANDed), and each
  scoped subtotal ties out to the matching dashboard rollup.

Aging depends on the reference date; the API has no ``as_of`` parameter, so these
tests pin ``graph.runner.date.today()`` to the fixture anchor ``2026-01-15`` (the
same sanctioned mechanism used by test_pipeline.py) so buckets never go stale.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api import app

AS_OF = date(2026, 1, 15)

MAPPING = {
    "customer": "Cust Name",
    "invoice_no": "Invoice #",
    "invoice_date": "Inv. Date",
    "due_date": "Payable On",
    "amount": "Balance Outstanding",
    "employee": "Sales Person",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fixed_today(monkeypatch):
    """Pin ``graph.runner.date.today()`` to the fixture anchor date."""

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return AS_OF

    monkeypatch.setattr("graph.runner.date", _FixedDate)
    return AS_OF


def _post_invoices(client, file_bytes, *, customer=None, employee=None, mapping=None):
    data = {"mapping": json.dumps(mapping if mapping is not None else MAPPING)}
    if customer is not None:
        data["customer"] = customer
    if employee is not None:
        data["employee"] = employee
    return client.post(
        "/api/invoices",
        files={"file": ("ar_small.xlsx", file_bytes, "application/octet-stream")},
        data=data,
    )


def _assert_error_shape(resp, expected_status: int, code: str | None = None):
    assert resp.status_code == expected_status, resp.text
    detail = resp.json()["detail"]
    assert set(detail.keys()) >= {"code", "message"}, detail
    assert isinstance(detail["message"], str) and detail["message"]
    if code is not None:
        assert detail["code"] == code
    return detail


# --------------------------------------------------------------------------- #
# (a) No filter — ties out to the dashboard total, excludes summary/total rows.
# --------------------------------------------------------------------------- #
def test_invoices_no_filter_ties_out(client, small_xlsx_bytes, expected_small, fixed_today):
    resp = _post_invoices(client, small_xlsx_bytes)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    d = body["data"]

    # One row per non-summary invoice; the small set is under the cap.
    assert d["total_count"] == expected_small["row_count"]
    assert len(d["invoices"]) == expected_small["row_count"]
    assert d["truncated"] is False

    # Subtotal (summed exact paise -> rupees) equals the dashboard total exactly.
    assert d["subtotal_amount"] == expected_small["total_outstanding"]

    # No embedded grand-total / summary row leaked into the drill-down.
    labels = {r["customer"].lower() for r in d["invoices"]}
    assert not any("total" in label for label in labels)

    # Row envelope shape.
    row = d["invoices"][0]
    assert set(row.keys()) == {
        "customer",
        "invoice_no",
        "amount",
        "due_date",
        "days_overdue",
        "bucket",
        "employee",
    }


# --------------------------------------------------------------------------- #
# (b) Customer filter — only that customer, subtotal == its outstanding.
# --------------------------------------------------------------------------- #
def test_invoices_customer_filter(client, small_xlsx_bytes, expected_small, fixed_today):
    resp = _post_invoices(client, small_xlsx_bytes, customer="Beacon & Co")
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]

    assert d["truncated"] is False
    assert d["total_count"] == len(d["invoices"]) > 0
    assert {r["customer"] for r in d["invoices"]} == {"Beacon & Co"}

    beacon = next(
        c for c in expected_small["top_customers_by_overdue"] if c["customer"] == "Beacon & Co"
    )
    assert d["subtotal_amount"] == beacon["outstanding_amount"]


# --------------------------------------------------------------------------- #
# (c) Employee filter — only that employee, subtotal == its outstanding.
# --------------------------------------------------------------------------- #
def test_invoices_employee_filter(client, small_xlsx_bytes, expected_small, fixed_today):
    resp = _post_invoices(client, small_xlsx_bytes, employee="Ravi")
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]

    assert d["truncated"] is False
    assert {r["employee"] for r in d["invoices"]} == {"Ravi"}

    ravi = next(e for e in expected_small["employees"] if e["employee"] == "Ravi")
    assert d["total_count"] == ravi["invoice_count"]
    assert len(d["invoices"]) == ravi["invoice_count"]
    assert d["subtotal_amount"] == ravi["total_outstanding"]


# --------------------------------------------------------------------------- #
# (d) Customer + employee combo — ANDed, subtotal over the intersection.
# --------------------------------------------------------------------------- #
def test_invoices_customer_and_employee_combo(client, small_xlsx_bytes, fixed_today):
    # Derive a real (customer, employee) pair from an employee-only query so the
    # test needs no hardcoded knowledge of the fixture's row layout.
    emp = _post_invoices(client, small_xlsx_bytes, employee="Ravi")
    emp_rows = emp.json()["data"]["invoices"]
    assert emp_rows, "Ravi should own at least one row"
    target_customer = emp_rows[0]["customer"]
    matching = [r for r in emp_rows if r["customer"] == target_customer]
    expected_subtotal = round(sum(r["amount"] for r in matching), 2)

    combo = _post_invoices(
        client, small_xlsx_bytes, customer=target_customer, employee="Ravi"
    )
    assert combo.status_code == 200, combo.text
    d = combo.json()["data"]

    assert d["truncated"] is False
    assert {(r["customer"], r["employee"]) for r in d["invoices"]} == {
        (target_customer, "Ravi")
    }
    assert d["total_count"] == len(matching)
    assert d["subtotal_amount"] == expected_subtotal


# --------------------------------------------------------------------------- #
# (e) Error paths — bad mapping / non-xlsx return the same clean errors.
# --------------------------------------------------------------------------- #
def test_invoices_rejects_missing_required_field(client, small_xlsx_bytes):
    incomplete = {k: v for k, v in MAPPING.items() if k != "employee"}
    resp = client.post(
        "/api/invoices",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"mapping": json.dumps(incomplete)},
    )
    _assert_error_shape(resp, 400, "BAD_MAPPING")


def test_invoices_rejects_nonexistent_column(client, small_xlsx_bytes):
    bad = {**MAPPING, "due_date": "No Such Column"}
    resp = client.post(
        "/api/invoices",
        files={"file": ("ar_small.xlsx", small_xlsx_bytes, "application/octet-stream")},
        data={"mapping": json.dumps(bad)},
    )
    _assert_error_shape(resp, 400, "BAD_MAPPING")


def test_invoices_rejects_non_xlsx(client):
    resp = client.post(
        "/api/invoices",
        files={"file": ("data.csv", b"a,b,c\n1,2,3\n4,5,6\n", "text/csv")},
        data={"mapping": json.dumps(MAPPING)},
    )
    detail = _assert_error_shape(resp, 400, "BAD_FILE")
    assert ".xlsx" in detail["message"]


# --------------------------------------------------------------------------- #
# (f) Full-data / no-sampling gate. An UNFILTERED list over the >=60,000-row
#     ar_large.xlsx caps ``invoices`` at AGENT_DRILLDOWN_MAX_ROWS (1000) and sets
#     truncated=True, yet total_count == the fixture's real-data row_count and
#     subtotal_amount ties out EXACTLY to /api/compute's total_outstanding — the
#     capped page never moves the reported totals.
#     (spec/capabilities/invoice_drilldown.md Success Criteria + roadmap Phase 4.)
# --------------------------------------------------------------------------- #
def test_invoices_unfiltered_large_caps_but_totals_tie_out(client, large_fixture, fixed_today):
    from config.settings import get_settings

    cap = get_settings().drilldown_max_rows
    assert cap == 1000  # spec default (AGENT_DRILLDOWN_MAX_ROWS)

    mapping = large_fixture["mapping"].as_dict()
    file_bytes = large_fixture["bytes"]
    expected = large_fixture["expected"]

    def _post(path):
        return client.post(
            path,
            files={"file": ("ar_large.xlsx", file_bytes, "application/octet-stream")},
            data={"mapping": json.dumps(mapping)},
        )

    # Dashboard total via the real /api/compute path — the tie-out reference.
    compute = _post("/api/compute")
    assert compute.status_code == 200, compute.text
    dashboard_total = compute.json()["data"]["total_outstanding"]

    # Unfiltered drill-down over the same file, same as_of.
    resp = _post("/api/invoices")
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]

    # Capped page: exactly the setting's worth of rows, and truncated.
    assert len(d["invoices"]) == cap
    assert d["truncated"] is True
    # Totals cover the FULL set, never the capped page.
    assert d["total_count"] == expected["row_count"] >= 60000
    assert d["subtotal_amount"] == dashboard_total
    # Cross-check against the independent pure-Python oracle.
    assert d["subtotal_amount"] == expected["total_outstanding"]
