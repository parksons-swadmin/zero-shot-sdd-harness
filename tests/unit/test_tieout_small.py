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


def test_phase2_fields_absent_in_phase1(small_xlsx_bytes, small_mapping):
    m = run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    assert m.employees is None
    assert m.customer_breakdown is None
    assert m.employee_breakdown is None
    assert m.risk_flags == []  # flag node ran (stub) -> empty list, not None
