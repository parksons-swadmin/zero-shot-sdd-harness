from datetime import date

from pydantic import BaseModel, Field

from domain.quality import DataQualityReport, RiskFlag


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


class EmployeeSummary(BaseModel):
    """Per-employee (salesperson) rollup for the ranked employee table (Phase 2)."""

    employee: str
    total_outstanding: float
    total_overdue: float
    pct_overdue: float
    worst_bucket: str
    invoice_count: int


class CustomerBreakdown(BaseModel):
    """Per-customer aging-bucket breakdown + weighted-avg days overdue (Phase 2).

    ``weighted_avg_days_overdue`` is ``None`` when the group has no overdue
    balance (never 0-as-if-computed, never a divide-by-zero).
    """

    key: str
    bucket_totals: BucketTotals
    weighted_avg_days_overdue: float | None
    pct_overdue: float
    total_outstanding: float


class EmployeeBreakdown(BaseModel):
    """Per-employee aging-bucket breakdown + weighted-avg days overdue (Phase 2)."""

    key: str
    bucket_totals: BucketTotals
    weighted_avg_days_overdue: float | None
    pct_overdue: float
    total_outstanding: float


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

    # Phase-2 fields — always populated by the deterministic engine (default to
    # empty lists so the wire shape stays stable if a partition is empty).
    employees: list[EmployeeSummary] = Field(default_factory=list)
    customer_breakdown: list[CustomerBreakdown] = Field(default_factory=list)
    employee_breakdown: list[EmployeeBreakdown] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
