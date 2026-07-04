"""Exact, deterministic AR aging metrics.

All aggregation is integer paise (``int64``) over the FULL frame — no sampling,
no ``head(N)``, no float accumulation — so every total ties out bit-exactly to
the source column regardless of row count or order.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd

from domain.aging import AgingMetrics, BucketTotals, CustomerOverdue
from domain.quality import DataQualityReport, QualityFlag
from observability.events import get_logger

_log = get_logger("metrics")

# Overdue buckets ordered oldest-first (used for worst-bucket tie-breaking).
_OVERDUE_BUCKETS = ["90+", "61-90", "31-60", "0-30"]
_BUCKET_FIELD = {
    "current": "current",
    "0-30": "b_0_30",
    "31-60": "b_31_60",
    "61-90": "b_61_90",
    "90+": "b_90_plus",
}


def _rupees(paise: int) -> float:
    return round(int(paise) / 100, 2)


def _worst_bucket(bucket_paise: dict[str, int], has_overdue: bool) -> str:
    if not has_overdue:
        return "none"
    best = _OVERDUE_BUCKETS[0]
    for bucket in _OVERDUE_BUCKETS[1:]:
        if bucket_paise.get(bucket, 0) > bucket_paise.get(best, 0):
            best = bucket
    return best


def compute_metrics(
    df: pd.DataFrame, as_of: date, phase: int = 1, *, summary_row_excluded: int = 0
) -> AgingMetrics:
    start = time.perf_counter()

    amount = df["amount_paise"].astype("int64")
    overdue_mask = (df["dpd"] > 0).fillna(False).to_numpy()

    total_outstanding_paise = int(amount.sum())
    overdue_amount = amount.where(overdue_mask, 0)
    total_overdue_paise = int(overdue_amount.sum())

    pct_overdue = (total_overdue_paise / total_outstanding_paise) if total_outstanding_paise != 0 else 0.0

    bucket_paise = {
        bucket: int(total) for bucket, total in amount.groupby(df["bucket"], sort=False).sum().items()
    }
    bucket_totals = BucketTotals(
        current=_rupees(bucket_paise.get("current", 0)),
        b_0_30=_rupees(bucket_paise.get("0-30", 0)),
        b_31_60=_rupees(bucket_paise.get("31-60", 0)),
        b_61_90=_rupees(bucket_paise.get("61-90", 0)),
        b_90_plus=_rupees(bucket_paise.get("90+", 0)),
    )

    worst_bucket = _worst_bucket(bucket_paise, has_overdue=bool(overdue_mask.any()))
    customer_count = int(df["customer"].nunique())

    per_customer = (
        pd.DataFrame(
            {
                "customer": df["customer"],
                "overdue": overdue_amount.astype("int64"),
                "outstanding": amount,
            }
        )
        .groupby("customer", sort=False, as_index=False)
        .sum()
        .sort_values(by=["overdue", "outstanding", "customer"], ascending=[False, False, True])
    )
    top_customers = [
        CustomerOverdue(
            customer=str(r.customer),
            overdue_amount=_rupees(int(r.overdue)),
            outstanding_amount=_rupees(int(r.outstanding)),
        )
        for r in per_customer.head(20).itertuples(index=False)
    ]

    unparseable_row_count = int(df["due_date"].isna().sum())

    metrics = AgingMetrics(
        as_of=as_of,
        row_count=int(len(df)),
        total_outstanding=_rupees(total_outstanding_paise),
        total_overdue=_rupees(total_overdue_paise),
        pct_overdue=pct_overdue,
        customer_count=customer_count,
        worst_bucket=worst_bucket,
        bucket_totals=bucket_totals,
        top_customers_by_overdue=top_customers,
        data_quality=DataQualityReport(
            flagged_row_count=0, unparseable_row_count=unparseable_row_count, by_reason={}
        ),
    )

    _log.info(
        "metrics.computed",
        row_count=metrics.row_count,
        overdue_rows=int(overdue_mask.sum()),
        unparseable_rows=unparseable_row_count,
        summary_rows_excluded=summary_row_excluded,
        customer_count=customer_count,
        worst_bucket=worst_bucket,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    return metrics


def build_data_quality_report(
    df: pd.DataFrame, flags: list[QualityFlag], *, summary_row_excluded: int = 0
) -> DataQualityReport:
    """Aggregate quality flags into the report attached to AgingMetrics.

    ``flagged_row_count`` = distinct rows with >= 1 flag; ``unparseable_row_count``
    = rows whose ``due_date`` is NaT; ``by_reason`` = count per reason. Phase-1
    leaves ``rows`` empty (the full list is a Phase-2 surface).

    ``summary_row_excluded`` (embedded grand-total rows dropped before
    aggregation) is surfaced under the ``summary_row_excluded`` ``by_reason`` key
    for transparency — only when non-zero, so the wire shape stays stable when a
    sheet has no embedded totals.
    """
    by_reason: dict[str, int] = {}
    flagged_rows: set[int] = set()
    for flag in flags:
        by_reason[flag.reason] = by_reason.get(flag.reason, 0) + 1
        flagged_rows.add(flag.row_index)

    if summary_row_excluded:
        by_reason["summary_row_excluded"] = summary_row_excluded

    return DataQualityReport(
        flagged_row_count=len(flagged_rows),
        unparseable_row_count=int(df["due_date"].isna().sum()),
        by_reason=by_reason,
        rows=[],
    )
