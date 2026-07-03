from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    dataset_ids: list[str]


class CreateSessionResponse(BaseModel):
    session_id: str
    dataset_ids: list[str]
