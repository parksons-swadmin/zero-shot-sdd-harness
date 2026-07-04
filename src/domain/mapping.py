from typing import Literal

from pydantic import BaseModel

from domain.quality import QualityFlag


class ColumnMapping(BaseModel):
    """Confirmed mapping from the six canonical fields to source column names."""

    customer: str
    invoice_no: str
    invoice_date: str
    due_date: str
    amount: str
    employee: str

    def as_dict(self) -> dict[str, str]:
        return {
            "customer": self.customer,
            "invoice_no": self.invoice_no,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
            "amount": self.amount,
            "employee": self.employee,
        }


class FieldMatch(BaseModel):
    """One auto-detected canonical-field → source-column proposal."""

    field: str
    matched_column: str | None
    confidence: int
    status: Literal["high", "low", "unmatched"]


class PreviewResult(BaseModel):
    """Response payload for POST /api/preview."""

    sheets: list[str]
    sheet_name: str
    columns: list[str]
    proposed_mapping: list[FieldMatch]
    preview_rows: list[dict]
    parse_flags: list[QualityFlag]
