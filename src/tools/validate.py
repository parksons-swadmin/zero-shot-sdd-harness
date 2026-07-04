"""Guardrail validation. Emits one QualityFlag per issue; never drops a row."""

from __future__ import annotations

import pandas as pd

from domain.quality import QualityFlag

BLANK = "(blank)"


def _raw(value: object) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value)
    return text if text else None


def validate(df: pd.DataFrame) -> list[QualityFlag]:
    """Return data-quality flags keyed by original ``row_index``.

    Reasons (stable strings): ``missing_due_date``, ``missing_invoice_date``,
    ``non_numeric_amount``, ``negative_amount``, ``zero_amount``,
    ``blank_customer``, ``blank_employee``. A missing/unparseable date yields
    ``missing_*`` (both resolve to NaT).
    """
    flags: list[QualityFlag] = []

    for row in df.itertuples(index=False):
        idx = int(row.row_index)

        if row.due_date is None or (isinstance(row.due_date, float) and pd.isna(row.due_date)):
            flags.append(
                QualityFlag(row_index=idx, field="due_date", reason="missing_due_date", raw_value=_raw(row.raw_due))
            )

        if row.invoice_date is None or (isinstance(row.invoice_date, float) and pd.isna(row.invoice_date)):
            flags.append(
                QualityFlag(
                    row_index=idx, field="invoice_date", reason="missing_invoice_date", raw_value=_raw(row.raw_invoice)
                )
            )

        if not row.amount_valid:
            flags.append(
                QualityFlag(row_index=idx, field="amount", reason="non_numeric_amount", raw_value=_raw(row.raw_amount))
            )
        else:
            paise = int(row.amount_paise)
            if paise < 0:
                flags.append(
                    QualityFlag(row_index=idx, field="amount", reason="negative_amount", raw_value=_raw(row.raw_amount))
                )
            elif paise == 0:
                flags.append(
                    QualityFlag(row_index=idx, field="amount", reason="zero_amount", raw_value=_raw(row.raw_amount))
                )

        if row.customer == BLANK:
            flags.append(QualityFlag(row_index=idx, field="customer", reason="blank_customer", raw_value=None))

        if row.employee == BLANK:
            flags.append(QualityFlag(row_index=idx, field="employee", reason="blank_employee", raw_value=None))

    return flags
