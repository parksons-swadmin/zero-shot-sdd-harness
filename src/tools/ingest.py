"""Workbook reading + normalization into the canonical invoice frame.

No row is ever dropped. Unparseable values become NaT / flagged rather than
guessed. All money is converted once to exact integer paise.
"""

from __future__ import annotations

import io
import math
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd

from domain.mapping import ColumnMapping

# Excel's 1900 date system epoch as used by openpyxl/pandas (accounts for the
# 1900 leap-year bug): serial 1 == 1899-12-31, so the base is 1899-12-30.
_EXCEL_EPOCH = date(1899, 12, 30)

CANONICAL_COLUMNS = ["customer", "invoice_no", "invoice_date", "due_date", "amount", "employee"]


def read_workbook(file_bytes: bytes, sheet_name: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Read the chosen sheet of an ``.xlsx`` workbook.

    Returns ``(dataframe, all_sheet_names)``. Raises ``ValueError`` when the
    bytes are not a readable workbook and ``KeyError`` when ``sheet_name`` is
    not present.
    """
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:  # noqa: BLE001 - any parse failure is a bad file
        raise ValueError(str(exc)) from exc

    sheets = list(xls.sheet_names)
    if not sheets:
        raise ValueError("workbook contains no sheets")

    chosen = sheet_name if sheet_name else sheets[0]
    if chosen not in sheets:
        raise KeyError(chosen)

    df = xls.parse(sheet_name=chosen, dtype=object)
    return df, sheets


def _parse_date(value: object) -> date | None:
    """Parse a native Excel date, an Excel serial number, or an ISO/dd-mm string.

    Returns ``None`` (→ NaT / unclassified) when the value is missing or cannot
    be parsed. Never guesses.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()

    if isinstance(value, (int, float)):
        try:
            serial = int(round(float(value)))
        except (ValueError, OverflowError):
            return None
        if serial <= 0 or serial > 400000:  # implausible as an Excel serial date
            return None
        try:
            return _EXCEL_EPOCH + timedelta(days=serial)
        except OverflowError:
            return None

    text = str(value).strip()
    if not text:
        return None
    try:
        # Unambiguous ISO yyyy-mm-dd (avoids the dayfirst warning for ISO input).
        return date.fromisoformat(text)
    except ValueError:
        pass
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if parsed is pd.NaT or pd.isna(parsed):
        return None
    return parsed.to_pydatetime().date()


def _parse_amount(value: object) -> tuple[int, bool]:
    """Return ``(amount_paise, is_numeric)``.

    Non-numeric / blank values yield ``(0, False)`` and are flagged; the row is
    retained. Numeric values are converted to exact integer paise.
    """
    if value is None:
        return 0, False
    if isinstance(value, float) and math.isnan(value):
        return 0, False

    if isinstance(value, bool):  # guard: bool is an int subclass
        return 0, False

    text = str(value).strip().replace(",", "").replace("₹", "").strip()
    if text.lower().startswith("rs"):
        text = text[2:].strip().lstrip(".").strip()
    if not text:
        return 0, False

    try:
        paise = int(Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, ValueError):
        return 0, False
    return paise, True


def _bucket(dpd: int | None) -> str:
    if dpd is None:
        return "unclassified"
    if dpd <= 0:
        return "current"
    if dpd <= 30:
        return "0-30"
    if dpd <= 60:
        return "31-60"
    if dpd <= 90:
        return "61-90"
    return "90+"


def _clean_text(value: object) -> str:
    if value is None:
        return "(blank)"
    if isinstance(value, float) and math.isnan(value):
        return "(blank)"
    text = str(value).strip()
    return text if text else "(blank)"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text if text else None


def normalize(df: pd.DataFrame, mapping: ColumnMapping, as_of: date) -> pd.DataFrame:
    """Apply the confirmed mapping and produce the canonical invoice frame.

    Output columns: ``row_index, customer, invoice_no, invoice_date, due_date,
    amount_paise, amount_valid, employee, dpd, bucket`` plus ``_raw_*`` columns
    (original source values, used only to populate quality-flag ``raw_value``).
    Rows are never dropped.
    """
    m = mapping.as_dict()
    raw_customer = df[m["customer"]]
    raw_invoice_no = df[m["invoice_no"]]
    raw_invoice_date = df[m["invoice_date"]]
    raw_due_date = df[m["due_date"]]
    raw_amount = df[m["amount"]]
    raw_employee = df[m["employee"]]

    n = len(df)
    out = pd.DataFrame({"row_index": range(n)})

    out["customer"] = [_clean_text(v) for v in raw_customer]
    out["employee"] = [_clean_text(v) for v in raw_employee]
    out["invoice_no"] = [_optional_text(v) for v in raw_invoice_no]

    out["invoice_date"] = [_parse_date(v) for v in raw_invoice_date]
    due_dates = [_parse_date(v) for v in raw_due_date]
    out["due_date"] = due_dates

    amounts = [_parse_amount(v) for v in raw_amount]
    out["amount_paise"] = pd.array([p for p, _ in amounts], dtype="int64")
    out["amount_valid"] = [ok for _, ok in amounts]

    dpd_vals: list[int | None] = [
        (as_of - d).days if isinstance(d, date) else None for d in due_dates
    ]
    out["dpd"] = pd.array(dpd_vals, dtype="Int64")
    out["bucket"] = [_bucket(d) for d in dpd_vals]

    # Raw values retained for faithful quality-flag reporting only.
    # (No leading underscore — itertuples cannot expose underscore-prefixed cols.)
    out["raw_due"] = [_optional_text(v) for v in raw_due_date]
    out["raw_invoice"] = [_optional_text(v) for v in raw_invoice_date]
    out["raw_amount"] = [_optional_text(v) for v in raw_amount]
    out["raw_customer"] = [_optional_text(v) for v in raw_customer]
    out["raw_employee"] = [_optional_text(v) for v in raw_employee]

    return out
