"""Fixture builder + INDEPENDENT expected-value oracles.

The oracle here is a deliberately dead-simple, pure-Python summation that shares
NO code with ``src/tools`` — so agreement between the pipeline and this oracle is
a genuine tie-out, not a tautology.

- ``ar_small.xlsx`` + ``expected_small.json`` are committed (they drive the API
  integration test, the Playwright E2E, and the user handoff).
- ``ar_large.xlsx`` (>= 60,000 rows) is NOT committed (it is gitignored) — the
  unit/integration suites build it into a tmp path via a session-scoped pytest
  fixture (see ``tests/conftest.py``), but the Phase-3 frontend Playwright E2E
  uploads the on-disk ``tests/fixtures/ar_large.xlsx``. Regenerate it on disk
  (same seeded generator the conftest fixture uses) with the ``--large`` flag.

Run directly to (re)generate the committed small fixture:

    uv run python tests/fixtures/build_fixtures.py

Regenerate the (gitignored) >=60,000-row large fixture on disk for the E2E:

    uv run python tests/fixtures/build_fixtures.py --large
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import Workbook

AS_OF = date(2026, 1, 15)
FIXTURE_DIR = Path(__file__).resolve().parent

_EXCEL_EPOCH = date(1899, 12, 30)

# Mirrors the default of ``AGENT_RISK_TOP_N`` in src/config/settings.py WITHOUT
# importing it — the oracle stays a fully independent pure-Python computation.
RISK_TOP_N = 5

# The five reportable buckets (``unclassified`` is deliberately excluded — a
# no-due-date row lands in no bucket, so the five bucket amounts need not sum to
# a group's total_outstanding).
_FIVE_BUCKETS = ["current", "0-30", "31-60", "61-90", "90+"]

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


def _oracle_worst_bucket(buckets: dict[str, int], has_overdue: bool) -> str:
    """Largest overdue bucket, oldest wins ties; ``none`` when no overdue rows."""
    if not has_overdue:
        return "none"
    best = "90+"
    for b in ["61-90", "31-60", "0-30"]:
        if buckets[b] > buckets[best]:
            best = b
    return best


def _oracle_bucket_totals(buckets: dict[str, int]) -> dict[str, float]:
    return {
        "current": _rupees(buckets["current"]),
        "b_0_30": _rupees(buckets["0-30"]),
        "b_31_60": _rupees(buckets["31-60"]),
        "b_61_90": _rupees(buckets["61-90"]),
        "b_90_plus": _rupees(buckets["90+"]),
    }


def _new_group() -> dict:
    return {
        "outstanding": 0,
        "overdue": 0,
        "wnum": 0,  # sum(paise_i * dpd_i) over overdue rows
        "count": 0,
        "overdue_rows": 0,
        "buckets": {b: 0 for b in _FIVE_BUCKETS},
    }


def _group_records(group: dict[str, dict], sort_key) -> list[dict]:
    """Emit ordered {key, bucket_totals, weighted_avg_days_overdue, pct_overdue,
    total_outstanding} records (+ paise variants) for a partition."""
    records = []
    for key, g in group.items():
        wden = g["overdue"]
        wavg = None if wden == 0 else round(g["wnum"] / wden, 2)
        records.append(
            {
                "key": key,
                "bucket_totals": _oracle_bucket_totals(g["buckets"]),
                "bucket_totals_paise": dict(g["buckets"]),
                "weighted_avg_days_overdue": wavg,
                "pct_overdue": (g["overdue"] / g["outstanding"]) if g["outstanding"] != 0 else 0.0,
                "total_outstanding": _rupees(g["outstanding"]),
                "total_outstanding_paise": g["outstanding"],
            }
        )
    records.sort(key=sort_key)
    return records


def compute_expected(rows: list[dict], as_of: date) -> dict:
    """Dead-simple independent summation over every row."""
    outstanding = 0
    overdue = 0
    bucket_paise = {"current": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    per_customer: dict[str, dict[str, int]] = {}
    per_customer_full: dict[str, dict] = {}
    per_employee: dict[str, dict] = {}
    cust_90: dict[str, int] = {}
    flags: list[dict] = []

    for idx, r in enumerate(rows):
        p = _paise(r["amount"])
        due = r["due_date"]
        dpd = (as_of - due).days if due is not None else None
        bucket = _oracle_bucket(dpd)
        is_overdue = dpd is not None and dpd > 0

        outstanding += p
        if is_overdue:
            overdue += p
        if bucket in bucket_paise:
            bucket_paise[bucket] += p

        cust = r["customer"] if (r["customer"] and str(r["customer"]).strip()) else "(blank)"
        emp = r["employee"] if (r["employee"] and str(r["employee"]).strip()) else "(blank)"

        pc = per_customer.setdefault(cust, {"overdue": 0, "outstanding": 0})
        pc["outstanding"] += p
        if is_overdue:
            pc["overdue"] += p

        for label, store in ((cust, per_customer_full), (emp, per_employee)):
            g = store.setdefault(label, _new_group())
            g["outstanding"] += p
            g["count"] += 1
            if bucket in g["buckets"]:
                g["buckets"][bucket] += p
            if is_overdue:
                g["overdue"] += p
                g["wnum"] += p * dpd
                g["overdue_rows"] += 1

        if bucket == "90+":
            cust_90[cust] = cust_90.get(cust, 0) + p

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
    worst = _oracle_worst_bucket(bucket_paise, has_overdue)

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

    # Phase-2: employee summary (outstanding desc, overdue desc, employee asc).
    employees = [
        {
            "employee": key,
            "total_outstanding": _rupees(g["outstanding"]),
            "total_overdue": _rupees(g["overdue"]),
            "total_outstanding_paise": g["outstanding"],
            "total_overdue_paise": g["overdue"],
            "pct_overdue": (g["overdue"] / g["outstanding"]) if g["outstanding"] != 0 else 0.0,
            "worst_bucket": _oracle_worst_bucket(g["buckets"], g["overdue_rows"] > 0),
            "invoice_count": g["count"],
        }
        for key, g in sorted(
            per_employee.items(),
            key=lambda kv: (-kv[1]["outstanding"], -kv[1]["overdue"], kv[0]),
        )
    ]

    # Phase-2: per-group aging breakdowns (outstanding desc, key asc).
    breakdown_sort = lambda rec: (-rec["total_outstanding_paise"], rec["key"])  # noqa: E731
    customer_breakdown = _group_records(per_customer_full, breakdown_sort)
    employee_breakdown = _group_records(per_employee, breakdown_sort)

    # Phase-2: risk flags — customers by 90+ overdue desc, name asc, top N.
    risk_flags = [
        {"customer": c, "reason": "largest 90+ overdue", "amount": _rupees(v), "bucket": "90+"}
        for c, v in sorted(
            ((c, v) for c, v in cust_90.items() if v != 0),
            key=lambda kv: (-kv[1], kv[0]),
        )[:RISK_TOP_N]
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
        "employees": employees,
        "customer_breakdown": customer_breakdown,
        "employee_breakdown": employee_breakdown,
        "risk_flags": risk_flags,
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


# --------------------------------------------------------------------------- #
# Synthetic embedded summary/grand-total fixture (built to a tmp path in tests;
# NEVER committed and NEVER derived from any real customer file). Exercises the
# SAP-style embedded-total-row exclusion without touching ar_small/expected_small.
# --------------------------------------------------------------------------- #
SUMMARY_HEADERS: dict[str, str] = {
    "customer": "Payer Name",
    "invoice_no": "Invoice No.",
    "invoice_date": "Billing Date",
    "due_date": "Due Date",
    "amount": "Amount Due",
    "employee": "Current Employee",
}

# Real invoice rows that MUST survive and net in (incl. the guardrails from the
# diagnosis: a blank-employee row and a negative credit note, both with a real
# customer + due date).
SUMMARY_KEEP_ROWS: list[dict] = [
    dict(customer="Acme Corp", invoice_no="K-001", invoice_date=_d(2025, 10, 1),
         due_date=_d(2025, 11, 1), due_fmt="native", amount=1000000.00, employee="Ravi"),
    dict(customer="Beacon & Co", invoice_no="K-002", invoice_date=_d(2025, 9, 1),
         due_date=_d(2025, 10, 1), due_fmt="native", amount=500000.00, employee="Priya"),
    # guardrail: blank employee, but real customer + due date -> KEPT
    dict(customer="Acme Corp", invoice_no="K-003", invoice_date=_d(2025, 11, 1),
         due_date=_d(2025, 12, 1), due_fmt="native", amount=250000.00, employee=None),
    # guardrail: negative credit note with full identity -> KEPT, nets in
    dict(customer="Beacon & Co", invoice_no="K-004", invoice_date=_d(2025, 11, 1),
         due_date=_d(2025, 12, 1), due_fmt="native", amount=-100000.00, employee="Ravi"),
]

# Embedded summary/grand-total rows that MUST be excluded before aggregation.
SUMMARY_EXCLUDE_ROWS: list[dict] = [
    # (a) employee == "Totals", all dimensions blank -- the real-file pattern.
    dict(customer=None, invoice_no=None, invoice_date=None,
         due_date=None, due_fmt="blank", amount=999999999.00, employee="Totals"),
    # (a) DUPLICATE "Totals" row (real exports embed more than one).
    dict(customer=None, invoice_no=None, invoice_date=None,
         due_date=None, due_fmt="blank", amount=999999999.00, employee="Totals"),
    # (a) "Grand Total" variant on the employee column.
    dict(customer=None, invoice_no=None, invoice_date=None,
         due_date=None, due_fmt="blank", amount=888888888.00, employee="Grand Total"),
    # (a) total marker on the CUSTOMER column (with a due date, so only rule (a) can catch it).
    dict(customer="Totals", invoice_no="T-1", invoice_date=_d(2025, 11, 1),
         due_date=_d(2025, 12, 1), due_fmt="native", amount=123456.00, employee="Ravi"),
    # (b) bare total: numeric amount but no customer / due date / invoice number.
    dict(customer=None, invoice_no=None, invoice_date=None,
         due_date=None, due_fmt="blank", amount=777777777.00, employee=None),
]

SUMMARY_MAPPING = {
    "customer": "Payer Name",
    "invoice_no": "Invoice No.",
    "invoice_date": "Billing Date",
    "due_date": "Due Date",
    "amount": "Amount Due",
    "employee": "Current Employee",
}


def build_summary(path: Path, as_of: date = AS_OF) -> dict:
    """Write KEEP + embedded summary rows; expected values tie out over KEEP only.

    The workbook contains every row, but the returned oracle is computed over the
    KEEP rows only -- so a correct pipeline (which excludes the summary rows) must
    equal it, while any pipeline that sums the total rows blows the total up by
    billions.
    """
    rows = SUMMARY_KEEP_ROWS + SUMMARY_EXCLUDE_ROWS
    _write_workbook(path, SUMMARY_HEADERS, rows)
    expected = compute_expected(SUMMARY_KEEP_ROWS, as_of)
    expected["summary_row_excluded"] = len(SUMMARY_EXCLUDE_ROWS)
    expected["mapping"] = dict(SUMMARY_MAPPING)
    return expected


def write_expected_json() -> Path:
    """(Re)write ``expected_small.json`` from the oracle WITHOUT touching the
    committed ``ar_small.xlsx`` binary (its rows are unchanged, so rewriting the
    workbook would only churn the binary)."""
    expected = compute_expected(SMALL_ROWS, AS_OF)
    out = FIXTURE_DIR / "expected_small.json"
    out.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_large_fixture(path: Path | None = None, n: int = 60000, seed: int = 12345) -> Path:
    """(Re)generate the >=60,000-row ``ar_large.xlsx`` on disk + its oracle JSON.

    Uses the SAME seeded generator (``build_large`` -> ``build_large_rows``) the
    session-scoped ``large_fixture`` conftest fixture uses, so the on-disk file is
    identical to the one the unit/integration suites build in a tmp path. Both
    outputs are gitignored — never commit them.
    """
    path = path or (FIXTURE_DIR / "ar_large.xlsx")
    expected = build_large(path, n=n, seed=seed)
    (FIXTURE_DIR / "expected_large.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def main() -> None:
    # --large regenerates ONLY the gitignored large fixture on disk (for the
    # Phase-3 frontend E2E). It is a multi-MB binary and must never be committed.
    if "--large" in sys.argv:
        path = build_large_fixture()
        expected = compute_expected(build_large_rows(), AS_OF)
        print(f"Wrote {path} ({expected['row_count']} rows) and expected_large.json")
        print(f"total_outstanding_paise={expected['total_outstanding_paise']} "
              f"top={expected['top_customers_by_overdue'][0]['customer']}")
        return

    json_only = "--json-only" in sys.argv
    if not json_only:
        build_small()
        print(f"Wrote {FIXTURE_DIR / 'ar_small.xlsx'}")
    out = write_expected_json()
    expected = compute_expected(SMALL_ROWS, AS_OF)
    print(f"Wrote {out}")
    print(f"total_outstanding={expected['total_outstanding']} total_overdue={expected['total_overdue']} "
          f"worst_bucket={expected['worst_bucket']} top={expected['top_customers_by_overdue'][0]['customer']}")
    # NOTE: ar_large.xlsx is intentionally NOT written by the default run — it is
    # a multi-MB binary rebuilt into a tmp path per test session (see
    # tests/conftest.py). Use `--large` to (re)generate it on disk for the E2E.


if __name__ == "__main__":
    main()
