"""Optional 7th mapping field ``hod`` (HoD Name = Head of Department).

Strictly additive + backward-compatible:
- header_detect proposes an optional ``hod`` only when a plausible column exists,
  and NEVER affects the "all six required mapped" gate;
- normalize captures a cleaned per-row ``hod`` column when mapped;
- each ``EmployeeSummary`` carries the most-common non-blank HoD for that
  employee (lexicographically-smallest on ties), ``None`` when unmapped/blank;
- when ``hod`` is unmapped, every existing metric/tie-out is byte-identical.

Three-scenario coverage: happy path (hod mapped), edge cases (tie-break, all
blank, no plausible column), and error/back-compat paths (unmapped identity,
bad hod column). No LLM, no DB — deterministic pandas pipeline.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import pytest
from openpyxl import Workbook

from domain.mapping import ColumnMapping
from graph.runner import PipelineError, build_preview, run_analysis
from tools.header_detect import CANONICAL_FIELDS, detect_mapping
from tools.ingest import normalize, read_workbook
from tools.metrics import compute_metrics

AS_OF = date(2026, 1, 15)

# Mapping WITH the optional hod field for DataFrame-direct tests.
MAPPING_HOD = ColumnMapping(
    customer="cust", invoice_no="inv", invoice_date="idt",
    due_date="ddt", amount="amt", employee="emp", hod="hodcol",
)
# Same identity, hod UNMAPPED (default None) — the back-compat baseline.
MAPPING_NO_HOD = ColumnMapping(
    customer="cust", invoice_no="inv", invoice_date="idt",
    due_date="ddt", amount="amt", employee="emp",
)


def _row(cust, emp, dpd, amt, hod=None):
    due = AS_OF - timedelta(days=dpd)
    return {
        "cust": cust, "inv": "x", "idt": date(2025, 1, 1),
        "ddt": due, "amt": amt, "emp": emp, "hodcol": hod,
    }


def _norm(rows: list[dict], mapping: ColumnMapping) -> pd.DataFrame:
    return normalize(pd.DataFrame(rows, dtype=object), mapping, AS_OF)


def _emp_hod(metrics) -> dict[str, str | None]:
    return {e.employee: e.hod for e in metrics.employees}


# --------------------------------------------------------------------------- #
# 1. header_detect — optional hod proposal, gate untouched
# --------------------------------------------------------------------------- #
def test_header_detect_proposes_hod_and_gate_unaffected():
    """A "HoD Name" column yields a 7th ``hod`` proposal; the six required fields
    still all match, so the all-six gate is satisfied and unaffected."""
    columns = [
        "Cust Name", "Invoice #", "Inv. Date", "Payable On",
        "Balance Outstanding", "Sales Person", "HoD Name",
    ]
    matches = detect_mapping(columns)
    by_field = {m.field: m for m in matches}

    # hod proposed against the real column, high confidence.
    assert "hod" in by_field
    assert by_field["hod"].matched_column == "HoD Name"
    assert by_field["hod"].status in ("high", "low")
    assert by_field["hod"].confidence >= 60

    # The six REQUIRED fields are all still matched -> the gate that blocks
    # compute until all six are mapped is unaffected by the optional hod.
    assert all(by_field[f].matched_column for f in CANONICAL_FIELDS)
    # hod is NOT one of the six required canonical fields.
    assert "hod" not in CANONICAL_FIELDS
    assert len(CANONICAL_FIELDS) == 6


@pytest.mark.parametrize("header", ["HoD Name", "HOD", "Head of Department", "Reporting Manager"])
def test_header_detect_matches_hod_synonyms(header):
    matches = {m.field: m for m in detect_mapping(["Customer", "Employee", header])}
    assert "hod" in matches
    assert matches["hod"].matched_column == header


def test_header_detect_omits_hod_when_no_plausible_column():
    """No HoD-like column -> no hod entry at all (guards the '* Name' false match:
    'Cust Name' must NOT be proposed as hod). The proposal count stays six."""
    columns = ["Cust Name", "Invoice #", "Inv. Date", "Payable On", "Balance Outstanding", "Sales Person"]
    matches = detect_mapping(columns)
    fields = [m.field for m in matches]
    assert "hod" not in fields
    assert len(matches) == 6


# --------------------------------------------------------------------------- #
# 2. normalize — optional hod column
# --------------------------------------------------------------------------- #
def test_normalize_captures_hod_when_mapped():
    out = _norm(
        [_row("A", "Ravi", 10, 100.0, hod="Alice"), _row("A", "Ravi", 10, 100.0, hod="  ")],
        MAPPING_HOD,
    )
    assert "hod" in out.columns
    assert out["hod"].tolist() == ["Alice", None]  # blank -> None sentinel


def test_normalize_hod_column_all_none_when_unmapped():
    out = _norm([_row("A", "Ravi", 10, 100.0, hod="Alice")], MAPPING_NO_HOD)
    # Column present (uniform downstream access) but carries no HoD data.
    assert "hod" in out.columns
    assert out["hod"].tolist() == [None]


# --------------------------------------------------------------------------- #
# 3. EmployeeSummary.hod — happy path + edge cases
# --------------------------------------------------------------------------- #
def test_employee_summary_hod_is_most_common(small_mapping):  # noqa: ARG001 - fixture parity
    """Each employee's hod = the most-common NON-blank HoD among their rows."""
    rows = [
        _row("A", "Ravi", 10, 500.0, hod="Alice"),
        _row("A", "Ravi", 10, 100.0, hod="Alice"),
        _row("B", "Ravi", 10, 100.0, hod="Bob"),        # Ravi: Alice x2, Bob x1 -> Alice
        _row("A", "Priya", 10, 300.0, hod="Carol"),
        _row("A", "Priya", 10, 100.0, hod=None),         # Priya: Carol x1 (+ blank) -> Carol
    ]
    m = compute_metrics(_norm(rows, MAPPING_HOD), AS_OF)
    hods = _emp_hod(m)
    assert hods == {"Ravi": "Alice", "Priya": "Carol"}
    # hod is on the wire shape for every employee row.
    assert all("hod" in e.model_dump() for e in m.employees)


