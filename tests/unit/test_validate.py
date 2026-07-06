"""Validation flags exactly the seeded bad rows; never drops a row."""

from datetime import date

import pandas as pd

from domain.mapping import ColumnMapping
from tools.ingest import normalize, read_workbook
from tools.validate import validate

AS_OF = date(2026, 1, 15)


def test_flags_exactly_the_seeded_bad_rows(small_xlsx_bytes, small_mapping, expected_small):
    df, _ = read_workbook(small_xlsx_bytes, None)
    out = normalize(df, small_mapping, AS_OF)
    flags = validate(out)

    got = sorted((f.row_index, f.field, f.reason) for f in flags)
    want = sorted((f["row_index"], f["field"], f["reason"]) for f in expected_small["flags"])
    assert got == want


def test_each_reason_type_fires():
    mapping = ColumnMapping(
        customer="cust", invoice_no="inv", invoice_date="idt",
        due_date="ddt", amount="amt", employee="emp",
    )
    rows = [
        {"cust": "A", "inv": "1", "idt": date(2025, 1, 1), "ddt": None, "amt": 10.0, "emp": "R"},   # missing_due_date
        {"cust": "A", "inv": "2", "idt": None, "ddt": date(2025, 1, 1), "amt": 10.0, "emp": "R"},   # missing_invoice_date
        {"cust": "A", "inv": "3", "idt": date(2025, 1, 1), "ddt": date(2025, 1, 1), "amt": -5.0, "emp": "R"},  # negative
        {"cust": "A", "inv": "4", "idt": date(2025, 1, 1), "ddt": date(2025, 1, 1), "amt": 0.0, "emp": "R"},   # zero
        {"cust": "A", "inv": "5", "idt": date(2025, 1, 1), "ddt": date(2025, 1, 1), "amt": "xyz", "emp": "R"},  # non_numeric
        {"cust": None, "inv": "6", "idt": date(2025, 1, 1), "ddt": date(2025, 1, 1), "amt": 10.0, "emp": None},  # blanks
    ]
    out = normalize(pd.DataFrame(rows, dtype=object), mapping, AS_OF)
    reasons = {(f.row_index, f.reason) for f in validate(out)}

    assert (0, "missing_due_date") in reasons
    assert (1, "missing_invoice_date") in reasons
    assert (2, "negative_amount") in reasons
    assert (3, "zero_amount") in reasons
    assert (4, "non_numeric_amount") in reasons
    assert (5, "blank_customer") in reasons
    assert (5, "blank_employee") in reasons
