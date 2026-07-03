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
