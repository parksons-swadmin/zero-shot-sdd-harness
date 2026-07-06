"""Graph compiles and state flows ingest -> validate -> compute -> flag -> assemble."""

from datetime import date

from domain.aging import AgingMetrics
from graph.agent import agentic_ai
from graph.runner import _read_or_raise
from graph.state import AnalysisState


def test_graph_compiles():
    assert agentic_ai is not None


def test_graph_nodes_present():
    node_names = set(agentic_ai.get_graph().nodes.keys())
    for expected in ("ingest", "validate", "compute", "flag", "assemble", "handle_error"):
        assert expected in node_names


def test_state_flows_through_all_nodes(small_xlsx_bytes, small_mapping, as_of: date):
    raw_df, _ = _read_or_raise(small_xlsx_bytes, None)
    state: AnalysisState = {
        "run_id": "test-run",
        "file_bytes": small_xlsx_bytes,
        "sheet_name": None,
        "mapping": small_mapping,
        "as_of": as_of,
        "phase": 1,
        "raw_df": raw_df,
        "error": None,
    }
    final = agentic_ai.invoke(state)

    assert not final.get("error")
    assert final["df"] is not None
    assert isinstance(final["quality_flags"], list)
    # Phase 2: the flag node now emits real riskiest-account flags.
    assert final["risk_flags"] and final["risk_flags"][0].customer == "Beacon & Co"
    assert isinstance(final["metrics"], AgingMetrics)
    # assemble attached the data-quality report (with the full audit list)
    assert final["metrics"].data_quality.flagged_row_count == 4
    assert {r.row_index for r in final["metrics"].data_quality.rows} == {14, 15, 16, 17}
    # Phase-2 breakdowns populated on the metrics object.
    assert [e.employee for e in final["metrics"].employees] == ["Ravi", "Priya", "(blank)"]


def test_error_routes_to_handle_error(as_of: date):
    """A fatal ingest failure sets error and terminates cleanly (no metrics)."""
    state: AnalysisState = {
        "run_id": "bad-run",
        "file_bytes": b"not an xlsx at all",
        "sheet_name": None,
        "mapping": None,
        "as_of": as_of,
        "phase": 1,
        "error": None,
    }
    final = agentic_ai.invoke(state)
    assert final.get("error")
    assert "metrics" not in final
