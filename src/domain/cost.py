from datetime import datetime

from pydantic import BaseModel


class CostRecordOut(BaseModel):
    id: str
    query_result_id: str | None = None
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    created_at: datetime


class CostTotals(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    call_count: int


class CostSummaryResponse(BaseModel):
    """GET /cost-summary — per-session (nullable) + all-time running totals.

    Both blocks are summed from CostRecord rows; each row's
    estimated_cost_usd was computed at write time from the Gemini price
    table in config/settings.py. `session` is null when no session_id is
    passed (per spec/api.md).
    """

    session: CostTotals | None = None
    all_time: CostTotals
