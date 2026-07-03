"""Pure unit tests for the Phase-3a artifact helpers in graph/nodes.py.

No real LLM call is made here: `_split_answer_sections`, `_build_table_data`
and `_build_chart_spec` are deterministic pure functions, and `execute_code` is
driven with a stubbed sandbox (LLMClient.call_model_with_usage is never
reached). These prove the artifact assembly reads ONLY the already-capped
ExecutionResult and never the raw rows / export metadata.
"""
import json

from graph import nodes


# --------------------------------------------------------------------------- #
# _split_answer_sections
# --------------------------------------------------------------------------- #

def test_split_sections_full():
    text = (
        "The total is **$100**.\n"
        "---FOLLOW-UPS---\n"
        "- Break down by region?\n"
        "- Trend over time?\n"
        "---ARTIFACTS---\n"
        '{"table": true, "chart": {"type": "bar", "x": "region", "y": "revenue"}}'
    )
    prose, follow_ups, intent = nodes._split_answer_sections(text)
    assert prose == "The total is **$100**."
    assert follow_ups == ["Break down by region?", "Trend over time?"]
    assert intent == {"table": True, "chart": {"type": "bar", "x": "region", "y": "revenue"}}


def test_split_sections_no_artifacts_marker_backward_compatible():
    text = "Answer **5**.\n---FOLLOW-UPS---\n- Next?"
    prose, follow_ups, intent = nodes._split_answer_sections(text)
    assert prose == "Answer **5**."
    assert follow_ups == ["Next?"]
    assert intent is None


def test_split_sections_unparseable_artifacts_json_degrades():
    text = "Answer.\n---FOLLOW-UPS---\n- Q\n---ARTIFACTS---\nnot json at all"
    prose, follow_ups, intent = nodes._split_answer_sections(text)
    assert prose == "Answer."
    assert follow_ups == ["Q"]
    assert intent is None


def test_split_answer_and_follow_ups_helper_preserved():
    # The generalised helper must not change the behaviour of the original.
    text = "Prose **1**.\n---FOLLOW-UPS---\n- One\n- Two"
    prose, follow_ups = nodes._split_answer_and_follow_ups(text)
    assert prose == "Prose **1**."
    assert follow_ups == ["One", "Two"]


# --------------------------------------------------------------------------- #
# _build_table_data
# --------------------------------------------------------------------------- #

def _dataframe_result(records, total_rows=None, truncated=False):
    return {
        "result": {
            "type": "dataframe",
            "total_rows": total_rows if total_rows is not None else len(records),
            "rows_returned": len(records),
            "truncated": truncated,
            "data_json": json.dumps(records),
        }
    }


def test_build_table_from_dataframe():
    records = [{"region": "West", "revenue": 10}, {"region": "East", "revenue": 20}]
    table = nodes._build_table_data(_dataframe_result(records))
    assert table["columns"] == ["region", "revenue"]
    assert table["rows"] == [["West", 10], ["East", 20]]
    assert table["truncated"] is False


def test_build_table_from_series():
    result = {
        "result": {
            "type": "series", "total_rows": 2, "rows_returned": 2, "truncated": False,
            "data_json": json.dumps({"West": 10, "East": 20}),
        }
    }
    table = nodes._build_table_data(result)
    assert table["columns"] == ["key", "value"]
    assert table["rows"] == [["West", 10], ["East", 20]]


def test_build_table_none_for_scalar():
    assert nodes._build_table_data({"result": {"type": "scalar", "value": 42}}) is None
    assert nodes._build_table_data(None) is None


def test_build_table_uses_only_data_json_not_total_rows():
    # total_rows is huge but only the 2 capped records are in data_json.
    records = [{"a": 1}, {"a": 2}]
    table = nodes._build_table_data(_dataframe_result(records, total_rows=10_000, truncated=True))
    assert len(table["rows"]) == 2  # from data_json, NOT 10_000
    assert table["total_rows"] == 10_000
    assert table["truncated"] is True


# --------------------------------------------------------------------------- #
# _build_chart_spec
# --------------------------------------------------------------------------- #

def test_build_chart_spec_from_intent():
    records = [{"region": "West", "revenue": 10}, {"region": "East", "revenue": 20}]
    intent = {"type": "bar", "x": "region", "y": "revenue", "title": "By region"}
    spec = nodes._build_chart_spec(_dataframe_result(records), intent)
    assert spec["type"] == "bar"
    assert spec["x_key"] == "region"
    assert spec["y_key"] == "revenue"
    assert spec["series"] == [{"x": "West", "y": 10}, {"x": "East", "y": 20}]


def test_build_chart_spec_series_capped(monkeypatch):
    import config.settings as settings_module
    settings_module._settings = None
    monkeypatch.setenv("AGENT_CHART_MAX_POINTS", "5")
    settings_module._settings = None

    records = [{"x": i, "y": i * 2} for i in range(250)]
    spec = nodes._build_chart_spec(_dataframe_result(records), {"type": "line", "x": "x", "y": "y"})
    assert len(spec["series"]) == 5  # capped to AGENT_CHART_MAX_POINTS, not 250


def test_build_chart_spec_default_cap_100():
    records = [{"x": i, "y": i} for i in range(250)]
    spec = nodes._build_chart_spec(_dataframe_result(records), {"type": "bar", "x": "x", "y": "y"})
    assert len(spec["series"]) == 100  # default chart_max_points


def test_build_chart_spec_none_for_scalar_or_disabled():
    assert nodes._build_chart_spec({"result": {"type": "scalar", "value": 1}}, {"type": "bar"}) is None
    records = [{"a": 1, "b": 2}]
    assert nodes._build_chart_spec(_dataframe_result(records), {"chart": False}) is None
    assert nodes._build_chart_spec(_dataframe_result(records), None) is None


def test_build_chart_spec_built_only_from_data_json():
    # A single record in data_json => exactly one series point, regardless of
    # the (large) total_rows the sandbox reported.
    records = [{"region": "West", "revenue": 999}]
    spec = nodes._build_chart_spec(
        _dataframe_result(records, total_rows=50_000, truncated=True),
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert spec["series"] == [{"x": "West", "y": 999}]


# --------------------------------------------------------------------------- #
# execute_code strips `export` from accumulated_summaries
# --------------------------------------------------------------------------- #

def test_execute_code_strips_export_from_summaries(monkeypatch):
    import execution.sandbox as sandbox

    fake_result = {
        "ok": True,
        "result": {"type": "scalar", "value": 5},
        "stdout": "",
        "duration_ms": 1,
        "export": {"temp_path": "/tmp/x.parquet", "row_count": 42, "column_count": 3},
    }
    monkeypatch.setattr(sandbox, "run_analysis_code", lambda *a, **k: fake_result)

    # Empty dataset_ids => no DB dataframe load; sandbox is stubbed anyway.
    state = {"generated_code": "result = 5", "dataset_ids": [], "reasoning_mode": "simple"}
    out = nodes.execute_code(state)

    assert out["export_meta"] == {"temp_path": "/tmp/x.parquet", "row_count": 42, "column_count": 3}
    assert "export" not in out["execution_result"]
    for summary in out["accumulated_summaries"]:
        assert "export" not in summary
