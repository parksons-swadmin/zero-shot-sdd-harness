"""Best-effort, fully-local PDF table extraction (Phase 3d).

Uses `pdfplumber` (pure-Python, no Ghostscript/Java/OCR, no network) so PDF
parsing never sends data off-machine, honoring the raw-data-never-leaves-the-
machine boundary in spec/architecture.md.

Parsing rules (pinned in spec/capabilities/dataset-ingestion.md ->
"PDF best-effort extraction rule"):
  - The first extracted row of a table is its header.
  - Tables sharing a consistent structure (same column count AND same header
    row) across pages are concatenated into ONE DataFrame (multi-page report).
  - If multiple structurally-different tables exist, the largest group (by total
    cell count; first on a tie) is used; the others are recorded as skipped.
  - Every PDF ingest carries a best-effort caveat so the profile screen always
    shows a visible "verify this — may be inaccurate" note.
  - A PDF with zero extractable tables (scanned/image-only) raises
    NoExtractableTablesError so the endpoint can map it to 422 PDF_NO_TABLES
    rather than crashing or returning a silently-empty dataset.

Returns (DataFrame, extra_issues) where extra_issues match the
CleaningReport.issues_json shape used elsewhere in ingestion.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pdfplumber


class NoExtractableTablesError(Exception):
    """Raised when a PDF yields no extractable tables (likely scanned/image-based)."""


def _normalize_cell(value: object) -> str:
    """pdfplumber returns None for empty cells; normalize to a clean string."""
    if value is None:
        return ""
    return str(value).strip()


def _header_signature(header_row: list[object]) -> tuple[int, tuple[str, ...]]:
    header = tuple(_normalize_cell(c) for c in header_row)
    return (len(header), header)


def extract_pdf_tables(path: str | Path) -> tuple[pd.DataFrame, list[dict]]:
    """Extract a single DataFrame from a PDF plus best-effort cleaning issues.

    Raises NoExtractableTablesError if no tables are found.
    """
    raw_tables: list[list[list[object]]] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                # A usable table needs at least a header row and one data row,
                # and at least one column.
                if not table or len(table) < 2 or len(table[0]) == 0:
                    continue
                raw_tables.append(table)

    if not raw_tables:
        raise NoExtractableTablesError(
            "This PDF has no extractable tables — it may be scanned/image-based; "
            "export to CSV instead."
        )

    # Group tables by (column_count, header_tuple) so consistent multi-page
    # tables concatenate. Preserve first-seen order for deterministic tie-breaks.
    groups: dict[tuple[int, tuple[str, ...]], list[list[list[object]]]] = {}
    group_order: list[tuple[int, tuple[str, ...]]] = []
    for table in raw_tables:
        sig = _header_signature(table[0])
        if sig not in groups:
            groups[sig] = []
            group_order.append(sig)
        groups[sig].append(table)

    def _group_cell_count(sig: tuple[int, tuple[str, ...]]) -> int:
        cols = sig[0]
        return sum(len(t) * cols for t in groups[sig])

    # Largest group by total cell count; first-seen on a tie.
    chosen_sig = group_order[0]
    for sig in group_order[1:]:
        if _group_cell_count(sig) > _group_cell_count(chosen_sig):
            chosen_sig = sig

    chosen_tables = groups[chosen_sig]
    col_count, header = chosen_sig
    columns = list(header)

    data_rows: list[list[str]] = []
    for table in chosen_tables:
        for row in table[1:]:  # first row is the (repeated) header
            cells = [_normalize_cell(c) for c in row]
            # Pad / truncate to the header width so the frame is rectangular.
            if len(cells) < col_count:
                cells = cells + [""] * (col_count - len(cells))
            elif len(cells) > col_count:
                cells = cells[:col_count]
            data_rows.append(cells)

    df = pd.DataFrame(data_rows, columns=columns)

    issues: list[dict] = []

    skipped_count = len(raw_tables) - len(chosen_tables)
    if skipped_count > 0:
        issues.append(
            {
                "column": "*",
                "issue_type": "pdf_tables_skipped",
                "action_taken": f"used largest table; skipped {skipped_count} other table(s)",
                "affected_row_count": 0,
                "needs_review": True,
            }
        )

    issues.append(
        {
            "column": "*",
            "issue_type": "pdf_best_effort",
            "action_taken": (
                "extracted table(s) from PDF — this may be inaccurate (merged cells, "
                "multi-column layouts, repeated headers); please verify against the source"
            ),
            "affected_row_count": int(df.shape[0]),
            "needs_review": True,
        }
    )

    return df, issues
