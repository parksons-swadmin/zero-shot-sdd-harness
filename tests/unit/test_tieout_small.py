"""Exact end-to-end tie-out: every AgingMetrics field on ar_small == the oracle.

Integer-paise equality against the hand-authored, independently-computed
expected_small.json.
"""

from datetime import date

from graph.runner import run_analysis

AS_OF = date(2026, 1, 15)


def _paise(rupees: float) -> int:
    return round(rupees * 100)


def test_every_field_ties_out(small_xlsx_bytes, small_mapping, expected_small):
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)

    assert m.as_of == date.fromisoformat(expected_small["as_of"])
    assert m.row_count == expected_small["row_count"]
    assert _paise(m.total_outstanding) == expected_small["total_outstanding_paise"]
    assert _paise(m.total_overdue) == expected_small["total_overdue_paise"]
    assert abs(m.pct_overdue - expected_small["pct_overdue"]) < 1e-12
    assert m.customer_count == expected_small["customer_count"]
    assert m.worst_bucket == expected_small["worst_bucket"]

    bt = m.bucket_totals
    ebt = expected_small["bucket_totals"]
    assert _paise(bt.current) == _paise(ebt["current"])
    assert _paise(bt.b_0_30) == _paise(ebt["b_0_30"])
    assert _paise(bt.b_31_60) == _paise(ebt["b_31_60"])
    assert _paise(bt.b_61_90) == _paise(ebt["b_61_90"])
    assert _paise(bt.b_90_plus) == _paise(ebt["b_90_plus"])


def test_top_customers_tie_out(small_xlsx_bytes, small_mapping, expected_small):
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)

    got = [(c.customer, _paise(c.overdue_amount), _paise(c.outstanding_amount)) for c in m.top_customers_by_overdue]
    want = [
        (c["customer"], _paise(c["overdue_amount"]), _paise(c["outstanding_amount"]))
        for c in expected_small["top_customers_by_overdue"]
    ]
    assert got == want
    assert got[0][0] == "Beacon & Co"  # deepest 90+ is top of Top-20


def test_data_quality_ties_out(small_xlsx_bytes, small_mapping, expected_small):
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    dq = m.data_quality
    edq = expected_small["data_quality"]
    assert dq.flagged_row_count == edq["flagged_row_count"]
    assert dq.unparseable_row_count == edq["unparseable_row_count"]
    assert dq.by_reason == edq["by_reason"]


def test_phase2_fields_are_populated(small_xlsx_bytes, small_mapping):
    """Phase 2 wires these blocks into real features — they are always populated
    now (superseded detail lives in tests/unit/test_phase2.py)."""
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    assert [e.employee for e in m.employees] == ["Ravi", "Priya", "(blank)"]
    assert len(m.customer_breakdown) == 5
    assert len(m.employee_breakdown) == 3
    assert m.risk_flags and m.risk_flags[0].customer == "Beacon & Co"
    assert {r.row_index for r in m.data_quality.rows} == {14, 15, 16, 17}
