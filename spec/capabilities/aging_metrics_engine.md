# Capability: Aging Metrics Engine (Exact, Deterministic)

> **Phase 1.** The computational core. Every number it emits must tie out to the source Excel **exactly**.

## What It Does
Given normalized invoice rows and a confirmed column mapping, computes the exact AR aging metrics with vectorized pandas — outstanding, overdue, per-invoice days-past-due and aging bucket, overall bucket totals, % overdue, customer count, worst bucket, and the Top-20 customers by overdue amount — with zero sampling and zero float drift.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| invoices | normalized rows (customer, invoice_no, invoice_date, due_date, amount_paise, employee) | ingest node | yes |
| as_of | `date` | injected — `date.today()` in production; fixed value in tests | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| metrics | `AgingMetrics` (see [data.md](../data.md)) | compute node → assemble → API |

`AgingMetrics` (Phase-1 fields): `total_outstanding`, `total_overdue`, `pct_overdue`, `customer_count`, `worst_bucket`, `bucket_totals` (current + four overdue buckets), `top_customers_by_overdue` (≤20), `row_count`.

## External Calls
None. Pure in-memory computation over a pandas DataFrame. No network, no LLM, no DB.

## Business Rules — Exact Definitions (assert these verbatim)
Let each row be one invoice's balance. All monetary math is done in **integer paise** to guarantee exact tie-out (see "Exactness" below).

- **Days past due (DPD):** `dpd = (as_of - due_date).days`, both normalized to calendar `date` (time component dropped).
- **Current (not overdue):** `dpd <= 0` (i.e. `due_date >= as_of`).
- **Overdue:** `due_date < as_of`, i.e. `dpd > 0`.
- **Aging buckets** (days past due), assigned only to overdue rows:
  - `0-30` → `1 <= dpd <= 30`
  - `31-60` → `31 <= dpd <= 60`
  - `61-90` → `61 <= dpd <= 90`
  - `90+` → `dpd >= 91`
  - `current` (separate, not an overdue bucket) → `dpd <= 0`
- **Outstanding** = sum of **all** unpaid balances (every row, including current rows, flagged rows, and negative/zero amounts — summed as-is so the total ties out to the raw column).
- **Overdue** = sum of balances of overdue rows (the four overdue buckets).
- **% overdue** = `total_overdue / total_outstanding` (a ratio 0..1; `0.0` when outstanding is `0`).
- **Customer count** = number of distinct `customer` values present.
- **Worst bucket** = the overdue bucket with the largest total amount; ties broken toward the older bucket (`90+` > `61-90` > `31-60` > `0-30`). `"none"` when there is no overdue balance.
- **Top-20 customers by overdue** = customers ranked by total overdue amount, descending; ties broken by total outstanding desc, then customer name asc; top 20 returned (each with `customer`, `overdue_amount`, `outstanding_amount`).

### Handling of flagged rows (tie-out preserved)
- **Missing/unparseable due date:** the row's amount still counts in **outstanding** (it is an unpaid balance) but the row is **not** classified as overdue and appears in **no** bucket. Flagged.
- **Negative or zero amount:** included in the outstanding/overdue sums **as-is** (a negative reduces the total exactly as the raw column does), and flagged. Never silently zeroed or dropped.
- **Blank employee / blank customer:** does not affect totals; a blank customer is grouped under the literal label `"(blank)"` so it is visible, not merged away.

## Exactness / Tie-out Guarantee
- Every amount is converted once to integer paise: `paise = int(Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)`.
- All summation and aggregation is integer (`int64`) — **no float accumulation** — so totals are bit-exact and independent of row order or count.
- Reported rupee values = `paise / 100` rendered to 2 decimals.
- **No sampling, no truncation, no head(N).** Every metric is computed over the full row set. See the full-data gate in [roadmap.md](../roadmap.md).

## Success Criteria
- [ ] On `tests/fixtures/ar_small.xlsx` (fixed rows) with the fixed `as_of`, every field of `AgingMetrics` equals the hand-authored oracle in `tests/fixtures/expected_small.json` **exactly** (integer-paise equality).
- [ ] `total_outstanding` equals the exact integer-paise sum of the amount column (including the negative and zero rows) on both fixtures.
- [ ] Each invoice's bucket matches the boundary table for hand-chosen DPD values of 0, 1, 30, 31, 60, 61, 90, 91.
- [ ] On `tests/fixtures/ar_large.xlsx` (≥60,000 rows, high-value rows at the tail) `total_outstanding` and `row_count` equal the independent oracle in `expected_large.json`; a prefix/sample of the rows would produce a different total (proving no truncation).
- [ ] `pct_overdue` on a file with zero outstanding is `0.0`, not a divide-by-zero error.
- [ ] Worst-bucket tie between two buckets of equal amount resolves to the older bucket.
- [ ] Compute over the ≥60,000-row fixture completes in under 15 seconds.
