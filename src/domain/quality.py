from pydantic import BaseModel, Field


class QualityFlag(BaseModel):
    """A single data-quality issue raised at parse/validate time, keyed by row."""

    row_index: int
    field: str
    reason: str
    raw_value: str | None = None


class RiskFlag(BaseModel):
    """A proactive riskiest-account flag (populated in Phase 2)."""

    customer: str
    reason: str
    amount: float
    bucket: str


class DataQualityReport(BaseModel):
    """Aggregate data-quality summary attached to AgingMetrics."""

    flagged_row_count: int
    unparseable_row_count: int
    by_reason: dict[str, int]
    rows: list[QualityFlag] = Field(default_factory=list)
