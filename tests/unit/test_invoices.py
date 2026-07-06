"""Unit tests for ``run_invoices`` — the invoice-level drill-down surface.

Covers filtering (customer / employee / combo), the unfiltered cap + truncation,
summary-row exclusion, exact paise->rupee subtotal tie-out to ``run_analysis``,
credit-note preservation, missing-due-date rendering, and the same structural
error paths as ``/api/compute``. All against synthetic in-memory workbooks (no
LLM / DB / network) with a pinned ``as_of``.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from config.settings import get_settings
from domain.mapping import ColumnMapping
from graph.runner import PipelineError, run_analysis, run_invoices

AS_OF = date(2026, 1, 15)

HEADERS = ["Cust", "Inv", "InvDate", "DueDate", "Amt", "Emp"]

MAPPING = ColumnMapping(
    customer="Cust",
    invoice_no="Inv",
    invoice_date="InvDate",
    due_date="DueDate",
    amount="Amt",
    employee="Emp",
)

# as_of = 2026-01-15. Aging per row:
#   1 Acme/Ravi   due 2025-12-01 -> dpd 45  -> 31-60   1000.00 -> 100000 paise
#   2 Acme/Priya  due 2026-01-20 -> dpd -5  -> current  500.00 ->  50000 paise
#   3 Beacon/Ravi due 2025-10-15 -> dpd 92  -> 90+     2000.00 -> 200000 paise
#   4 Beacon/Priya no due date   -> dpd None-> unclass  300.00 ->  30000 paise
#   5 Zen/Ravi    due 2026-01-10 -> dpd 5   -> 0-30    -150.00 -> -15000 paise (credit note)
# Total paise = 365000 -> 3650.00 rupees.  Ravi paise = 285000 -> 2850.00.
ROWS = [
    ["Acme", "1", "2025-11-01", "2025-12-01", 1000.00, "Ravi"],
    ["Acme", "2", "2025-12-15", "2026-01-20", 500.00, "Priya"],
    ["Beacon", "3", "2025-09-01", "2025-10-15", 2000.00, "Ravi"],
    ["Beacon", "4", "2025-12-01", None, 300.00, "Priya"],
    ["Zen", "5", "2025-12-20", "2026-01-10", -150.00, "Ravi"],
]


def _wb(rows, sheet: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Happy path: unfiltered list ties out exactly to run_analysis (the dashboard).
# --------------------------------------------------------------------------- #
def test_run_invoices_ties_out_to_run_analysis():
    data = _wb(ROWS)
    metrics = run_analysis(file_bytes=data, sheet_name=None, mapping=MAPPING, as_of=AS_OF)
    result = run_invoices(file_bytes=data, sheet_name=None, mapping=MAPPING, as_of=AS_OF)

    assert result.total_count == metrics.row_count == 5
    assert len(result.invoices) == 5
    assert result.truncated is False
    assert result.subtotal_amount == metrics.total_outstanding == 3650.00


# --------------------------------------------------------------------------- #
# Edge: unfiltered list is capped at `limit`; counts/subtotal cover the FULL set.
# --------------------------------------------------------------------------- #
def test_run_invoices_truncates_unfiltered_list():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, as_of=AS_OF, limit=3
    )
    assert result.total_count == 5
    assert len(result.invoices) == 3
    assert result.truncated is True
    # Subtotal still reflects ALL five rows, not just the returned three.
    assert result.subtotal_amount == 3650.00


def test_run_invoices_not_truncated_when_set_fits_under_limit():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data,
        sheet_name=None,
        mapping=MAPPING,
        as_of=AS_OF,
        limit=get_settings().drilldown_max_rows,
    )
    assert result.truncated is False
    assert len(result.invoices) == result.total_count == 5


def test_run_invoices_default_limit_is_drilldown_max_rows_setting():
    """With no explicit ``limit`` the cap comes from ``AGENT_DRILLDOWN_MAX_ROWS``
    (``settings.drilldown_max_rows``, default 1000) — never a hardcoded value."""
    assert get_settings().drilldown_max_rows == 1000
    data = _wb(ROWS)
    result = run_invoices(file_bytes=data, sheet_name=None, mapping=MAPPING, as_of=AS_OF)
    # 5 rows < 1000 cap -> full set returned, not truncated.
    assert result.truncated is False
    assert len(result.invoices) == result.total_count == 5


# --------------------------------------------------------------------------- #
# A filtered set is returned in full (bounded) even below the cap — never trunc'd.
# --------------------------------------------------------------------------- #
def test_run_invoices_filter_returns_all_and_never_truncates():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, employee="Ravi", as_of=AS_OF, limit=1
    )
    assert {r.employee for r in result.invoices} == {"Ravi"}
    assert result.total_count == len(result.invoices) == 3
    assert result.truncated is False
    assert result.subtotal_amount == 2850.00


def test_run_invoices_customer_filter():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, customer="Acme", as_of=AS_OF
    )
    assert {r.customer for r in result.invoices} == {"Acme"}
    assert result.total_count == 2
    assert result.subtotal_amount == 1500.00  # 1000 + 500


def test_run_invoices_customer_and_employee_combo():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data,
        sheet_name=None,
        mapping=MAPPING,
        customer="Acme",
        employee="Ravi",
        as_of=AS_OF,
    )
    assert result.total_count == 1
    assert result.invoices[0].invoice_no == "1"
    assert result.subtotal_amount == 1000.00


def test_run_invoices_no_match_returns_empty_not_error():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, customer="Nobody", as_of=AS_OF
    )
    assert result.total_count == 0
    assert result.invoices == []
    assert result.subtotal_amount == 0.0
    assert result.truncated is False


# --------------------------------------------------------------------------- #
# Row fields: bucket / days_overdue / due_date, credit-note sign preservation.
# --------------------------------------------------------------------------- #
def test_run_invoices_row_fields_and_missing_due_date():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, customer="Beacon", as_of=AS_OF
    )
    by_inv = {r.invoice_no: r for r in result.invoices}

    # Missing due date -> days_overdue None, due_date None, bucket unclassified.
    r4 = by_inv["4"]
    assert r4.days_overdue is None
    assert r4.due_date is None
    assert r4.bucket == "unclassified"

    # Deeply overdue row keeps its ISO date, positive DPD, and 90+ bucket.
    r3 = by_inv["3"]
    assert r3.days_overdue == 92
    assert r3.bucket == "90+"
    assert r3.due_date == "2025-10-15"


def test_run_invoices_preserves_negative_credit_note():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, customer="Zen", as_of=AS_OF
    )
    assert result.total_count == 1
    assert result.invoices[0].amount == -150.00
    assert result.subtotal_amount == -150.00


# --------------------------------------------------------------------------- #
# Blank/whitespace filter values are ignored (treated as "no filter").
# --------------------------------------------------------------------------- #
def test_run_invoices_blank_filter_is_no_filter():
    data = _wb(ROWS)
    result = run_invoices(
        file_bytes=data, sheet_name=None, mapping=MAPPING, customer="   ", employee="", as_of=AS_OF
    )
    assert result.total_count == 5
    assert result.truncated is False


# --------------------------------------------------------------------------- #
# Embedded summary/grand-total rows are excluded (same as the metrics engine).
# --------------------------------------------------------------------------- #
def test_run_invoices_excludes_summary_rows():
    rows_with_total = ROWS + [["Grand Total", None, None, None, 3650.00, None]]
    data = _wb(rows_with_total)
    result = run_invoices(file_bytes=data, sheet_name=None, mapping=MAPPING, as_of=AS_OF)

    assert result.total_count == 5  # the grand-total row is excluded
    assert "Grand Total" not in {r.customer for r in result.invoices}
    # If the total row were summed, this would double to 7300.00.
    assert result.subtotal_amount == 3650.00


# --------------------------------------------------------------------------- #
# Error paths — identical structural failures to /api/compute.
# --------------------------------------------------------------------------- #
def test_run_invoices_bad_mapping_nonexistent_column():
    bad = ColumnMapping(
        customer="Cust",
        invoice_no="Inv",
        invoice_date="InvDate",
        due_date="No Such Column",
        amount="Amt",
        employee="Emp",
    )
    with pytest.raises(PipelineError) as exc:
        run_invoices(file_bytes=_wb(ROWS), sheet_name=None, mapping=bad, as_of=AS_OF)
    assert exc.value.code == "BAD_MAPPING"
    assert exc.value.status == 400


def test_run_invoices_non_xlsx_raises_bad_file():
    with pytest.raises(PipelineError) as exc:
        run_invoices(file_bytes=b"a,b,c\n1,2,3\n", sheet_name=None, mapping=MAPPING, as_of=AS_OF)
    assert exc.value.code == "BAD_FILE"
    assert exc.value.status == 400
