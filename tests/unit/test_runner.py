"""Runner public surface: build_preview + run_analysis error paths."""

import io
from datetime import date

import pytest
from openpyxl import Workbook

from domain.mapping import ColumnMapping
from graph.runner import PipelineError, build_preview, run_analysis

AS_OF = date(2026, 1, 15)


def _tiny_workbook(headers: list[str], rows: list[list], sheet: str = "Aging") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- build_preview happy path ---------------------------------------------- #
def test_build_preview_returns_full_shape(small_xlsx_bytes):
    preview = build_preview(file_bytes=small_xlsx_bytes)
    assert preview.sheets == ["Aging"]
    assert preview.sheet_name == "Aging"
    assert len(preview.columns) == 6
    assert len(preview.proposed_mapping) == 6
    assert len(preview.preview_rows) == 10  # first 10 rows
    due = next(m for m in preview.proposed_mapping if m.field == "due_date")
    assert due.status == "low"
    # seeded parse-time flags surfaced
    reasons = {f.reason for f in preview.parse_flags}
    assert reasons == {"missing_due_date", "negative_amount", "zero_amount", "blank_employee"}


def test_build_preview_unicode_round_trip(small_xlsx_bytes):
    preview = build_preview(file_bytes=small_xlsx_bytes)
    customers = {str(row.get("Cust Name")) for row in preview.preview_rows}
    assert "Müller Traders" in customers
    assert "श्री एंटरप्राइजेज" in customers


# --- error paths ------------------------------------------------------------ #
def test_preview_rejects_non_xlsx():
    with pytest.raises(PipelineError) as exc:
        build_preview(file_bytes=b"col1,col2\n1,2\n")  # a CSV, not xlsx
    assert exc.value.code == "BAD_FILE"
    assert exc.value.status == 400
    assert ".xlsx" in exc.value.message


def test_preview_sheet_not_found(small_xlsx_bytes):
    with pytest.raises(PipelineError) as exc:
        build_preview(file_bytes=small_xlsx_bytes, sheet_name="Nope")
    assert exc.value.code == "SHEET_NOT_FOUND"
    assert exc.value.status == 400


def test_preview_too_many_rows(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_ROWS", "2")
    import config.settings as m

    m._settings = None
    data = _tiny_workbook(
        ["Cust Name", "Invoice #", "Inv. Date", "Payable On", "Balance Outstanding", "Sales Person"],
        [["A", "1", "2025-01-01", "2025-02-01", 10, "R"]] * 3,
    )
    with pytest.raises(PipelineError) as exc:
        build_preview(file_bytes=data)
    assert exc.value.code == "TOO_MANY_ROWS"
    assert exc.value.status == 422


def test_run_analysis_bad_mapping_nonexistent_column(small_xlsx_bytes):
    mapping = ColumnMapping(
        customer="Cust Name", invoice_no="Invoice #", invoice_date="Inv. Date",
        due_date="Payable On", amount="Balance Outstanding", employee="DOES NOT EXIST",
    )
    with pytest.raises(PipelineError) as exc:
        run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=mapping, as_of=AS_OF)
    assert exc.value.code == "BAD_MAPPING"
    assert exc.value.status == 400
    assert "employee" in exc.value.message


def test_run_analysis_bad_mapping_duplicate_column(small_xlsx_bytes):
    mapping = ColumnMapping(
        customer="Cust Name", invoice_no="Invoice #", invoice_date="Inv. Date",
        due_date="Payable On", amount="Balance Outstanding", employee="Balance Outstanding",
    )
    with pytest.raises(PipelineError) as exc:
        run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=mapping, as_of=AS_OF)
    assert exc.value.code == "BAD_MAPPING"
    assert exc.value.status == 400


def test_run_analysis_bad_mapping_empty_field(small_xlsx_bytes):
    mapping = ColumnMapping(
        customer="", invoice_no="Invoice #", invoice_date="Inv. Date",
        due_date="Payable On", amount="Balance Outstanding", employee="Sales Person",
    )
    with pytest.raises(PipelineError) as exc:
        run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=mapping, as_of=AS_OF)
    assert exc.value.code == "BAD_MAPPING"
    assert "customer" in exc.value.message


def test_run_analysis_defaults_as_of_to_today(small_xlsx_bytes, small_mapping):
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping)
    assert m.as_of == date.today()


def test_compute_failure_surfaces_as_clean_pipeline_error(monkeypatch, small_xlsx_bytes, small_mapping):
    """A node failure routes to handle_error and is rendered as COMPUTE_ERROR,
    never a raw traceback leaking to the caller."""
    import graph.nodes as nodes

    def _boom(*a, **k):
        raise RuntimeError("boom internal detail")

    monkeypatch.setattr(nodes, "compute_metrics", _boom)
    with pytest.raises(PipelineError) as exc:
        run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    assert exc.value.code == "COMPUTE_ERROR"
    assert exc.value.status in (422, 500)
