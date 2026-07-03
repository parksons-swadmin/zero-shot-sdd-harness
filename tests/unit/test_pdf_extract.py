"""Unit tests for tools.pdf_extract — real pdfplumber parsing over
programmatically-generated fixture PDFs (no mocking of the parse)."""
from __future__ import annotations

import io

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet

from tools.pdf_extract import NoExtractableTablesError, extract_pdf_tables

_GRID = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])


def _grid(rows: list[list[str]]) -> Table:
    t = Table(rows)
    t.setStyle(_GRID)
    return t


def _write_pdf(flowables: list, path) -> str:
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    doc.build(flowables)
    return str(path)


def _single_table_pdf(path) -> str:
    rows = [["name", "amount"]] + [[f"row{i}", str(i * 10)] for i in range(6)]
    return _write_pdf([_grid(rows)], path)


def _multi_page_table_pdf(path) -> tuple[str, int, int]:
    """A single logical table whose rows span two pages (same header)."""
    header = ["name", "amount"]
    page1 = [header] + [[f"row{i}", str(i)] for i in range(0, 7)]
    page2 = [header] + [[f"row{i}", str(i)] for i in range(7, 12)]
    total_data_rows = (len(page1) - 1) + (len(page2) - 1)  # 7 + 5 = 12
    total_amount = sum(range(0, 12))
    _write_pdf([_grid(page1), PageBreak(), _grid(page2)], path)
    return str(path), total_data_rows, total_amount


def _multi_different_tables_pdf(path) -> str:
    """A small 2-row table and a larger 6-row table with different headers."""
    small = [["a", "b"], ["1", "2"]]
    big = [["x", "y", "z"]] + [[str(i), str(i + 1), str(i + 2)] for i in range(6)]
    _write_pdf([_grid(small), Spacer(1, 20), _grid(big)], path)
    return str(path)


def _no_table_pdf(path) -> str:
    """A text-only PDF simulating a scanned/image export with no ruled table."""
    styles = getSampleStyleSheet()
    flow = [Paragraph("Quarterly Report", styles["Title"])]
    for _ in range(10):
        flow.append(Paragraph("This document contains only prose, no tables.", styles["Normal"]))
    _write_pdf(flow, path)
    return str(path)


def test_single_table_header_and_shape(tmp_path):
    path = _single_table_pdf(tmp_path / "single.pdf")
    df, issues = extract_pdf_tables(path)

    assert list(df.columns) == ["name", "amount"]
    assert df.shape == (6, 2)
    assert df.iloc[0]["name"] == "row0"
    # Best-effort caveat is always present.
    kinds = {i["issue_type"] for i in issues}
    assert "pdf_best_effort" in kinds
    best = next(i for i in issues if i["issue_type"] == "pdf_best_effort")
    assert best["needs_review"] is True
    assert best["affected_row_count"] == 6
    # Whole-dataset issue: column uses the codebase "*" convention (matches
    # the enforced CleaningIssueOut schema and the existing duplicate_rows issue).
    assert best["column"] == "*"
    # No skipped tables for a single-table PDF.
    assert "pdf_tables_skipped" not in kinds


def test_multi_page_table_is_concatenated(tmp_path):
    path, total_rows, total_amount = _multi_page_table_pdf(tmp_path / "multi.pdf")
    df, issues = extract_pdf_tables(path)

    # Rows from BOTH pages must be present (catches a page-1-only bug).
    assert df.shape[0] == total_rows == 12
    assert list(df.columns) == ["name", "amount"]
    assert df.iloc[0]["name"] == "row0"
    assert df.iloc[-1]["name"] == "row11"
    assert df["amount"].astype(int).sum() == total_amount
    # A consistent multi-page table is one table, so nothing is skipped.
    assert not any(i["issue_type"] == "pdf_tables_skipped" for i in issues)
    assert any(i["issue_type"] == "pdf_best_effort" for i in issues)


def test_multiple_different_tables_keeps_largest_and_records_skipped(tmp_path):
    path = _multi_different_tables_pdf(tmp_path / "diff.pdf")
    df, issues = extract_pdf_tables(path)

    # The larger 3-column, 6-row table wins.
    assert list(df.columns) == ["x", "y", "z"]
    assert df.shape == (6, 3)
    skipped = [i for i in issues if i["issue_type"] == "pdf_tables_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["needs_review"] is True
    assert "skipped 1" in skipped[0]["action_taken"]


def test_no_tables_raises(tmp_path):
    path = _no_table_pdf(tmp_path / "scanned.pdf")
    with pytest.raises(NoExtractableTablesError):
        extract_pdf_tables(path)
