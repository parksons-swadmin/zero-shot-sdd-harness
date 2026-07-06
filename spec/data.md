# Data Model

> The AR Aging Dashboard is **stateless and holds no persistent data**. There is **no database**. Every model below is an **in-memory / over-the-wire** shape that lives only for the duration of a single request. See [architecture.md](architecture.md) for the "no DB" decision and rationale.

---

## Storage Technology

**None.** No database, no ORM, no migrations. SQLAlchemy, Alembic, and the `src/db/` + `alembic/` directories are **removed** in Phase 1 (nothing is persisted). The uploaded file is parsed into memory, computed, returned, and discarded. No file is written to disk except a short-lived upload temp that is deleted after parse.

Rationale: the product requirement is "stateless, fresh every upload, no memory, no DB persistence." Keeping an unused database would be dead infrastructure (violates the no-gold-plating rule). Consequently the Phase-1 gate has **no `alembic upgrade head` step** (see [roadmap.md](../roadmap.md)).

---

## Statelessness & the two-call flow

There is **no server-side session or cache**. The mapping-confirmation flow is two stateless calls, and the client re-sends the file on the second call:

1. `POST /api/preview` — file in, proposed mapping + preview out. Server keeps nothing.
2. `POST /api/compute` — same file + confirmed mapping in, `DashboardResult` out. Server keeps nothing.

Re-sending the file over loopback (localhost) is negligible for a local desktop tool, and true statelessness is the headline product constraint. See [api.md](api.md).

---

## Entities (in-memory Pydantic models, `src/domain/`)

