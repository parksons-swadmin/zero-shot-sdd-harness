"""Fixture builder + INDEPENDENT expected-value oracles.

The oracle here is a deliberately dead-simple, pure-Python summation that shares
NO code with ``src/tools`` — so agreement between the pipeline and this oracle is
a genuine tie-out, not a tautology.

- ``ar_small.xlsx`` + ``expected_small.json`` are committed (they drive the API
  integration test, the Playwright E2E, and the user handoff).
- ``ar_large.xlsx`` (>= 60,000 rows) is NOT committed — it is built into a tmp
  path by a session-scoped pytest fixture (see ``tests/conftest.py``).

Run directly to (re)generate the committed small fixture:

    uv run python tests/fixtures/build_fixtures.py
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import Workbook

AS_OF = date(2026, 1, 15)
FIXTURE_DIR = Path(__file__).resolve().parent

_EXCEL_EPOCH = date(1899, 12, 30)

DEVANAGARI = "श्री एंटरप्राइजेज"  # श्री एंटरप्राइजेज

# Deliberately messy headers to exercise fuzzy matching. "Payable On" is chosen
# for due_date because it lands at LOW confidence (exercising the confirm path);
# a header like "Due Dt" is near-identical to the "due date"/"due dt" seeds and
# would resolve HIGH, defeating the confirm-screen requirement.
SMALL_HEADERS: dict[str, str] = {
    "customer": "Cust Name",
    "invoice_no": "Invoice #",
    "invoice_date": "Inv. Date",
    "due_date": "Payable On",
    "amount": "Balance Outstanding",
    "employee": "Sales Person",
}


def _d(y: int, m: int, day: int) -> date:
    return date(y, m, day)


# row_index == position in this list (0-based data row).
SMALL_ROWS: list[dict] = [
    dict(customer="Beacon & Co", invoice_no="INV-1001", invoice_date=_d(2025, 5, 18),
         due_date=_d(2025, 6, 18), due_fmt="native", amount=2500000.00, employee="Ravi"),
    dict(customer="Beacon & Co", invoice_no="INV-1002", invoice_date=_d(2025, 6, 20),
         due_date=_d(2025, 7, 20), due_fmt="native", amount=1250000.00, employee="Priya"),
    dict(customer="Acme Corp", invoice_no="INV-1003", invoice_date=_d(2025, 12, 18),
         due_date=_d(2026, 1, 20), due_fmt="native", amount=800000.00, employee="Ravi"),
    dict(customer="Acme Corp", invoice_no="INV-1004", invoice_date=_d(2025, 11, 18),
         due_date=_d(2025, 12, 20), due_fmt="iso", amount=1200000.00, employee="Priya"),
    dict(customer="Acme Corp", invoice_no="INV-1005", invoice_date=_d(2025, 10, 22),
         due_date=_d(2025, 11, 25), due_fmt="native", amount=900000.00, employee="Ravi"),
    dict(customer="Müller Traders", invoice_no="INV-1006", invoice_date=_d(2025, 9, 20),
         due_date=_d(2025, 10, 25), due_fmt="native", amount=800000.00, employee="Priya"),
    dict(customer="Müller Traders", invoice_no="INV-1007", invoice_date=_d(2025, 12, 20),
         due_date=_d(2026, 1, 25), due_fmt="native", amount=450000.00, employee="Ravi"),
    dict(customer=DEVANAGARI, invoice_no="INV-1008", invoice_date=_d(2025, 11, 13),
         due_date=_d(2025, 12, 10), due_fmt="native", amount=550000.00, employee="Priya"),
    dict(customer=DEVANAGARI, invoice_no="INV-1009", invoice_date=_d(2025, 10, 14),
         due_date=_d(2025, 11, 5), due_fmt="serial", amount=300000.00, employee="Ravi"),
    dict(customer="Zenith Ltd", invoice_no="INV-1010", invoice_date=_d(2025, 12, 20),
         due_date=_d(2026, 2, 10), due_fmt="native", amount=600000.00, employee="Priya"),
    dict(customer="Zenith Ltd", invoice_no="INV-1011", invoice_date=_d(2025, 12, 22),
         due_date=_d(2026, 3, 15), due_fmt="native", amount=400000.00, employee="Ravi"),
    dict(customer="Acme Corp", invoice_no="INV-1012", invoice_date=_d(2025, 4, 13),
         due_date=_d(2025, 5, 15), due_fmt="native", amount=250000.00, employee="Priya"),
    dict(customer="Müller Traders", invoice_no="INV-1013", invoice_date=_d(2025, 12, 20),
         due_date=_d(2026, 1, 14), due_fmt="native", amount=350000.00, employee="Ravi"),
    dict(customer=DEVANAGARI, invoice_no="INV-1014", invoice_date=_d(2025, 11, 14),
         due_date=_d(2025, 12, 14), due_fmt="native", amount=200000.00, employee="Priya"),
    # --- seeded edge/bad rows ---
    dict(customer="Acme Corp", invoice_no="INV-1015", invoice_date=_d(2025, 12, 13),
         due_date=None, due_fmt="blank", amount=500000.00, employee="Ravi"),           # missing_due_date
    dict(customer="Müller Traders", invoice_no="INV-1016", invoice_date=_d(2025, 11, 14),
         due_date=_d(2025, 12, 5), due_fmt="native", amount=-150000.00, employee="Priya"),  # negative_amount
    dict(customer=DEVANAGARI, invoice_no="INV-1017", invoice_date=_d(2025, 12, 16),
         due_date=_d(2026, 1, 30), due_fmt="native", amount=0.00, employee="Ravi"),     # zero_amount
    dict(customer="Acme Corp", invoice_no="INV-1018", invoice_date=_d(2025, 11, 20),
         due_date=_d(2025, 12, 22), due_fmt="native", amount=275000.00, employee=None),  # blank_employee
]


# --------------------------------------------------------------------------- #
# Independent oracle (pure Python, shares no code with src/tools)
# --------------------------------------------------------------------------- #
def _paise(amount: float) -> int:
    return int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def _oracle_bucket(dpd: int | None) -> str:
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


def _rupees(paise: int) -> float:
    return round(paise / 100, 2)


def compute_expected(rows: list[dict], as_of: date) -> dict:
    """Dead-simple independent summation over every row."""
    outstanding = 0
    overdue = 0
    bucket_paise = {"current": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    per_customer: dict[str, dict[str, int]] = {}
    flags: list[dict] = []

    for idx, r in enumerate(rows):
        p = _paise(r["amount"])
        due = r["due_date"]
        dpd = (as_of - due).days if due is not None else None
        bucket = _oracle_bucket(dpd)

        outstanding += p
        if dpd is not None and dpd > 0:
            overdue += p
        if bucket in bucket_paise:
            bucket_paise[bucket] += p

        cust = r["customer"] if (r["customer"] and str(r["customer"]).strip()) else "(blank)"
        pc = per_customer.setdefault(cust, {"overdue": 0, "outstanding": 0})
        pc["outstanding"] += p
        if dpd is not None and dpd > 0:
            pc["overdue"] += p

        emp_blank = not (r["employee"] and str(r["employee"]).strip())
        cust_blank = not (r["customer"] and str(r["customer"]).strip())
        if due is None:
            flags.append({"row_index": idx, "field": "due_date", "reason": "missing_due_date"})
        if p < 0:
            flags.append({"row_index": idx, "field": "amount", "reason": "negative_amount"})
        elif p == 0:
            flags.append({"row_index": idx, "field": "amount", "reason": "zero_amount"})
        if cust_blank:
            flags.append({"row_index": idx, "field": "customer", "reason": "blank_customer"})
        if emp_blank:
            flags.append({"row_index": idx, "field": "employee", "reason": "blank_employee"})

    has_overdue = any(
        (r["due_date"] is not None and (as_of - r["due_date"]).days > 0) for r in rows
    )
    worst = "none"
    if has_overdue:
        worst = "90+"
        for b in ["61-90", "31-60", "0-30"]:
            if bucket_paise[b] > bucket_paise[worst]:
                worst = b

    ranked = sorted(
        per_customer.items(),
        key=lambda kv: (-kv[1]["overdue"], -kv[1]["outstanding"], kv[0]),
    )
    top = [
        {
            "customer": name,
            "overdue_amount": _rupees(v["overdue"]),
            "outstanding_amount": _rupees(v["outstanding"]),
        }
        for name, v in ranked[:20]
    ]

    by_reason: dict[str, int] = {}
    flagged_rows = set()
    for f in flags:
        by_reason[f["reason"]] = by_reason.get(f["reason"], 0) + 1
        flagged_rows.add(f["row_index"])
    unparseable = sum(1 for r in rows if r["due_date"] is None)

    return {
        "as_of": as_of.isoformat(),
        "row_count": len(rows),
        "total_outstanding": _rupees(outstanding),
        "total_overdue": _rupees(overdue),
        "total_outstanding_paise": outstanding,
        "total_overdue_paise": overdue,
        "pct_overdue": (overdue / outstanding) if outstanding != 0 else 0.0,
        "customer_count": len({
            (r["customer"] if (r["customer"] and str(r["customer"]).strip()) else "(blank)") for r in rows
        }),
        "worst_bucket": worst,
        "bucket_totals": {
            "current": _rupees(bucket_paise["current"]),
            "b_0_30": _rupees(bucket_paise["0-30"]),
            "b_31_60": _rupees(bucket_paise["31-60"]),
            "b_61_90": _rupees(bucket_paise["61-90"]),
            "b_90_plus": _rupees(bucket_paise["90+"]),
        },
        "top_customers_by_overdue": top,
        "data_quality": {
            "flagged_row_count": len(flagged_rows),
            "unparseable_row_count": unparseable,
            "by_reason": by_reason,
        },
        "flags": flags,
    }


# --------------------------------------------------------------------------- #
# Workbook writers
# --------------------------------------------------------------------------- #
def _write_workbook(path: Path, headers: dict[str, str], rows: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Aging"
    order = ["customer", "invoice_no", "invoice_date", "due_date", "amount", "employee"]
    ws.append([headers[f] for f in order])

    for r in rows:
        due = r["due_date"]
        fmt = r.get("due_fmt", "native")
        if fmt == "blank" or due is None:
            due_cell = None
        elif fmt == "iso":
            due_cell = due.isoformat()
        elif fmt == "serial":
            due_cell = (due - _EXCEL_EPOCH).days
        else:
            due_cell = due
        ws.append([
            r["customer"],
            r["invoice_no"],
            r["invoice_date"],
            due_cell,
            r["amount"],
            r["employee"],
        ])
    wb.save(path)


def build_small(path: Path | None = None) -> Path:
    path = path or (FIXTURE_DIR / "ar_small.xlsx")
    _write_workbook(path, SMALL_HEADERS, SMALL_ROWS)
    return path


def build_large_rows(n: int = 60000, seed: int = 12345) -> list[dict]:
    """Deterministic rows; high-value overdue rows are placed in the LAST 100."""
    rng = random.Random(seed)
    customers = [f"Cust {i:04d}" for i in range(200)]
    employees = [f"Emp {i}" for i in range(10)]
    rows: list[dict] = []

    body = n - 100
    for i in range(body):
        cust = customers[rng.randrange(len(customers))]
        amount = round(rng.uniform(100.0, 5000.0), 2)
        offset = rng.randint(-30, 200)  # mix of current (<=0 dpd) and overdue
        due = AS_OF - timedelta(days=offset)
        rows.append(dict(
            customer=cust, invoice_no=f"L{i:06d}", invoice_date=due - timedelta(days=30),
            due_date=due, due_fmt="native", amount=amount, employee=employees[i % len(employees)],
        ))

    # Last 100 rows: a single whale customer, huge overdue balances that dominate
    # the total and the Top-20 — any prefix/truncating impl misses them.
    for j in range(100):
        amount = round(rng.uniform(5_000_000.0, 9_000_000.0), 2)
        due = AS_OF - timedelta(days=200 + j)  # deeply overdue
        rows.append(dict(
            customer="Zzz Whale Corp", invoice_no=f"W{j:04d}", invoice_date=due - timedelta(days=30),
            due_date=due, due_fmt="native", amount=amount, employee="Emp 0",
        ))
    return rows


LARGE_HEADERS: dict[str, str] = {
    "customer": "Customer",
    "invoice_no": "Invoice No",
    "invoice_date": "Invoice Date",
    "due_date": "Due Date",
    "amount": "Amount",
    "employee": "Employee",
}


def build_large(path: Path, n: int = 60000, seed: int = 12345) -> dict:
    rows = build_large_rows(n=n, seed=seed)
    _write_workbook(path, LARGE_HEADERS, rows)
    expected = compute_expected(rows, AS_OF)
    expected["top_customer"] = expected["top_customers_by_overdue"][0]["customer"]
    expected["top20_customers"] = [t["customer"] for t in expected["top_customers_by_overdue"][:20]]
    # Independent prefix oracle: summing only the first (n - 100) rows must differ
    # from the full total — proves the pipeline reads the high-value tail rows.
    expected["head_total_outstanding_paise"] = sum(_paise(r["amount"]) for r in rows[:-100])
    return expected


def main() -> None:
    build_small()
    expected = compute_expected(SMALL_ROWS, AS_OF)
    (FIXTURE_DIR / "expected_small.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {FIXTURE_DIR / 'ar_small.xlsx'}")
    print(f"Wrote {FIXTURE_DIR / 'expected_small.json'}")
    print(f"total_outstanding={expected['total_outstanding']} total_overdue={expected['total_overdue']} "
          f"worst_bucket={expected['worst_bucket']} top={expected['top_customers_by_overdue'][0]['customer']}")
    # NOTE: ar_large.xlsx is intentionally NOT written here — it is a multi-MB
    # binary rebuilt into a tmp path per test session (see tests/conftest.py) and
    # must never be committed. Use build_large(path) directly if you need a copy.


if __name__ == "__main__":
    main()
