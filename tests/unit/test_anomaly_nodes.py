"""Pure unit tests for the Phase-3b anomaly helpers in graph/nodes.py.

No real LLM call is made here: `_split_answer_sections`, `_profile_anomalies`,
`_coerce_anomaly` and `_merge_anomalies` are deterministic pure functions.
These prove the anomaly output reads ONLY the aggregate profile / structured
sections and never the raw rows, that the prose boundary is preserved so
`_extract_key_numbers` is unaffected, and that LLM + deterministic flags merge
and dedup by (type, column).
"""
from graph import nodes


# --------------------------------------------------------------------------- #
# _split_answer_sections — the 4-tuple
# --------------------------------------------------------------------------- #

_FULL = (
    "The total revenue is **$1,000**.\n"
    "---FOLLOW-UPS---\n"
    "- Break down by region?\n"
    "- Trend over time?\n"
    "---ARTIFACTS---\n"
    '{"table": true, "chart": {"type": "bar", "x": "region", "y": "revenue"}}\n'
    "---ANOMALIES---\n"
    '[{"type": "constant_column", "column": "data_source", "severity": "warning", '
    '"message": "data_source is constant."}]'
)


def test_split_sections_returns_four_tuple_all_sections():
    prose, follow_ups, intent, anomalies = nodes._split_answer_sections(_FULL)
    assert prose == "The total revenue is **$1,000**."
    assert follow_ups == ["Break down by region?", "Trend over time?"]
    assert intent == {"table": True, "chart": {"type": "bar", "x": "region", "y": "revenue"}}
    assert anomalies == [{
        "type": "constant_column", "column": "data_source",
        "severity": "warning", "message": "data_source is constant.",
    }]


def test_split_sections_prose_boundary_preserved_for_key_numbers():
    # _extract_key_numbers must run against prose only — the bolded value in the
    # prose is picked up, and nothing from the anomaly/follow-up tail leaks in.
    prose, _fu, _intent, _an = nodes._split_answer_sections(_FULL)
    key_numbers = nodes._extract_key_numbers(prose)
    assert key_numbers == [{"label": "value_1", "value": "$1,000"}]


def test_split_sections_missing_anomalies_marker_returns_empty_list():
    text = (
        "Answer **5**.\n---FOLLOW-UPS---\n- Next?\n"
        '---ARTIFACTS---\n{"table": false, "chart": false}'
    )
    prose, follow_ups, intent, anomalies = nodes._split_answer_sections(text)
    assert prose == "Answer **5**."
    assert follow_ups == ["Next?"]
    assert intent == {"table": False, "chart": False}
    assert anomalies == []


def test_split_sections_unparseable_anomalies_json_degrades_to_empty():
    text = _FULL.rsplit("---ANOMALIES---", 1)[0] + "---ANOMALIES---\nnot json at all"
    _prose, _fu, _intent, anomalies = nodes._split_answer_sections(text)
    assert anomalies == []


def test_split_sections_drops_malformed_anomaly_entries():
    text = (
        "Answer.\n---FOLLOW-UPS---\n- Q\n---ARTIFACTS---\n{}\n---ANOMALIES---\n"
        '[{"type": "null_values", "column": "region", "severity": "info", "message": "region has nulls."}, '
        '{"column": "x", "message": "no type"}, '
        '{"type": "outlier", "message": ""}, '
        '"not an object"]'
    )
    _prose, _fu, _intent, anomalies = nodes._split_answer_sections(text)
    assert anomalies == [{
        "type": "null_values", "column": "region",
        "severity": "info", "message": "region has nulls.",
    }]


def test_coerce_anomaly_normalises_bad_severity_to_info():
    coerced = nodes._coerce_anomaly(
        {"type": "constant_column", "column": "c", "severity": "SEVERE", "message": "m"}
    )
    assert coerced["severity"] == "info"


def test_coerce_anomaly_allows_null_column():
    coerced = nodes._coerce_anomaly(
        {"type": "shape", "column": None, "severity": "critical", "message": "m"}
    )
    assert coerced == {"type": "shape", "column": None, "severity": "critical", "message": "m"}


# --------------------------------------------------------------------------- #
# _profile_anomalies — deterministic, no LLM, no raw rows
# --------------------------------------------------------------------------- #

def _profiles_fixture():
    return [{
        "dataset_id": "d1",
        "var_name": "df",
        "columns": [
            {"name": "data_source", "distinct_count": 1, "null_count": 0},
            {"name": "region", "distinct_count": 5, "null_count": 37},
            {"name": "revenue", "distinct_count": 4000, "null_count": 0},
        ],
    }]


def test_profile_anomalies_flags_constant_column():
    flags = nodes._profile_anomalies(_profiles_fixture())
    constant = [f for f in flags if f["type"] == "constant_column"]
    assert len(constant) == 1
    assert constant[0]["column"] == "data_source"
    assert constant[0]["severity"] == "warning"


def test_profile_anomalies_flags_null_spike():
    flags = nodes._profile_anomalies(_profiles_fixture())
    nulls = [f for f in flags if f["type"] == "null_values"]
    assert len(nulls) == 1
    assert nulls[0]["column"] == "region"
    assert nulls[0]["severity"] == "info"


def test_profile_anomalies_clean_column_not_flagged():
    flags = nodes._profile_anomalies(_profiles_fixture())
    assert all(f["column"] != "revenue" for f in flags)


def test_profile_anomalies_empty_for_no_profiles():
    assert nodes._profile_anomalies(None) == []
    assert nodes._profile_anomalies([]) == []


# --------------------------------------------------------------------------- #
# _merge_anomalies — dedup by (type, column), deterministic wins
# --------------------------------------------------------------------------- #

def test_merge_dedups_by_type_and_column_deterministic_wins():
    llm = [
        {"type": "constant_column", "column": "data_source", "severity": "info",
         "message": "llm version"},
        {"type": "outlier", "column": "revenue", "severity": "warning", "message": "big outlier"},
    ]
    profile = [
        {"type": "constant_column", "column": "data_source", "severity": "warning",
         "message": "data_source has the same value in every row."},
    ]
    merged = nodes._merge_anomalies(llm, profile)
    by_key = {(f["type"], f["column"]): f for f in merged}
    # Deduped: only one constant_column/data_source, and it is the deterministic one.
    assert len(merged) == 2
    assert by_key[("constant_column", "data_source")]["severity"] == "warning"
    assert by_key[("constant_column", "data_source")]["message"].endswith("every row.")
    # The LLM-only flag survives.
    assert ("outlier", "revenue") in by_key