def test_employee_hod_tiebreak_is_lexicographically_smallest():
    """A frequency tie resolves to the lexicographically-smallest HoD."""
    rows = [
        _row("A", "Ravi", 10, 100.0, hod="Zoe"),
        _row("A", "Ravi", 10, 100.0, hod="Amy"),  # 1-1 tie -> "Amy" wins
    ]
    m = compute_metrics(_norm(rows, MAPPING_HOD), AS_OF)
    assert _emp_hod(m) == {"Ravi": "Amy"}


def test_employee_hod_none_when_all_blank_for_employee():
    """An employee whose HoD cells are all blank/None gets hod=None even though
    another employee in the same file has a HoD."""
    rows = [
        _row("A", "Ravi", 10, 100.0, hod="Alice"),
        _row("A", "Priya", 10, 100.0, hod=None),
        _row("A", "Priya", 10, 100.0, hod="   "),
    ]
    m = compute_metrics(_norm(rows, MAPPING_HOD), AS_OF)
    hods = _emp_hod(m)
    assert hods["Ravi"] == "Alice"
    assert hods["Priya"] is None


# --------------------------------------------------------------------------- #
# 4. Back-compat — hod unmapped is byte-identical to the pre-change behaviour
# --------------------------------------------------------------------------- #
def test_hod_unmapped_all_none_and_metrics_byte_identical(small_xlsx_bytes, small_mapping, expected_small):
    """With hod UNMAPPED: every EmployeeSummary.hod is None AND the existing
    tie-outs are byte-identical to the independent oracle."""
    df, _ = read_workbook(small_xlsx_bytes, None)
    m = compute_metrics(normalize(df, small_mapping, AS_OF), AS_OF)

    # (a) hod is None for every employee.
    assert all(e.hod is None for e in m.employees)

    # (b) existing employee tie-out unchanged (employee, outstanding, overdue,
    #     worst_bucket, invoice_count) — byte-identical to the oracle.
    got = [
        (e.employee, round(e.total_outstanding * 100), round(e.total_overdue * 100),
         e.worst_bucket, e.invoice_count)
        for e in m.employees
    ]
    want = [
        (e["employee"], e["total_outstanding_paise"], e["total_overdue_paise"],
         e["worst_bucket"], e["invoice_count"])
        for e in expected_small["employees"]
    ]
    assert got == want

    # (c) headline totals unchanged.
    assert round(m.total_outstanding * 100) == expected_small["total_outstanding_paise"]
    assert round(m.total_overdue * 100) == expected_small["total_overdue_paise"]
    assert m.worst_bucket == expected_small["worst_bucket"]


