from datetime import datetime

from pydantic import BaseModel

from domain.query_result import QueryResultOut


class CreateSessionRequest(BaseModel):
    dataset_ids: list[str]


class CreateSessionResponse(BaseModel):
    session_id: str
    dataset_ids: list[str]


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    query_result: QueryResultOut | None = None


class SessionHistoryResponse(BaseModel):
    session_id: str
    dataset_ids: list[str]
    messages: list[MessageOut]
