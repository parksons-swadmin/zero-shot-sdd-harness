"""Public backend entry points for the API layer. No DB, no network, stateless.

``build_preview`` and ``run_analysis`` are the pinned surface the ``api`` slice
imports. Structural failures raise ``PipelineError`` (which the route renders via
``api_error``); data-quality problems are never errors — they are flagged and
the run completes.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd

from config.settings import get_settings
from domain.aging import AgingMetrics
from domain.mapping import ColumnMapping, PreviewResult
from graph.agent import agentic_ai
from graph.state import AnalysisState
from observability.events import get_logger
from tools.flags import compute_risk_flags
from tools.header_detect import CANONICAL_FIELDS, detect_mapping
from tools.ingest import normalize, read_workbook
from tools.metrics import build_data_quality_report, compute_metrics
from tools.validate import validate

# Coarse progress increment: emit a "rows_done" frame roughly every this many
# rows so the client bar advances without event flooding (large_file_progress).
_PROGRESS_CHUNK = 5000

ProgressFn = Callable[[str, int, int], None]

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

    # Optional 7th field: absent/None is always fine and never required. When
    # provided it must reference a real column (else BAD_MAPPING); it is not
    # subject to the duplicate-column rule (the six canonical fields are).
    if mapping.hod is not None and str(mapping.hod).strip():
        if mapping.hod not in available:
            raise PipelineError(
                "BAD_MAPPING",
                f"Field 'hod' is mapped to '{mapping.hod}', which is not a column in the sheet.",
                400,
            )


def run_analysis(
    *,
    file_bytes: bytes,
    sheet_name: str | None,
    mapping: ColumnMapping,
    as_of: date | None = None,
) -> AgingMetrics:
    as_of = as_of or get_settings().as_of or date.today()
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


def _normalize_streaming(
    raw_df: pd.DataFrame,
    mapping: ColumnMapping,
    as_of: date,
    progress: ProgressFn,
    chunk_size: int = _PROGRESS_CHUNK,
) -> pd.DataFrame:
    """Normalize the full frame in row-chunks, emitting REAL ``parse`` progress.

    Each chunk is a genuine ``normalize`` call over real rows (honest progress —
    never a timer). ``normalize`` is purely row-local, so chunking + concatenating
    yields a frame byte-identical to normalizing the whole frame at once — EXCEPT
    that ``normalize`` numbers ``row_index`` as ``range(len(chunk))`` per call, so
    each chunk's ``row_index`` MUST be re-offset to its global start (the
    data-quality audit + risk flags are keyed by ``row_index``; a wrong offset
    would diverge from the non-streaming path). The equivalence test is the
    mandatory safety net for this invariant.
    """
    rows_total = len(raw_df)
    if rows_total == 0:
        return normalize(raw_df, mapping, as_of)

    parts: list[pd.DataFrame] = []
    for start in range(0, rows_total, chunk_size):
        end = min(start + chunk_size, rows_total)
        chunk = normalize(raw_df.iloc[start:end], mapping, as_of)
        # Re-offset row_index from per-chunk 0..n to the global start..end.
        chunk["row_index"] = list(range(start, end))
        parts.append(chunk)
        progress("parse", end, rows_total)

    df = pd.concat(parts, ignore_index=True)
    return df


def run_analysis_streaming(
    *,
    file_bytes: bytes,
    sheet_name: str | None,
    mapping: ColumnMapping,
    as_of: date | None = None,
    progress: ProgressFn,
    chunk_size: int = _PROGRESS_CHUNK,
) -> AgingMetrics:
    """Run the deterministic pipeline while emitting real row-count progress.

    Produces the IDENTICAL ``AgingMetrics`` as :func:`run_analysis` for the same
    inputs — it runs the same downstream steps the graph nodes run (exclude
    summary rows -> validate -> compute_metrics -> compute_risk_flags ->
    build_data_quality_report/assemble), differing only in that ``normalize`` is
    driven in chunks so ``progress(phase, rows_done, rows_total)`` reflects real
    rows processed. Structural failures raise ``PipelineError`` (rendered by the
    route as an SSE ``error`` frame).
    """
    as_of = as_of or get_settings().as_of or date.today()
    raw_df, _ = _read_or_raise(file_bytes, sheet_name)
    _validate_mapping(mapping, [str(c) for c in raw_df.columns])

    rows_total = int(len(raw_df))
    run_id = str(uuid.uuid4())
    _log.info("stream.start", run_id=run_id, rows=rows_total)

    df = _normalize_streaming(raw_df, mapping, as_of, progress, chunk_size)

    # Identical downstream to node_ingest -> ... -> node_assemble.
    summary_excluded = int(df["is_summary"].sum())
    df = df[~df["is_summary"]].drop(columns=["is_summary"]).reset_index(drop=True)

    flags = validate(df)
    metrics = compute_metrics(df, as_of, 1, summary_row_excluded=summary_excluded)
    metrics.risk_flags = compute_risk_flags(df)
    metrics.data_quality = build_data_quality_report(
        df, flags, summary_row_excluded=summary_excluded
    )

    progress("compute", metrics.row_count, metrics.row_count)
    _log.info("stream.complete", run_id=run_id, row_count=metrics.row_count)
    return metrics
