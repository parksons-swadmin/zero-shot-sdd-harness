from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class KeyNumberOut(BaseModel):
    label: str
    value: str


class AnomalyFlagOut(BaseModel):
    type: str
    column: str | None = None
    severity: str
    message: str


class QueryResultOut(BaseModel):
    id: str
    reasoning_mode: str
    summary_text: str
    key_numbers: list[KeyNumberOut] | None = None
    table: dict | None = None
    chart_spec: dict | None = None
    export_dataset_id: str | None = None
    generated_code: str
    follow_up_questions: list[str] | None = None
    anomaly_flags: list[AnomalyFlagOut] | None = None
    step_count: int
    status: str


class AskResponse(BaseModel):
    message_id: str
    query_result: QueryResultOut
