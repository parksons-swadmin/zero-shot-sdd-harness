"""Public backend entry points for the API layer. No DB, no network, stateless.

``build_preview`` and ``run_analysis`` are the pinned surface the ``api`` slice
imports. Structural failures raise ``PipelineError`` (which the route renders via
``api_error``); data-quality problems are never errors — they are flagged and
the run completes.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime

import pandas as pd

from config.settings import get_settings
from domain.aging import AgingMetrics
from domain.mapping import ColumnMapping, PreviewResult
from graph.agent import agentic_ai
from graph.state import AnalysisState
from observability.events import get_logger
from tools.header_detect import CANONICAL_FIELDS, detect_mapping
from tools.ingest import normalize, read_workbook
from tools.validate import validate

_log = get_logger("runner")


class PipelineError(Exception):
    """A structural failure that the API renders as a clean error response."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            f = float(value)
            return None if math.isnan(f) else f
    except ImportError:  # pragma: no cover
        pass
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _read_or_raise(file_bytes: bytes, sheet_name: str | None) -> tuple[pd.DataFrame, list[str]]:
    try:
        return read_workbook(file_bytes, sheet_name)
    except KeyError:
        raise PipelineError(
            "SHEET_NOT_FOUND", f"Sheet '{sheet_name}' was not found in the workbook.", 400
        ) from None
    except ValueError:
        raise PipelineError(
            "BAD_FILE",
            "Could not read the file as an .xlsx workbook. Please upload a valid .xlsx file.",
            400,
        ) from None


def build_preview(*, file_bytes: bytes, sheet_name: str | None = None) -> PreviewResult:
    settings = get_settings()
    df, sheets = _read_or_raise(file_bytes, sheet_name)

    if len(df) > settings.max_rows:
        raise PipelineError(
            "TOO_MANY_ROWS",
            f"The sheet has {len(df)} rows, exceeding the limit of {settings.max_rows}.",
            422,
        )

    chosen = sheet_name if sheet_name else sheets[0]
    columns = [str(c) for c in df.columns]
    proposed = detect_mapping(columns)

    preview_rows = [
        {str(col): _json_safe(val) for col, val in row.items()}
        for _, row in df.head(10).iterrows()
    ]

    parse_flags = []
    matched = {m.field: m.matched_column for m in proposed}
    if all(matched.get(f) for f in CANONICAL_FIELDS):
        mapping = ColumnMapping(**{f: matched[f] for f in CANONICAL_FIELDS})
        normalized = normalize(df, mapping, date.today())
        parse_flags = validate(normalized)

    _log.info("preview.built", sheet=chosen, columns=len(columns), rows=len(df), flags=len(parse_flags))
    return PreviewResult(
        sheets=sheets,
        sheet_name=chosen,
        columns=columns,
        proposed_mapping=proposed,
        preview_rows=preview_rows,
        parse_flags=parse_flags,
    )


def _validate_mapping(mapping: ColumnMapping, columns: list[str]) -> None:
    available = set(columns)
    values = mapping.as_dict()

    for field in CANONICAL_FIELDS:
        col = values[field]
        if not col or not str(col).strip():
            raise PipelineError("BAD_MAPPING", f"No source column selected for '{field}'.", 400)
        if col not in available:
            raise PipelineError(
                "BAD_MAPPING", f"Field '{field}' is mapped to '{col}', which is not a column in the sheet.", 400
            )

    seen: dict[str, str] = {}
    for field in CANONICAL_FIELDS:
        col = values[field]
        if col in seen:
            raise PipelineError(
                "BAD_MAPPING",
                f"Column '{col}' is mapped to both '{seen[col]}' and '{field}'; each column may map to only one field.",
                400,
            )
        seen[col] = field


def run_analysis(
    *,
    file_bytes: bytes,
    sheet_name: str | None,
    mapping: ColumnMapping,
    as_of: date | None = None,
) -> AgingMetrics:
    as_of = as_of or date.today()
    raw_df, _ = _read_or_raise(file_bytes, sheet_name)
    _validate_mapping(mapping, [str(c) for c in raw_df.columns])

    run_id = str(uuid.uuid4())
    state: AnalysisState = {
        "run_id": run_id,
        "file_bytes": file_bytes,
        "sheet_name": sheet_name,
        "mapping": mapping,
        "as_of": as_of,
        "phase": 1,
        "raw_df": raw_df,
        "error": None,
    }
    _log.info("run.start", run_id=run_id, rows=int(len(raw_df)))
    final = agentic_ai.invoke(state)

    if final.get("error"):
        raise PipelineError("COMPUTE_ERROR", f"Could not compute metrics: {final['error']}", 422)

    metrics = final["metrics"]
    _log.info("run.complete", run_id=run_id, row_count=metrics.row_count)
    return metrics
