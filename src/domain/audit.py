from datetime import datetime

from pydantic import BaseModel


class AuditLogEntryOut(BaseModel):
    id: str
    session_id: str | None = None
    dataset_id: str | None = None
    query_result_id: str | None = None
    event_type: str
    detail: dict
    created_at: datetime
