from datetime import date

from pydantic import BaseModel

from domain.quality import DataQualityReport


class BucketTotals(BaseModel):
    """Rupee totals for the current bucket plus the four overdue buckets."""

    current: float
    b_0_30: float
    b_31_60: float
    b_61_90: float
    b_90_plus: float


class CustomerOverdue(BaseModel):
    """One customer's overdue + outstanding rupee totals (for the Top-20 chart)."""

    customer: str
    overdue_amount: float
    outstanding_amount: float


class AgingMetrics(BaseModel):
    """Computed AR aging metrics (compute node output).

    Money fields are rupee floats (paise / 100, 2dp) for the wire; all internal
    aggregation is done in integer paise for exact tie-out.
    """

    as_of: date
    row_count: int
    total_outstanding: float
    total_overdue: float
    pct_overdue: float
    customer_count: int
    worst_bucket: str
    bucket_totals: BucketTotals
    top_customers_by_overdue: list[CustomerOverdue]
    data_quality: DataQualityReport

    # Phase-2 fields — present but default None so the wire shape is stable.
    employees: list | None = None
    customer_breakdown: list | None = None
    employee_breakdown: list | None = None
    risk_flags: list | None = None
