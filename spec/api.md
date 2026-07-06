# API

> Local JSON API served by FastAPI on `http://localhost:8001`. No authentication (single-user local tool). Every response uses the skeleton envelope `{"data": ..., "error": null}` via `ok(data)`, or raises `api_error(code, message, status)` which the frontend renders. All routes are stateless — pure functions of their inputs, nothing cached server-side.

---

## API Style

REST, JSON + multipart. New router `src/api/analysis.py` (replaces the skeleton's `src/api/runs.py`, which is deleted). `health.py` is kept. No LLM, no DB.

---

## Endpoints / Commands

### `POST /api/preview` — parse headers & propose mapping *(Phase 1)*

**Purpose:** Read the uploaded `.xlsx`, list sheets/columns, auto-detect the six canonical fields (**preferring a built-in default mapping profile** over fuzzy matching), signal whether the whole file was confidently recognized (`auto_mapped`), and return a 10-row preview and parse-time data-quality flags. Server keeps nothing.

**Request:** `multipart/form-data`
| Part | Type | Required |
|------|------|----------|
| file | `.xlsx` file | yes |
| sheet_name | string | no (defaults to first sheet) |

**Response `data`:**
```json
{
  "sheets": ["Sheet1", "Aging"],
  "sheet_name": "Sheet1",
  "columns": ["Cust Name", "Invoice #", "Inv. Date", "Due Dt", "Balance Outstanding", "Sales Person"],
  "proposed_mapping": [
    {"field": "customer",     "matched_column": "Cust Name",           "confidence": 90, "status": "high"},
    {"field": "invoice_no",   "matched_column": "Invoice #",           "confidence": 88, "status": "high"},
    {"field": "invoice_date", "matched_column": "Inv. Date",           "confidence": 86, "status": "high"},
    {"field": "due_date",     "matched_column": "Due Dt",              "confidence": 72, "status": "low"},
    {"field": "amount",       "matched_column": "Balance Outstanding", "confidence": 91, "status": "high"},
    {"field": "employee",     "matched_column": "Sales Person",        "confidence": 95, "status": "high"},
    {"field": "hod",          "matched_column": "HoD Name",            "confidence": 70, "status": "low"}
  ],
  "preview_rows": [{"Cust Name": "Acme Corp", "Invoice #": "INV-1", "...": "..."}],
  "parse_flags": [{"row_index": 7, "field": "due_date", "reason": "missing", "raw_value": ""}],
  "auto_mapped": false
}
```

> `proposed_mapping` MAY include an optional 7th `hod` (Head-of-Department) entry, auto-detected from headers like "HoD Name"; it is **optional and low-confidence is fine** — it is never one of the six required fields and never blocks Confirm. Omitted when no plausible HoD column is found.

> **`auto_mapped` *(Phase 3.1)*.** `true` only when **all six required fields** are resolved by the **built-in default mapping profile** to **distinct** columns present in the sheet at `status=high`, with no duplicate columns (a purely-fuzzy match, without the profile headers, does **not** trigger auto-skip); the optional `hod` **never** affects it. When `true`, the frontend **skips the mapping-confirmation screen** and goes straight to compute/dashboard (with a dismissible review affordance); when `false`, it shows the confirmation screen as today. Detection **prefers** the default mapping profile: a profile source header present in the sheet (matched exact, case/whitespace-insensitive) pins its field at high confidence over any fuzzy candidate (e.g. `invoice_date` → `Base Line Date` even when other date columns exist). See [capabilities/xlsx_ingestion_and_mapping.md](capabilities/xlsx_ingestion_and_mapping.md) for the profile table and [ui.md](ui.md) for the flow.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Not a `.xlsx` (e.g. `.csv`/`.xls`) — message names the accepted format |
| 400 | Empty / unreadable workbook, or sheet not found |
| 413 | Upload exceeds `AGENT_MAX_UPLOAD_MB` |
| 422 | Row count exceeds `AGENT_MAX_ROWS` |

---

### `POST /api/compute` — compute the dashboard *(Phase 1; extended Phase 2)*

**Purpose:** Apply the confirmed mapping, run the deterministic pipeline over the full sheet, return `DashboardResult`.

**Request:** `multipart/form-data`
| Part | Type | Required |
|------|------|----------|
| file | `.xlsx` file (re-sent) | yes |
| sheet_name | string | no |
| mapping | JSON string — `{customer, invoice_no, invoice_date, due_date, amount, employee}` (all required) → source column names, **plus** an optional `hod` key (nullable/omittable) | yes |

**Response `data` (`DashboardResult`) — Phase 1 fields:**
```json
{
  "source_filename": "ar_export.xlsx",
  "sheet_name": "Sheet1",
  "as_of": "2026-07-04",
  "row_count": 18,
  "total_outstanding": 12345678.90,
  "total_overdue": 5123400.00,
  "pct_overdue": 0.4150,
  "customer_count": 5,
  "worst_bucket": "90+",
  "bucket_totals": {"current": 7222278.90, "b_0_30": 1200000.00, "b_31_60": 900000.00, "b_61_90": 800000.00, "b_90_plus": 2223400.00},
  "top_customers_by_overdue": [
    {"customer": "Beacon & Co", "overdue_amount": 2223400.00, "outstanding_amount": 2223400.00}
  ],
  "data_quality": {"flagged_row_count": 4, "unparseable_row_count": 1, "by_reason": {"missing_due_date": 1, "zero_amount": 1, "negative_amount": 1, "blank_employee": 1}}
}
```

**Phase 2** additionally populates `employees`, `customer_breakdown`, `employee_breakdown`, `risk_flags`, and `data_quality.rows`. Phase-1 responses omit or null these; the frontend shows labelled stubs. Each `EmployeeSummary` in `employees` also carries an optional `hod: string | null` (the Head-of-Department name for that employee; `null` when `hod` is unmapped or blank for that employee).

**Reference date:** `as_of` is `date.today()` unless the server is started with `AGENT_AS_OF` set (a server-level reproducibility override; see [architecture.md](architecture.md) Settings). There is **no per-request `as_of` field** on the API.

**Money on the wire:** ₹ values are JSON numbers already rounded to 2 decimals from exact integer paise (values < 2^53, exact for display). `pct_overdue` is a ratio 0..1. The exactness guarantee is enforced/tested in the backend on integer paise (see [data.md](data.md)).

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Mapping missing a required field, or maps a non-existent column, or maps the same column twice |
| 400 | Not a `.xlsx` / unreadable workbook |
| 422 | A required mapped column cannot be coerced at all (structural) — message names the field |
| 500 | Unexpected compute error — pipeline `error` rendered, never a raw traceback |

> Data-quality issues (bad rows) are **not** errors — they return `200` with the totals plus the flags. Only structural failures error out.

---

### `POST /api/compute/stream` — SSE progress + result *(Phase 3)*

**Purpose:** Same inputs as `/api/compute`; streams `{phase, rows_done, rows_total}` progress events, then a final event carrying the identical `DashboardResult`. Falls back to `/api/compute` if unused. See [large_file_progress.md](capabilities/large_file_progress.md).

### `GET /api/export/xlsx` / `GET /api/export/pdf` *(Phase 3)*

Excel export is generated server-side from the same `DashboardResult` (see [excel_export.md](capabilities/excel_export.md)). PDF is produced client-side via `window.print()` (see [pdf_export.md](capabilities/pdf_export.md)); no server PDF endpoint is required — the `/api/export/pdf` slot is reserved and may be dropped if the client-side approach fully covers it.
> **Assumed:** PDF is client-side only; the server exposes no PDF endpoint.

### `GET /health` *(existing)* — liveness check, unchanged.

---

## Authentication

None. Single-user, localhost-only tool. No login, no tokens, no CORS surface beyond same-origin `/app`.
