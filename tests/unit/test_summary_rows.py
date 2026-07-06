"""Embedded summary / grand-total row exclusion.

Real SAP AR exports embed grand-total rows in the sheet body (customer/dims
blank, ``Current Employee`` == "Totals", a huge Amount Due). Summing them
multiplies the true Total Outstanding. These tests pin the detection at the
normalize layer (happy + guardrail) and the exclusion end-to-end through the
pipeline (a synthetic workbook only -- never the real, confidential file), while
proving genuine invoice rows (blank-employee rows, negative credit notes) survive
and net in.
"""

from datetime import date

import pandas as pd

import build_fixtures as bf  # fixtures dir is on sys.path via tests/conftest.py
from domain.mapping import ColumnMapping
from graph.runner import run_analysis
from tools.ingest import normalize

AS_OF = date(2026, 1, 15)

MAPPING = ColumnMapping(
    customer="cust", invoice_no="inv", invoice_date="idt",
    due_date="ddt", amount="amt", employee="emp",
)


def _norm(rows: list[dict]) -> pd.DataFrame:
    return normalize(pd.DataFrame(rows, dtype=object), MAPPING, AS_OF)


# --------------------------------------------------------------------------- #
# Detection at the normalize layer (fast, no workbook round-trip)
# --------------------------------------------------------------------------- #
def test_embedded_summary_rows_are_flagged():
    """Both detection rules fire, on either the customer or the employee column."""
    rows = [
        # (a) employee == "Totals", every dimension blank -- the real-file pattern.
        {"cust": None, "inv": None, "idt": None, "ddt": None, "amt": 6970739133.06, "emp": "Totals"},
        # (a) "Grand Total" variant on the employee column.
        {"cust": None, "inv": None, "idt": None, "ddt": None, "amt": 888.0, "emp": "Grand Total"},
        # (a) total marker on the customer column (with a due date).
        {"cust": "Totals", "inv": "T-1", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": 123.0, "emp": "Ravi"},
        # (b) bare total: numeric amount but no customer / due date / invoice number.
        {"cust": None, "inv": None, "idt": None, "ddt": None, "amt": 777.0, "emp": None},
    ]
    out = _norm(rows)
    assert out["is_summary"].tolist() == [True, True, True, True]
    # Detection never drops rows -- exclusion is the pipeline's job.
    assert len(out) == 4


def test_genuine_invoice_rows_are_never_flagged_as_summary():
    """Guardrails: real rows (incl. blank-employee, negative credit notes) survive."""
    rows = [
        # blank employee but a real customer + due date -> KEPT.
        {"cust": "Acme Corp", "inv": "K-003", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": 250000.0, "emp": None},
        # negative credit note with a full identity -> KEPT, nets in.
        {"cust": "Beacon & Co", "inv": "K-004", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": -100000.0, "emp": "Ravi"},
        # a HUBERGROUP-style row: real customer, an old (2022) due date, a negative amount.
        {"cust": "HUBERGROUP", "inv": "H-1", "idt": date(2022, 1, 1), "ddt": date(2022, 2, 1), "amt": -201.0, "emp": "Rep"},
        # a legitimate customer whose name merely CONTAINS "total" is not a marker.
        {"cust": "Total Solutions Pvt Ltd", "inv": "TS-1", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": 500.0, "emp": "Ravi"},
        # a bare blank row whose amount is NON-numeric -> not rule (b) (no valid amount).
        {"cust": None, "inv": None, "idt": None, "ddt": None, "amt": "abc", "emp": None},
    ]
    out = _norm(rows)
    assert out["is_summary"].tolist() == [False, False, False, False, False]


# --------------------------------------------------------------------------- #
# End-to-end exclusion through the pipeline (synthetic workbook only)
# --------------------------------------------------------------------------- #
def test_pipeline_excludes_embedded_summary_rows(tmp_path):
    path = tmp_path / "ar_summary.xlsx"
    expected = bf.build_summary(path, as_of=AS_OF)
    mapping = ColumnMapping(**expected["mapping"])

    m = run_analysis(file_bytes=path.read_bytes(), sheet_name=None, mapping=mapping, as_of=AS_OF)

    # Totals tie out to the KEEP-only oracle: the billions in the summary rows
    # were never summed.
    assert round(m.total_outstanding * 100) == expected["total_outstanding_paise"]
    assert round(m.total_overdue * 100) == expected["total_overdue_paise"]

    # Only genuine invoice rows are counted.
    assert m.row_count == expected["row_count"] == len(bf.SUMMARY_KEEP_ROWS)
    assert m.customer_count == expected["customer_count"] == 2

    # Top-N never contains a "Totals"/"(blank)" pseudo-customer.
    names = [c.customer for c in m.top_customers_by_overdue]
    assert "Totals" not in names and "(blank)" not in names
    assert names == [t["customer"] for t in expected["top_customers_by_overdue"]]

    # Guardrail negative credit note netted in: Beacon = 500,000 - 100,000.
    beacon = next(c for c in m.top_customers_by_overdue if c.customer == "Beacon & Co")
    assert round(beacon.outstanding_amount * 100) == 40000000

    # Transparency (no schema change): excluded count surfaced under by_reason.
    assert m.data_quality.by_reason["summary_row_excluded"] == len(bf.SUMMARY_EXCLUDE_ROWS)
    # Real-row quality flags still recorded alongside the excluded count.
    assert m.data_quality.by_reason.get("negative_amount") == 1
    assert m.data_quality.by_reason.get("blank_employee") == 1


def test_by_reason_omits_summary_key_when_no_summary_rows(small_xlsx_bytes, small_mapping):
    """A clean sheet (no embedded totals) must not gain the new by_reason key,
    keeping the wire shape stable."""
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    assert "summary_row_excluded" not in m.data_quality.by_reason
