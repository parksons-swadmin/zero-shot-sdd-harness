"""Multi-sheet Excel export of the computed AR aging dashboard.

Deterministic, in-memory ``openpyxl`` workbook built from the SAME
``AgingMetrics`` the dashboard renders — so the export can never diverge from the
screen. No LLM, no network, no DB.

The export carries the FULL data set, NOT the on-screen truncated view: the
dashboard caps the Top-N customer chart at 20 and the flagged-rows panel at the
first 50 rows, but this workbook writes EVERY customer, EVERY employee, and
EVERY flagged/unparseable row.

Money cells are written as the underlying rupee NUMBER (``paise / 100`` exact),
formatted with an Indian lakh/crore digit-grouping currency mask so a reader sees
``₹`` grouping while the cell value stays a plain number that ties out exactly to
the API metrics when read back.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from domain.aging import AgingMetrics, BucketTotals

# Indian-grouping rupee number format (lakh/crore digit grouping). The cell
# VALUE remains the exact rupee number; only the display is grouped.
_INR_FMT = '"₹"#,##,##,##0.00'
_PCT_FMT = "0.00%"
_EMDASH = "—"

_TITLE_FONT = Font(bold=True, size=14)
_HEADER_FONT = Font(bold=True)
_SECTION_FONT = Font(bold=True)


def _overdue_of(bt: BucketTotals) -> float:
    """Overdue rupees for a group = the four overdue buckets (dpd > 0).

    ``current`` (dpd <= 0) and unclassified (no due date) are not overdue, so the
    overdue amount is exactly the sum of the 0-30 / 31-60 / 61-90 / 90+ buckets —
    which matches the API's ``top_customers_by_overdue`` overdue figure.
    """
    return round(bt.b_0_30 + bt.b_31_60 + bt.b_61_90 + bt.b_90_plus, 2)


def _wavg_cell(value: float | None) -> float | str:
    return _EMDASH if value is None else value


def _set_col_format(ws: Worksheet, col_idx: int, fmt: str, first_data_row: int) -> None:
    """Apply a number format to a whole data column (1-based ``col_idx``)."""
    for row in range(first_data_row, ws.max_row + 1):
        cell = ws.cell(row=row, column=col_idx)
        if isinstance(cell.value, (int, float)):
            cell.number_format = fmt


def _autosize(ws: Worksheet, widths: dict[int, int]) -> None:
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def _build_summary(ws: Worksheet, metrics: AgingMetrics, source_filename: str) -> None:
    ws.title = "Summary"

    ws["A1"] = "AR Aging Dashboard — Summary"
    ws["A1"].font = _TITLE_FONT

    ws["A2"] = "Source File"
    ws["B2"] = source_filename
    ws["A3"] = "As Of"
    ws["B3"] = metrics.as_of.isoformat()
    for lbl in ("A2", "A3"):
        ws[lbl].font = _HEADER_FONT

    ws["A5"] = "Key Performance Indicators"
    ws["A5"].font = _SECTION_FONT

    # (label, value, number_format | None). "Total Outstanding"/"Total Overdue"
    # are read back verbatim by the gate and MUST equal the API metrics exactly.
    kpis: list[tuple[str, object, str | None]] = [
        ("Total Outstanding", metrics.total_outstanding, _INR_FMT),
        ("Total Overdue", metrics.total_overdue, _INR_FMT),
        ("% Overdue", metrics.pct_overdue, _PCT_FMT),
        ("Customer Count", metrics.customer_count, None),
        ("Row Count", metrics.row_count, None),
        ("Worst Bucket", metrics.worst_bucket, None),
    ]
    row = 6
    for label, value, fmt in kpis:
        ws.cell(row=row, column=1, value=label).font = _HEADER_FONT
        cell = ws.cell(row=row, column=2, value=value)
        if fmt:
            cell.number_format = fmt
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Aging Buckets (Outstanding by Age)").font = _SECTION_FONT
    row += 1
    bt = metrics.bucket_totals
    buckets: list[tuple[str, float]] = [
        ("Current", bt.current),
        ("0-30", bt.b_0_30),
        ("31-60", bt.b_31_60),
        ("61-90", bt.b_61_90),
        ("90+", bt.b_90_plus),
    ]
    for label, value in buckets:
        ws.cell(row=row, column=1, value=label).font = _HEADER_FONT
        ws.cell(row=row, column=2, value=value).number_format = _INR_FMT
        row += 1

    _autosize(ws, {1: 26, 2: 22})


def _build_customers(ws: Worksheet, metrics: AgingMetrics) -> None:
    """Every customer (uncapped), ranked by overdue amount descending."""
    headers = [
        "Customer", "Outstanding", "Overdue", "Current", "0-30", "31-60",
        "61-90", "90+", "Weighted Avg DPD", "% Overdue",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT

    ranked = sorted(
        metrics.customer_breakdown,
        key=lambda b: (-_overdue_of(b.bucket_totals), -b.total_outstanding, b.key),
    )
    for b in ranked:
        bt = b.bucket_totals
        ws.append([
            b.key,
            b.total_outstanding,
            _overdue_of(bt),
            bt.current,
            bt.b_0_30,
            bt.b_31_60,
            bt.b_61_90,
            bt.b_90_plus,
            _wavg_cell(b.weighted_avg_days_overdue),
            b.pct_overdue,
        ])

    for col in (2, 3, 4, 5, 6, 7, 8):  # money columns
        _set_col_format(ws, col, _INR_FMT, first_data_row=2)
    _set_col_format(ws, 10, _PCT_FMT, first_data_row=2)  # % overdue
    _autosize(ws, {1: 28, **{c: 15 for c in range(2, 11)}})


def _build_employees(ws: Worksheet, metrics: AgingMetrics) -> None:
    """Every employee (ranked by outstanding desc), incl. HoD Name + per-employee
    aging breakdown columns merged in from ``employee_breakdown`` (keyed by key)."""
    headers = [
        "Employee", "HoD Name", "Total Outstanding", "Total Overdue", "% Overdue",
        "Worst Bucket", "Invoice Count", "Current", "0-30", "31-60", "61-90",
        "90+", "Weighted Avg DPD",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT

    breakdown_by_key = {b.key: b for b in metrics.employee_breakdown}
    for e in metrics.employees:
        bd = breakdown_by_key.get(e.employee)
        bt = bd.bucket_totals if bd else None
        ws.append([
            e.employee,
            e.hod or "",
            e.total_outstanding,
            e.total_overdue,
            e.pct_overdue,
            e.worst_bucket,
            e.invoice_count,
            bt.current if bt else 0.0,
            bt.b_0_30 if bt else 0.0,
            bt.b_31_60 if bt else 0.0,
            bt.b_61_90 if bt else 0.0,
            bt.b_90_plus if bt else 0.0,
            _wavg_cell(bd.weighted_avg_days_overdue) if bd else _EMDASH,
        ])

    for col in (3, 4, 8, 9, 10, 11, 12):  # money columns
        _set_col_format(ws, col, _INR_FMT, first_data_row=2)
    _set_col_format(ws, 5, _PCT_FMT, first_data_row=2)  # % overdue
    _autosize(ws, {1: 20, 2: 20, 3: 18, 4: 18, **{c: 14 for c in range(5, 14)}})


def _build_flagged_rows(ws: Worksheet, metrics: AgingMetrics) -> None:
    """Every flagged/unparseable row (uncapped) + the summary-rows-excluded note."""
    dq = metrics.data_quality
    excluded = dq.by_reason.get("summary_row_excluded", 0)

    ws["A1"] = "Flagged Rows — Data Quality Audit"
    ws["A1"].font = _TITLE_FONT
    # Transparency note: embedded summary/total rows removed before aggregation.
    ws["A2"] = f"{excluded} summary/total rows excluded"
    ws["A2"].font = _HEADER_FONT

    header_row = 4
    headers = ["Row Index", "Field", "Reason", "Raw Value"]
    for col, label in enumerate(headers, start=1):
        ws.cell(row=header_row, column=col, value=label).font = _HEADER_FONT

    row = header_row + 1
    for flag in dq.rows:
        ws.cell(row=row, column=1, value=flag.row_index)
        ws.cell(row=row, column=2, value=flag.field)
        ws.cell(row=row, column=3, value=flag.reason)
        ws.cell(row=row, column=4, value=flag.raw_value if flag.raw_value is not None else "")
        row += 1

    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left")
    _autosize(ws, {1: 12, 2: 16, 3: 22, 4: 24})


def build_workbook(metrics: AgingMetrics, *, source_filename: str) -> bytes:
    """Build the multi-sheet AR aging workbook and return its ``.xlsx`` bytes.

    Sheets (by required name): ``Summary``, ``Customers``, ``Employees``,
    ``Flagged Rows``. Built entirely in memory; on any failure the caller returns
    a clean error rather than a partial file.
    """
    wb = Workbook()
    _build_summary(wb.active, metrics, source_filename)
    _build_customers(wb.create_sheet("Customers"), metrics)
    _build_employees(wb.create_sheet("Employees"), metrics)
    _build_flagged_rows(wb.create_sheet("Flagged Rows"), metrics)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
