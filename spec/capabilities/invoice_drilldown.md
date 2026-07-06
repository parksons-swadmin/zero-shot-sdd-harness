# Capability: Invoice Drill-down

> **Phase 4.** Lets the user inspect the individual invoices behind the aggregates — the row-level view under the KPIs, chart, employee summary and breakdowns.

## What It Does
From the dashboard the user opens an inline drill-down section that lists individual invoices (one row per invoice) with a searchable customer picker and an employee filter, a sortable table, and a filtered subtotal + invoice count computed over the **full** filtered set. It is stateless and deterministic — a pure function of (uploaded file + confirmed mapping + optional filters).

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | `.xlsx` file (re-sent) | browser (`POST /api/invoices`) | yes |
| sheet_name | string | browser | no (first sheet) |
| mapping | `ColumnMapping` JSON (same shape as `/api/compute`) | browser | yes |
| customer | string (exact customer name) | customer picker | no |
| employee | string (exact employee name, incl. `"(blank)"`) | employee filter / employee-row click | no |
| as_of | `date` | injected — `date.today()` in production, fixed in tests (see [architecture.md](../architecture.md) Settings) | yes |

The customer-picker option list and the employee-filter option list are sourced **client-side** from the already-present `DashboardResult.customer_breakdown[].key` (the full distinct customer list) and `DashboardResult.employees[].employee` — no extra data on the wire. Type-to-search filters that list in the browser (fast for 1,000+ customers); the selected value is what is sent to `POST /api/invoices`.

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| result | `DrilldownResult` (see [data.md](../data.md)) | `POST /api/invoices` response → inline drill-down section |

`DrilldownResult`: `invoices` (`list[InvoiceRow]`), `total_count` (int), `subtotal_amount` (₹, 2dp), `truncated` (bool). `InvoiceRow`: `customer`, `invoice_no`, `amount` (₹, 2dp), `due_date` (ISO date or null), `days_overdue` (int or null), `bucket` (`current`/`0-30`/`31-60`/`61-90`/`90+`/`unclassified`), `employee`.

## External Calls
None. Pure in-memory filter/sort/aggregate over the same normalized `Invoice` rows produced by the ingest pipeline. No network, no LLM, no DB, no persistence.

## Business Rules
- **Same normalized rows as the engine.** Drill-down operates on the exact `Invoice` set the [metrics engine](aging_metrics_engine.md) uses. Embedded **summary / total rows are excluded** by the same rule ([summary-row detection](xlsx_ingestion_and_mapping.md#summary--total-row-detection--exclusion)); they are never materialized as invoice rows. Genuine data rows are **all included** — negative credit notes, zero amounts, blank employee (`"(blank)"`), and rows with a missing/unparseable due date (`bucket = unclassified`, `days_overdue = null`).
- **Per-row fields:** `amount = amount_paise / 100` (2dp); `days_overdue = dpd` (>0 overdue, `<= 0` current, `null` when due date missing); `due_date` = ISO `YYYY-MM-DD` or `null`; `bucket` = the engine's bucket enum (five named buckets + `unclassified`).
- **Filters combine with AND.** `customer` (exact match) AND `employee` (exact match, `"(blank)"` matches blank-employee rows). Either may be omitted; omitting both is the unfiltered view.
- **Filtered subtotal + count over the FULL filtered set.** `total_count` = number of rows in the full filtered set; `subtotal_amount` = exact **integer-paise** sum over the full filtered set, then `/ 100` (same exactness guarantee as [aging_metrics_engine.md](aging_metrics_engine.md)). These are computed over **every** matching row — never over the (possibly capped) returned page. Displayed as e.g. `Beacon & Co — 12 invoices · ₹37,50,000`.
- **Render cap + truncation (bounded response).** The endpoint applies a hard cap `AGENT_DRILLDOWN_MAX_ROWS` (default 1000; see [architecture.md](../architecture.md) Settings) on the number of rows returned in `invoices`. Rows are ordered by a deterministic **default sort** (`days_overdue` desc, `unclassified` last; ties → `amount` desc, then `invoice_no` asc, then `row_index` asc) and the first N are returned. `truncated = total_count > len(invoices)`. When a customer (and/or employee) filter is applied the matching set is virtually always within the cap, so `truncated=false` and the full matching set is returned; an unfiltered/broad view over a large file is capped (`truncated=true`) yet **still reports the true `total_count` and `subtotal_amount` over the full set** — a capped page never distorts the totals. The UI shows a "Showing first N of M — apply a filter to narrow" prompt when `truncated=true`.
- **Column sorting** (by amount, days overdue, due date) is a **client-side** concern over the returned rows (the given API contract carries no sort params); the deterministic server default sort governs only which rows survive truncation.
- **Stateless & deterministic:** identical (file + mapping + filters + `as_of`) → identical `DrilldownResult`. Nothing cached or persisted.

## Success Criteria
- [ ] `POST /api/invoices` with `customer="Beacon & Co"` on `ar_small.xlsx` returns exactly that customer's real data rows (summary/total rows excluded, its negative credit note **included**); `total_count` equals that row count and `subtotal_amount` equals the exact integer-paise sum of that customer's amount rows (`/100`), with `truncated=false`.
- [ ] Adding `employee` narrows the set to the customer-AND-employee intersection; `"(blank)"` as the employee value matches the seeded blank-employee row.
- [ ] Each `InvoiceRow` carries a correct `due_date` (ISO or `null`), `days_overdue` (int or `null`), and `bucket` — the seeded missing-due-date row returns `due_date=null`, `days_overdue=null`, `bucket="unclassified"`.
- [ ] **Full-data / no-sampling gate:** an unfiltered `POST /api/invoices` on `ar_large.xlsx` (≥60,000 rows) returns `len(invoices) == AGENT_DRILLDOWN_MAX_ROWS`, `truncated=true`, `total_count` == the fixture's real-data `row_count`, and `subtotal_amount` == the DashboardResult `total_outstanding` (exact) — proving the capped page never changes the reported totals.
- [ ] In the UI, clicking **Drill down** reveals the inline section (not a modal); typing in the customer picker filters the option list and selecting a customer loads its invoices with the subtotal line; clicking a column header re-sorts the visible rows.
- [ ] Clicking a row in the employee-wise summary opens the drill-down pre-filtered to that employee (employee filter pre-set).
- [ ] The Playwright E2E asserts the drill-down section, a filtered subtotal, at least one invoice row, and the employee-row-click pre-filter after the full upload→map→compute→drill-down journey.
