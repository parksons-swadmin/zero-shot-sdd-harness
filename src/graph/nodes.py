"""Deterministic pipeline nodes. No LLM, no network, no DB.

Each node is a pure function of its inputs. On a fatal failure a node returns
``{**state, "error": str(exc)}`` and routing sends the run to ``node_handle_error``.
"""

from __future__ import annotations

from graph.state import AnalysisState
from observability.events import get_logger
from tools.flags import compute_risk_flags
from tools.ingest import normalize, read_workbook
from tools.metrics import build_data_quality_report, compute_metrics
from tools.validate import validate

_log = get_logger("graph")


def node_ingest(state: AnalysisState) -> AnalysisState:
    try:
        raw_df = state.get("raw_df")
        if raw_df is None:
            raw_df, _ = read_workbook(state["file_bytes"], state.get("sheet_name"))
        df = normalize(raw_df, state["mapping"], state["as_of"])
        # Exclude embedded summary/grand-total rows before any aggregation so
        # they never inflate totals, buckets, customer_count, or the Top-N.
        # The count is threaded downstream for transparency (log + report).
        summary_excluded = int(df["is_summary"].sum())
        df = df[~df["is_summary"]].drop(columns=["is_summary"]).reset_index(drop=True)
        _log.info(
            "node.ingest",
            run_id=state.get("run_id"),
            row_count=int(len(df)),
            summary_rows_excluded=summary_excluded,
        )
        return {**state, "df": df, "summary_row_excluded": summary_excluded}
    except Exception as exc:  # noqa: BLE001 - fatal ingest failures route to handle_error
        return {**state, "error": str(exc)}


def node_validate(state: AnalysisState) -> AnalysisState:
    try:
        flags = validate(state["df"])
        _log.info("node.validate", run_id=state.get("run_id"), flag_count=len(flags))
        return {**state, "quality_flags": flags}
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": str(exc)}


def node_compute(state: AnalysisState) -> AnalysisState:
    try:
        metrics = compute_metrics(
            state["df"],
            state["as_of"],
            state.get("phase", 1),
            summary_row_excluded=state.get("summary_row_excluded", 0),
        )
        return {**state, "metrics": metrics}
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": str(exc)}


def node_flag(state: AnalysisState) -> AnalysisState:
    try:
        risk_flags = compute_risk_flags(state["df"])
        return {**state, "risk_flags": risk_flags}
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": str(exc)}


def node_assemble(state: AnalysisState) -> AnalysisState:
    metrics = state["metrics"]
    metrics.data_quality = build_data_quality_report(
        state["df"],
        state.get("quality_flags", []),
        summary_row_excluded=state.get("summary_row_excluded", 0),
    )
    metrics.risk_flags = state.get("risk_flags", [])
    _log.info(
        "node.assemble",
        run_id=state.get("run_id"),
        flagged_row_count=metrics.data_quality.flagged_row_count,
    )
    return {**state, "metrics": metrics}


def node_handle_error(state: AnalysisState) -> AnalysisState:
    _log.error("node.error", run_id=state.get("run_id"), error=state.get("error"))
    return state
