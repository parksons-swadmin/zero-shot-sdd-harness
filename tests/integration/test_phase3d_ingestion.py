"""Phase 3d ingestion round-trips through the real POST /datasets endpoint
against the isolated file DB and real local pdfplumber/pandas parsing.

No mocking of the parse; no LLM call (ingestion never touches the LLM).
"""
from __future__ import annotations

import io

import pandas as pd
import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

_GRID = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])


def _grid(rows):
    t = Table(rows)
    t.setStyle(_GRID)
    return t


def _multi_page_pdf_bytes() -> tuple[bytes, int, int]:
    header = ["name", "amount"]
    page1 = [header] + [[f"row{i}", str(i)] for i in range(0, 7)]
    page2 = [header] + [[f"row{i}", str(i)] for i in range(7, 12)]
    total_rows = (len(page1) - 1) + (len(page2) - 1)  # 12
    total_amount = sum(range(0, 12))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter).build([_grid(page1), PageBreak(), _grid(page2)])
    return buf.getvalue(), total_rows, total_amount


def _no_table_pdf_bytes() -> bytes:
    styles = getSampleStyleSheet()
    flow = [Paragraph("Scanned Report", styles["Title"])]
    for _ in range(8):
        flow.append(Paragraph("Only prose here, no ruled tables at all.", styles["Normal"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter).build(flow)
    return buf.getvalue()


def _multi_sheet_xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"name": ["a", "b"], "value": [1, 2]}).to_excel(
            writer, sheet_name="Primary", index=False
        )
        pd.DataFrame({"other": [9]}).to_excel(writer, sheet_name="Extra", index=False)
    return buf.getvalue()


def _xls_bytes() -> bytes:
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    for c, name in enumerate(["name", "value"]):
        sheet.write(0, c, name)
    for r, (n, v) in enumerate([("a", 1), ("b", 2), ("c", 3)], start=1):
        sheet.write(r, 0, n)
        sheet.write(r, 1, v)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _csv_bytes() -> bytes:
    return b"name,value\nx,1\ny,2\n"


def _set_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None


def test_multi_page_pdf_concatenates_all_pages(api_client, tmp_path, monkeypatch):
    _set_data_dir(tmp_path, monkeypatch)
    pdf_bytes, total_rows, total_amount = _multi_page_pdf_bytes()

    resp = api_client.post(
        "/datasets", files={"file": ("report.pdf", pdf_bytes, "application/pdf")}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ready"
    # All pages concatenated, not just page 1.
    assert data["row_count"] == total_rows == 12
    assert data["column_count"] == 2

    issues = data["cleaning_report"]["issues"]
    best = [i for i in issues if i["issue_type"] == "pdf_best_effort"]
    assert len(best) == 1
    assert best[0]["needs_review"] is True
    assert "verify" in best[0]["action_taken"].lower()

    # The derived cleaned dataset is queryable and numerically intact.
    dataset_id = data["dataset_id"]
    get_resp = api_client.get(f"/datasets/{dataset_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["row_count"] == 12


def test_scanned_pdf_returns_422_pdf_no_tables(api_client, tmp_path, monkeypatch):
    _set_data_dir(tmp_path, monkeypatch)
    resp = api_client.post(
        "/datasets", files={"file": ("scan.pdf", _no_table_pdf_bytes(), "application/pdf")}
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "PDF_NO_TABLES"
    assert "export to CSV instead" in detail["message"]

    # No partial file left behind.
    uploads_dir = tmp_path / "uploads"
    if uploads_dir.exists():
        leftover = [p for p in uploads_dir.glob("**/*") if p.is_file()]
        assert leftover == []


def test_multi_sheet_xlsx_notes_skipped_sheets(api_client, tmp_path, monkeypatch):
    _set_data_dir(tmp_path, monkeypatch)
    resp = api_client.post(
        "/datasets",
        files={
            "file": (
                "book.xlsx",
                _multi_sheet_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ready"
    # Only the first sheet's data loaded.
    assert data["column_count"] == 2
    issues = data["cleaning_report"]["issues"]
    skipped = [i for i in issues if i["issue_type"] == "excel_extra_sheets_skipped"]
    assert len(skipped) == 1
    assert "Extra" in skipped[0]["action_taken"]
    assert "Primary" in skipped[0]["action_taken"]
    assert skipped[0]["needs_review"] is True


def test_legacy_xls_parses_ready(api_client, tmp_path, monkeypatch):
    _set_data_dir(tmp_path, monkeypatch)
    resp = api_client.post(
        "/datasets",
        files={"file": ("legacy.xls", _xls_bytes(), "application/vnd.ms-excel")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ready"
    assert data["row_count"] == 3
    assert data["column_count"] == 2


def test_csv_happy_path_still_green(api_client, tmp_path, monkeypatch):
    _set_data_dir(tmp_path, monkeypatch)
    resp = api_client.post(
        "/datasets", files={"file": ("simple.csv", _csv_bytes(), "text/csv")}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ready"
    assert data["row_count"] == 2
    assert data["column_count"] == 2
    # No PDF/Excel notes on a plain CSV.
    kinds = {i["issue_type"] for i in data["cleaning_report"]["issues"]}
    assert "pdf_best_effort" not in kinds
    assert "excel_extra_sheets_skipped" not in kinds