def test_column_mapping_as_dict_excludes_hod():
    """``as_dict`` returns only the six required fields (validation/normalization
    treat only the six as required)."""
    assert set(MAPPING_HOD.as_dict().keys()) == {
        "customer", "invoice_no", "invoice_date", "due_date", "amount", "employee"
    }


# --------------------------------------------------------------------------- #
# 5. End-to-end through the graph runner + validation error path
# --------------------------------------------------------------------------- #
def _workbook_with_hod() -> bytes:
    """A 7-column workbook (incl. a HoD Name column) for run_analysis."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Aging"
    ws.append(["Cust", "Inv", "Inv Date", "Due Date", "Amount", "Employee", "HoD Name"])
    rows = [
        ["Acme", "1", date(2025, 1, 1), AS_OF - timedelta(days=40), 1000.0, "Ravi", "Alice"],
        ["Acme", "2", date(2025, 1, 1), AS_OF - timedelta(days=40), 2000.0, "Ravi", "Alice"],
        ["Beacon", "3", date(2025, 1, 1), AS_OF - timedelta(days=5), 500.0, "Priya", "Bob"],
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_run_analysis_threads_hod_end_to_end():
    """Full graph pipeline (ingest->...->assemble) surfaces the per-employee hod
    while headline totals stay correct."""
    mapping = ColumnMapping(
        customer="Cust", invoice_no="Inv", invoice_date="Inv Date",
        due_date="Due Date", amount="Amount", employee="Employee", hod="HoD Name",
    )
    m = run_analysis(
        file_bytes=_workbook_with_hod(), sheet_name=None, mapping=mapping, as_of=AS_OF
    )
    assert _emp_hod(m) == {"Ravi": "Alice", "Priya": "Bob"}
    assert round(m.total_outstanding * 100) == 350000  # 1000 + 2000 + 500


def test_run_analysis_without_hod_leaves_totals_and_hod_none():
    """Same workbook, hod OMITTED from the mapping: totals identical, hod None."""
    mapping = ColumnMapping(
        customer="Cust", invoice_no="Inv", invoice_date="Inv Date",
        due_date="Due Date", amount="Amount", employee="Employee",
    )
    m = run_analysis(
        file_bytes=_workbook_with_hod(), sheet_name=None, mapping=mapping, as_of=AS_OF
    )
    assert all(e.hod is None for e in m.employees)
    assert round(m.total_outstanding * 100) == 350000


def test_run_analysis_rejects_hod_mapped_to_nonexistent_column():
    """A hod mapped to a column that isn't in the sheet -> BAD_MAPPING (a mapped
    optional field must reference a real column). Absent/None hod is always fine."""
    mapping = ColumnMapping(
        customer="Cust", invoice_no="Inv", invoice_date="Inv Date",
        due_date="Due Date", amount="Amount", employee="Employee", hod="No Such Column",
    )
    with pytest.raises(PipelineError) as exc:
        run_analysis(file_bytes=_workbook_with_hod(), sheet_name=None, mapping=mapping, as_of=AS_OF)
    assert exc.value.code == "BAD_MAPPING"
    assert exc.value.status == 400
    assert "hod" in exc.value.message


def test_build_preview_proposes_hod_from_workbook():
    """The preview surface exposes the optional hod proposal for a real HoD column
    without disturbing the six-field proposals."""
    preview = build_preview(file_bytes=_workbook_with_hod())
    by_field = {m.field: m for m in preview.proposed_mapping}
    assert by_field["hod"].matched_column == "HoD Name"
    assert all(by_field[f].matched_column for f in CANONICAL_FIELDS)
