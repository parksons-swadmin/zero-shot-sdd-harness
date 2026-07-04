"""Normalization: date/serial/ISO parsing, paise conversion, (blank), DPD/bucket."""

import io
from datetime import date

import pandas as pd
import pytest

from domain.mapping import ColumnMapping
from tools.ingest import _EXCEL_EPOCH, normalize, read_workbook

AS_OF = date(2026, 1, 15)

MAPPING = ColumnMapping(
    customer="cust", invoice_no="inv", invoice_date="idt",
    due_date="ddt", amount="amt", employee="emp",
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype=object)


def test_native_iso_and_serial_dates_parse_to_same_date():
    serial = (date(2025, 11, 5) - _EXCEL_EPOCH).days
    df = _frame([
        {"cust": "A", "inv": "1", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 20), "amt": 100.0, "emp": "R"},
        {"cust": "A", "inv": "2", "idt": date(2025, 11, 1), "ddt": "2025-12-20", "amt": 100.0, "emp": "R"},
        {"cust": "A", "inv": "3", "idt": date(2025, 11, 1), "ddt": serial, "amt": 100.0, "emp": "R"},
    ])
    out = normalize(df, MAPPING, AS_OF)
    assert out["due_date"].tolist() == [date(2025, 12, 20), date(2025, 12, 20), date(2025, 11, 5)]


def test_unparseable_due_date_becomes_none_unclassified():
    df = _frame([{"cust": "A", "inv": "1", "idt": date(2025, 11, 1), "ddt": "not a date", "amt": 100.0, "emp": "R"}])
    out = normalize(df, MAPPING, AS_OF)
    assert out["due_date"].iloc[0] is None
    assert out["bucket"].iloc[0] == "unclassified"
    assert pd.isna(out["dpd"].iloc[0])


def test_blank_customer_and_employee_become_blank_label():
    df = _frame([{"cust": None, "inv": "1", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": 100.0, "emp": "  "}])
    out = normalize(df, MAPPING, AS_OF)
    assert out["customer"].iloc[0] == "(blank)"
    assert out["employee"].iloc[0] == "(blank)"


@pytest.mark.parametrize(
    "amount,expected_paise,valid",
    [
        (1500000.00, 150000000, True),
        (-150000.00, -15000000, True),
        (0.00, 0, True),
        (1234.56, 123456, True),
        ("₹1,23,456.78", 12345678, True),
        ("abc", 0, False),
        (None, 0, False),
    ],
)
def test_amount_to_exact_paise(amount, expected_paise, valid):
    df = _frame([{"cust": "A", "inv": "1", "idt": date(2025, 11, 1), "ddt": date(2025, 12, 1), "amt": amount, "emp": "R"}])
    out = normalize(df, MAPPING, AS_OF)
    assert int(out["amount_paise"].iloc[0]) == expected_paise
    assert bool(out["amount_valid"].iloc[0]) is valid


@pytest.mark.parametrize(
    "dpd,expected_bucket",
    [
        (0, "current"),
        (1, "0-30"),
        (30, "0-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "90+"),
    ],
)
def test_dpd_bucket_boundary_table(dpd, expected_bucket):
    from datetime import timedelta

    due = AS_OF - timedelta(days=dpd)
    df = _frame([{"cust": "A", "inv": "1", "idt": date(2025, 11, 1), "ddt": due, "amt": 100.0, "emp": "R"}])
    out = normalize(df, MAPPING, AS_OF)
    assert int(out["dpd"].iloc[0]) == dpd
    assert out["bucket"].iloc[0] == expected_bucket


def test_no_row_is_ever_dropped(small_xlsx_bytes, small_mapping):
    df, _ = read_workbook(small_xlsx_bytes, None)
    out = normalize(df, small_mapping, AS_OF)
    assert len(out) == len(df) == 18
    assert out["row_index"].tolist() == list(range(18))


def test_read_workbook_lists_sheets(small_xlsx_bytes):
    df, sheets = read_workbook(small_xlsx_bytes, None)
    assert sheets == ["Aging"]
    assert len(df) == 18


def test_read_workbook_rejects_non_xlsx():
    with pytest.raises(ValueError):
        read_workbook(b"this is not a workbook", None)


def test_read_workbook_unknown_sheet_raises_keyerror(small_xlsx_bytes):
    with pytest.raises(KeyError):
        read_workbook(small_xlsx_bytes, "NoSuchSheet")
