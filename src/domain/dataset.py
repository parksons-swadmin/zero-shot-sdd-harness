from datetime import datetime

from pydantic import BaseModel


class TopValueOut(BaseModel):
    value: str
    count: int


class ColumnProfileOut(BaseModel):
    name: str
    dtype: str
    null_count: int
    distinct_count: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    top_values: list[TopValueOut] | None = None


class DatasetProfileOut(BaseModel):
    columns: list[ColumnProfileOut]


class CleaningIssueOut(BaseModel):
    column: str
    issue_type: str
    action_taken: str
    affected_row_count: int
    needs_review: bool


class CleaningReportOut(BaseModel):
    issues: list[CleaningIssueOut]


class DatasetUploadResponse(BaseModel):
    dataset_id: str
    filename: str
    row_count: int | None = None
    column_count: int | None = None
    status: str
    profile: DatasetProfileOut
    cleaning_report: CleaningReportOut


class DatasetListItemOut(BaseModel):
    dataset_id: str
    filename: str
    row_count: int | None = None
    column_count: int | None = None
    status: str
    created_at: datetime


class DatasetListResponse(BaseModel):
    datasets: list[DatasetListItemOut]
