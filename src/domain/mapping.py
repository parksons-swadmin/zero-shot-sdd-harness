from typing import Literal

from pydantic import BaseModel

from domain.quality import QualityFlag


class ColumnMapping(BaseModel):
    """Confirmed mapping from the six canonical fields to source column names.

    ``hod`` (Head of Department / the salesperson's manager) is a strictly
    OPTIONAL seventh field: it never gates compute, defaults to ``None`` when
    unmapped, and is not part of the six required canonical fields.
    """

    customer: str
    invoice_no: str
    invoice_date: str
    due_date: str
    amount: str
    employee: str
    hod: str | None = None

    def as_dict(self) -> dict[str, str]:
        """The six REQUIRED canonical field → column mappings.

        Intentionally excludes the optional ``hod`` so every consumer
        (validation, normalization, duplicate detection) treats only the six as
        required. Read ``mapping.hod`` directly for the optional field.
        """
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
    # Additive signal: when True, all six required fields were resolved to
    # distinct high-confidence columns (a recognized standard export), so the
    # client may skip the mapping-confirm screen. Defaults False for every sheet
    # that does not fully auto-resolve — preserving the existing confirm flow.
    auto_mapped: bool = False