### Entity: `ColumnMapping`
Confirmed mapping from the six canonical fields to source columns, plus one optional field.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| customer | str | yes | Source column name for customer |
| invoice_no | str | yes | Source column for invoice number |
| invoice_date | str | yes | Source column for invoice date |
| due_date | str | yes | Source column for due date |
| amount | str | yes | Source column for outstanding balance |
| employee | str | yes | Source column for salesperson |
| hod | str \| None = None | no | Source column for HoD Name (Head of Department / salesperson's manager); `None` when unmapped |

### Entity: `FieldMatch` (preview output)
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| field | str | yes | Canonical field name |
| matched_column | str \| null | no | Best-matching source column (null if unmatched) |
| confidence | int (0–100) | yes | rapidfuzz `token_sort_ratio` best score |
| status | enum `high`\|`low`\|`unmatched` | yes | Confidence tier (see ingestion capability) |

### Entity: `Invoice` (normalized row)
One parsed invoice after the mapping is applied.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| row_index | int | yes | 0-based position in the source sheet (for audit) |
| customer | str | yes | `"(blank)"` when source is empty |
| invoice_no | str \| null | no | Retained as text |
| invoice_date | date \| null | no | Parsed; null when unparseable (flagged) |
| due_date | date \| null | no | Parsed; null when unparseable (flagged) |
| amount_paise | int | yes | Amount as exact integer paise (see exactness rule) |
| employee | str | yes | `"(blank)"` when source is empty |
| hod | str \| null | no | Head-of-Department text for the row; `null` when `hod` is unmapped or the source cell is blank |
| dpd | int \| null | no | Days past due at `as_of`; null when due_date null |
| bucket | enum `current`\|`0-30`\|`31-60`\|`61-90`\|`90+`\|`unclassified` | yes | `unclassified` when due_date null |

### Entity: `AgingMetrics` (compute output)
| Field | Type | Phase | Description |
|-------|------|-------|-------------|
| as_of | date | 1 | Reference date used for aging |
| row_count | int | 1 | Total invoice rows processed |
| total_outstanding | number (₹, 2dp) | 1 | Sum of all balances (exact) |
| total_overdue | number (₹, 2dp) | 1 | Sum of overdue balances |
| pct_overdue | float (0..1) | 1 | overdue ÷ outstanding |
| customer_count | int | 1 | Distinct customers |
| worst_bucket | enum bucket \| `none` | 1 | Largest overdue bucket (older wins ties) |
| bucket_totals | `BucketTotals` | 1 | current + four overdue buckets (₹) |
| top_customers_by_overdue | `list[CustomerOverdue]` (≤20) | 1 | Ranked desc by overdue |
| employees | `list[EmployeeSummary]` | 2 | Ranked desc by outstanding |
| customer_breakdown | `list[CustomerBreakdown]` | 2 | Per-customer buckets + weighted-avg-DPD |
| employee_breakdown | `list[EmployeeBreakdown]` | 2 | Per-employee buckets + weighted-avg-DPD |
| risk_flags | `list[RiskFlag]` | 2 | Riskiest accounts |
| data_quality | `DataQualityReport` | 1 (counts) / 2 (full list) | Flagged rows |

> The engine computes `employees`, `customer_breakdown`, and `employee_breakdown` **unconditionally** — they are always populated on every `/api/compute` response (defaulting to empty lists only when a partition is genuinely empty), not phase-gated in the payload. Phase-gating is a **frontend display** concern: the UI shows labelled stubs for these surfaces until the phase that renders them, even though the data is present on the wire.

> **`as_of` reference date:** the served/demo path can pin the reference date via the optional `AGENT_AS_OF` env var for reproducibility (lets the bundled demo fixture reproduce the documented dashboard deterministically). Default is `date.today()`; with the var unset, real files always age to today. See [architecture.md](architecture.md) Settings.

### Value objects
- `BucketTotals`: `current`, `b_0_30`, `b_31_60`, `b_61_90`, `b_90_plus` — each a ₹ number (from exact paise).
- `CustomerOverdue`: `customer`, `overdue_amount`, `outstanding_amount`.
- `EmployeeSummary`: `employee`, `total_outstanding`, `total_overdue`, `pct_overdue`, `worst_bucket`, `invoice_count`, and optional `hod: str | None` = the Head-of-Department for that employee (the most-common non-blank `hod` among that employee's rows; `None` when `hod` is unmapped or all-blank for the employee).
- `CustomerBreakdown` / `EmployeeBreakdown`: `key`, `bucket_totals`, `weighted_avg_days_overdue` (float \| null), `pct_overdue`, `total_outstanding`.
- `RiskFlag`: `customer`, `reason`, `amount`, `bucket`.
- `QualityFlag`: `row_index`, `field`, `reason`, `raw_value`.
- `DataQualityReport`: `flagged_row_count`, `unparseable_row_count`, `by_reason` (`{reason: count}`), `rows` (`list[QualityFlag]`, Phase 2). Excluded embedded subtotal / grand-total rows are **not** a first-class field — their count is carried inside `by_reason` under the key `summary_row_excluded` (present only when > 0; see below).

### Value object: `DashboardResult`
The `POST /api/compute` response payload = `AgingMetrics` plus `source_filename` and `sheet_name`. Single source of truth for the UI and both exports.

### Value objects: `InvoiceRow` / `DrilldownResult` *(Phase 4)*
The `POST /api/invoices` response payload (see [api.md](api.md) and [capabilities/invoice_drilldown.md](capabilities/invoice_drilldown.md)). Both are **projections of the existing normalized `Invoice` rows** for a filter — no new persisted data.
- `InvoiceRow`: `customer` (str), `invoice_no` (str \| null), `amount` (₹ number, 2dp, from `amount_paise`), `due_date` (ISO date \| null), `days_overdue` (int \| null = `Invoice.dpd`), `bucket` (the `Invoice.bucket` enum incl. `unclassified`), `employee` (str, `"(blank)"` when blank).
- `DrilldownResult`: `invoices` (`list[InvoiceRow]`, capped at `AGENT_DRILLDOWN_MAX_ROWS`), `total_count` (int — full filtered-set count), `subtotal_amount` (₹ number, 2dp — exact integer-paise sum over the full filtered set), `truncated` (bool — `total_count > len(invoices)`).

---

## Exactness rule (money)
Every amount → integer paise once: `int(Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)`. All aggregation is integer `int64`. Reported ₹ = `paise / 100` to 2 decimals. This guarantees bit-exact tie-out to the source column regardless of row count/order (see [aging_metrics_engine.md](capabilities/aging_metrics_engine.md)).

---

## Normalization & summary-row exclusion
Before aggregation, normalization **marks and excludes embedded summary / total rows** (subtotal, "Totals", "Grand Total", or all-identity-blank-with-amount rows) so they never inflate the metrics — the detection rule is defined in [xlsx_ingestion_and_mapping.md](capabilities/xlsx_ingestion_and_mapping.md#summary--total-row-detection--exclusion). Excluded rows are **not** materialized as `Invoice` rows for the [metrics engine](capabilities/aging_metrics_engine.md); the engine's "every row" sums therefore operate on real data rows only. This is distinct from flagged rows: genuine data rows (blank employee, negative credit notes, missing invoice_no) are **retained**, never dropped. The count of excluded rows is surfaced transparently on `DataQualityReport.by_reason["summary_row_excluded"]` (an integer count, key present only when > 0; logged in the `metrics.computed`/`node.ingest` events) — never silent. Once excluded, `total_outstanding` ties out exactly to the file's own embedded Totals figure.

## Data Lifecycle
Created on upload (parsed into memory) → **normalized (summary rows excluded)** → computed → returned as JSON / export bytes → **discarded** when the request ends. Nothing is stored, cached, or logged in full (structured logs record counts and timings, never row contents / customer data).

## Sensitive Data
The uploaded AR file contains customer names and balances (commercially sensitive). It **never leaves the machine**: no network egress, no third-party API, no LLM. Logs record aggregate counts/timings only — never customer names, balances, or file contents. The upload temp file is deleted immediately after parse.
