"""Full-data gate: >=60,000 rows tie out; no sampling/truncation; <15s."""

import time
from datetime import date

from graph.runner import run_analysis
from tools.ingest import normalize, read_workbook

AS_OF = date(2026, 1, 15)


def test_full_data_total_and_row_count_tie_out(large_fixture):
    expected = large_fixture["expected"]
    start = time.perf_counter()
    m = run_analysis(
        file_bytes=large_fixture["bytes"], sheet_name=None, mapping=large_fixture["mapping"], as_of=AS_OF
    )
    elapsed = time.perf_counter() - start

    assert m.row_count == expected["row_count"] >= 60000
    assert round(m.total_outstanding * 100) == expected["total_outstanding_paise"]
    assert round(m.total_overdue * 100) == expected["total_overdue_paise"]
    assert elapsed < 15.0, f"compute took {elapsed:.1f}s, budget is 15s"


def test_high_value_tail_dominates_top_customer(large_fixture):
    m = run_analysis(
        file_bytes=large_fixture["bytes"], sheet_name=None, mapping=large_fixture["mapping"], as_of=AS_OF
    )
    assert m.top_customers_by_overdue[0].customer == large_fixture["expected"]["top_customer"]


def test_prefix_would_differ_proving_no_truncation(large_fixture):
    """A prefix (all but the last 100 rows) has a materially different total,
    so any head(N)/sampling impl would produce the wrong answer."""
    df, _ = read_workbook(large_fixture["bytes"], None)
    out = normalize(df, large_fixture["mapping"], AS_OF)
    full = int(out["amount_paise"].sum())
    prefix = int(out["amount_paise"].iloc[:-100].sum())
    assert prefix != full
    assert full == large_fixture["expected"]["total_outstanding_paise"]
