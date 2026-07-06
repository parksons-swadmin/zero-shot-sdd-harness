"""Metrics engine: tie-out, zero-outstanding, worst-bucket tie-breaking."""

from datetime import date, timedelta

import pandas as pd

from domain.mapping import ColumnMapping
from tools.ingest import normalize
from tools.metrics import compute_metrics

AS_OF = date(2026, 1, 15)
MAPPING = ColumnMapping(
    customer="cust", invoice_no="inv", invoice_date="idt",
    due_date="ddt", amount="amt", employee="emp",
)


def _norm(rows: list[dict]) -> pd.DataFrame:
    return normalize(pd.DataFrame(rows, dtype=object), MAPPING, AS_OF)


def _row(cust, dpd, amt):
    due = AS_OF - timedelta(days=dpd)
    return {"cust": cust, "inv": "x", "idt": date(2025, 1, 1), "ddt": due, "amt": amt, "emp": "R"}


def test_pct_overdue_zero_when_outstanding_zero():
    """A frame whose balances net to zero must not divide by zero."""
    df = _norm([_row("A", -5, 100.0), _row("B", -5, -100.0)])  # both current, sum 0
    m = compute_metrics(df, AS_OF)
    assert m.total_outstanding == 0.0
    assert m.pct_overdue == 0.0


def test_worst_bucket_none_when_no_overdue():
    df = _norm([_row("A", -1, 100.0), _row("B", -10, 200.0)])  # all current
    m = compute_metrics(df, AS_OF)
    assert m.worst_bucket == "none"


def test_worst_bucket_tie_resolves_to_older():
    # 61-90 and 31-60 tie at 100 each; older (61-90) wins.
    df = _norm([_row("A", 70, 100.0), _row("B", 45, 100.0)])
    m = compute_metrics(df, AS_OF)
    assert m.bucket_totals.b_61_90 == 100.0
    assert m.bucket_totals.b_31_60 == 100.0
    assert m.worst_bucket == "61-90"


def test_outstanding_includes_negative_and_zero_and_unclassified():
    df = _norm([
        _row("A", 10, 500.0),
        _row("A", 10, -200.0),
        _row("A", 10, 0.0),
        {"cust": "A", "inv": "m", "idt": date(2025, 1, 1), "ddt": None, "amt": 300.0, "emp": "R"},
    ])
    m = compute_metrics(df, AS_OF)
    # 500 - 200 + 0 + 300 = 600 outstanding; overdue = 500 - 200 = 300 (unclassified excluded)
    assert round(m.total_outstanding * 100) == 60000
    assert round(m.total_overdue * 100) == 30000


def test_small_fixture_headline_tieout(small_xlsx_bytes, small_mapping, expected_small):
    """Direct compute_metrics tie-out (integer paise) on the committed fixture."""
    from tools.ingest import read_workbook

    df, _ = read_workbook(small_xlsx_bytes, None)
    m = compute_metrics(normalize(df, small_mapping, AS_OF), AS_OF)

    assert round(m.total_outstanding * 100) == expected_small["total_outstanding_paise"]
    assert round(m.total_overdue * 100) == expected_small["total_overdue_paise"]
    assert m.worst_bucket == expected_small["worst_bucket"]
    assert m.customer_count == expected_small["customer_count"]
    assert m.top_customers_by_overdue[0].customer == expected_small["top_customers_by_overdue"][0]["customer"]
