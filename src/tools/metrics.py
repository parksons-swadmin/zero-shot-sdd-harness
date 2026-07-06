"""Exact, deterministic AR aging metrics.

All aggregation is integer paise (``int64``) over the FULL frame — no sampling,
no ``head(N)``, no float accumulation — so every total ties out bit-exactly to
the source column regardless of row count or order.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd

from domain.aging import (
    AgingMetrics,
    BucketTotals,
    CustomerBreakdown,
    CustomerOverdue,
    EmployeeBreakdown,
    EmployeeSummary,
)
from domain.quality import DataQualityReport, QualityFlag
from observability.events import get_logger

_log = get_logger("metrics")

# Overdue buckets ordered oldest-first (used for worst-bucket tie-breaking).
_OVERDUE_BUCKETS = ["90+", "61-90", "31-60", "0-30"]
# The five reportable buckets (``unclassified`` is intentionally NOT one of
# them — rows with no due date carry into ``total_outstanding`` but into no
# bucket, so the five bucket amounts need not sum to a group's outstanding).
_FIVE_BUCKETS = ["current", "0-30", "31-60", "61-90", "90+"]
_BUCKET_FIELD = {
    "current": "current",
    "0-30": "b_0_30",
    "31-60": "b_31_60",
    "61-90": "b_61_90",
    "90+": "b_90_plus",
}


def _rupees(paise: int) -> float:
    return round(int(paise) / 100, 2)


def _bucket_totals(bucket_paise: dict[str, int]) -> BucketTotals:
    """Build a ``BucketTotals`` (rupees) from a paise-keyed bucket dict."""
    return BucketTotals(
        current=_rupees(bucket_paise.get("current", 0)),
        b_0_30=_rupees(bucket_paise.get("0-30", 0)),
        b_31_60=_rupees(bucket_paise.get("31-60", 0)),
        b_61_90=_rupees(bucket_paise.get("61-90", 0)),
        b_90_plus=_rupees(bucket_paise.get("90+", 0)),
    )


def _worst_bucket(bucket_paise: dict[str, int], has_overdue: bool) -> str:
    if not has_overdue:
        return "none"
    best = _OVERDUE_BUCKETS[0]
    for bucket in _OVERDUE_BUCKETS[1:]:
        if bucket_paise.get(bucket, 0) > bucket_paise.get(best, 0):
            best = bucket
    return best


def _partition_records(df: pd.DataFrame, key_col: str) -> list[dict]:
    """Per-group integer-paise aggregates keyed by ``key_col``.

    Returns one dict per distinct group label (blank labels arrive as the
    literal ``"(blank)"`` from normalization and are never dropped). All money
    stays integer paise; the weighted-avg numerator is ``sum(paise_i * dpd_i)``
    over the group's OVERDUE rows only. ``outstanding`` includes unclassified
    (no-due-date) rows, so it can exceed the sum of the five bucket amounts.
    """
    amount = df["amount_paise"].astype("int64")
    dpd = df["dpd"]
    overdue_mask = (dpd > 0).fillna(False)

    overdue_amount = amount.where(overdue_mask, 0).astype("int64")
    # Weighted numerator: paise * dpd, over overdue rows only. Overdue rows
    # always have a non-null positive dpd, so the fillna(0) only touches the
    # rows the mask then zeroes out.
    wnum = (amount * dpd.fillna(0)).where(overdue_mask, 0).astype("int64")

    work = pd.DataFrame(
        {
            "key": df[key_col].astype(str).to_numpy(),
            "amount": amount.to_numpy(),
            "bucket": df["bucket"].astype(str).to_numpy(),
            "overdue": overdue_amount.to_numpy(),
            "wnum": wnum.to_numpy(),
            "is_overdue": overdue_mask.to_numpy(),
        }
    )

    agg = work.groupby("key", sort=False).agg(
        outstanding=("amount", "sum"),
        overdue=("overdue", "sum"),
        wnum=("wnum", "sum"),
        invoice_count=("amount", "size"),
        overdue_rows=("is_overdue", "sum"),
    )
    bucket_paise = (
        work.groupby(["key", "bucket"])["amount"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=_FIVE_BUCKETS, fill_value=0)
    )

    records: list[dict] = []
    for key in agg.index:
        row = agg.loc[key]
        records.append(
            {
                "key": str(key),
                "outstanding": int(row["outstanding"]),
                "overdue": int(row["overdue"]),
                "wnum": int(row["wnum"]),
                "invoice_count": int(row["invoice_count"]),
                "has_overdue": int(row["overdue_rows"]) > 0,
                "buckets": {b: int(bucket_paise.loc[key, b]) for b in _FIVE_BUCKETS},
            }
        )
    return records


def _pct_overdue(overdue_paise: int, outstanding_paise: int) -> float:
    return (overdue_paise / outstanding_paise) if outstanding_paise != 0 else 0.0


def _weighted_avg_days(wnum_paise: int, overdue_paise: int) -> float | None:
    # No overdue balance -> undefined (never 0-as-if-computed, never /0).
    if overdue_paise == 0:
        return None
    return round(wnum_paise / overdue_paise, 2)


def _employee_hods(df: pd.DataFrame) -> dict[str, str]:
    """Most-common non-blank HoD per employee (deterministic).

    Ties on frequency are broken by the lexicographically smallest HoD for
    reproducibility. Employees with no non-blank HoD are absent from the result
    (callers treat a missing key as ``None``), which covers both the unmapped
    (all-None ``hod`` column) and the all-blank-for-this-employee cases.
    """
    if "hod" not in df.columns:
        return {}

    counts: dict[str, dict[str, int]] = {}
    for emp, hod in zip(df["employee"].astype(str), df["hod"]):
        # Skip None and NaN (a plain-list column build could coerce None->NaN;
        # str(NaN) == "nan" must never be counted as a HoD name).
        if hod is None or (isinstance(hod, float) and pd.isna(hod)):
            continue
        text = str(hod).strip()
        if not text:
            continue
        counts.setdefault(emp, {})
        counts[emp][text] = counts[emp].get(text, 0) + 1

    return {
        emp: min(by_hod.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        for emp, by_hod in counts.items()
    }


def _employee_summaries(df: pd.DataFrame) -> list[EmployeeSummary]:
    """Ranked employee rollups: outstanding desc, overdue desc, employee asc."""
    records = _partition_records(df, "employee")
    records.sort(key=lambda r: (-r["outstanding"], -r["overdue"], r["key"]))
    hod_by_employee = _employee_hods(df)
    return [
        EmployeeSummary(
            employee=r["key"],
            total_outstanding=_rupees(r["outstanding"]),
            total_overdue=_rupees(r["overdue"]),
            pct_overdue=_pct_overdue(r["overdue"], r["outstanding"]),
            worst_bucket=_worst_bucket(r["buckets"], r["has_overdue"]),
            invoice_count=r["invoice_count"],
            hod=hod_by_employee.get(r["key"]),
        )
        for r in records
    ]


def _breakdowns(
    df: pd.DataFrame, key_col: str, model_cls: type
) -> list:
    """Per-group aging breakdown + weighted-avg-DPD, ranked outstanding desc, key asc."""
    records = _partition_records(df, key_col)
    records.sort(key=lambda r: (-r["outstanding"], r["key"]))
    return [
        model_cls(
            key=r["key"],
            bucket_totals=_bucket_totals(r["buckets"]),
            weighted_avg_days_overdue=_weighted_avg_days(r["wnum"], r["overdue"]),
            pct_overdue=_pct_overdue(r["overdue"], r["outstanding"]),
            total_outstanding=_rupees(r["outstanding"]),
        )
        for r in records
    ]


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
    bucket_totals = _bucket_totals(bucket_paise)

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

    # Phase-2 breakdowns — computed UNCONDITIONALLY (the ``phase`` arg is kept
    # only for call-site backward compatibility and no longer gates output).
    employees = _employee_summaries(df)
    customer_breakdown = _breakdowns(df, "customer", CustomerBreakdown)
    employee_breakdown = _breakdowns(df, "employee", EmployeeBreakdown)

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
        employees=employees,
        customer_breakdown=customer_breakdown,
        employee_breakdown=employee_breakdown,
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
        employee_count=len(employees),
        worst_bucket=worst_bucket,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    return metrics


def build_data_quality_report(
    df: pd.DataFrame, flags: list[QualityFlag], *, summary_row_excluded: int = 0
) -> DataQualityReport:
    """Aggregate quality flags into the report attached to AgingMetrics.

    ``flagged_row_count`` = distinct rows with >= 1 flag; ``unparseable_row_count``
    = rows whose ``due_date`` is NaT; ``by_reason`` = count per reason. Phase 2
    populates ``rows`` with the full ``QualityFlag`` list (the audit list surfaced
    in the data-quality panel), keyed by ``row_index`` — nothing is dropped.

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
        rows=list(flags),
    )
