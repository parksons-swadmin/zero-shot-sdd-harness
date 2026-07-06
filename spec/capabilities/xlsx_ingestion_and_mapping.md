# Capability: XLSX Ingestion & Column Mapping

> **Phase 1.** Part of the primary user journey.

## What It Does
Accepts an uploaded AR aging export (`.xlsx`), parses the chosen sheet, auto-detects the six required fields — **preferring a built-in default mapping profile** over fuzzy header matching — and, when the columns are not confidently recognized, presents a mapping-confirmation step (pre-filled, reviewable) so the user confirms or corrects the column mapping before any metric is computed. When all six required fields resolve confidently (`auto_mapped`), the confirmation step is **skipped** and the user goes straight to the dashboard with a review affordance. Surfaces data-quality issues at parse time and never drops a row silently.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | `.xlsx` upload (multipart) | User (browser file picker / drag-drop) | yes |
| sheet_name | string | User (defaults to first sheet) | no |
| mapping | `{canonical_field: source_column}` | User (confirm/correct step) | yes for compute |

The six **canonical fields** every AR file must map to:

| Canonical field | Meaning | Synonym seeds (fuzzy-match anchors) |
|-----------------|---------|-------------------------------------|
| `customer` | Customer name or code | customer, cust, party, account name, client, buyer, name |
| `invoice_no` | Invoice number | invoice no, invoice #, inv no, bill no, document no, voucher |
| `invoice_date` | Invoice date | invoice date, inv date, bill date, doc date, date |
| `due_date` | Payment due date | due date, due dt, maturity date, net due, payable by |
| `amount` | Outstanding balance for the row | amount, balance, outstanding, amt, net amount, due amount, pending |
| `employee` | Salesperson / responsible employee | employee, salesperson, sales person, executive, rep, owner, marketing person |

> **Optional 7th field — `hod` (HoD Name = Head of Department, the salesperson's manager).** Auto-detected by the same fuzzy match against synonym seeds (`hod`, `head of department`, `department head`, `reporting manager`). (The bare `hod name` seed is intentionally excluded: its `name` token false-matches `Payer Name` / `Cust Name`; real HoD headers still match strongly via the seeds above.) It is **strictly optional**: it is confirmable/correctable on the mapping screen, low-confidence is fine, and it **never blocks Compute** whether matched, unmatched, or left unmapped. It is **NOT** one of the six required canonical fields — the six above remain required and unchanged. When present it is carried through normalization and surfaced on the employee summary (see [employee_summary.md](employee_summary.md)); when absent everything works exactly as before.

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| sheets | `list[str]` | Preview response → UI sheet picker |
| columns | `list[str]` | Preview response → mapping dropdowns |
| proposed_mapping | `list[FieldMatch]` (field, matched column, confidence 0–100, status) | Preview response → pre-filled mapping form |
| preview_rows | first 10 rows as `list[dict]` | Preview response → sample table |
| parse_flags | `list[QualityFlag]` (parse-time issues) | Preview response → inline warnings |

`FieldMatch.status` is one of:
- `high` — score ≥ `AGENT_HEADER_MATCH_THRESHOLD` (default 85) → auto-selected, green.
- `low` — 60 ≤ score < threshold → auto-selected but flagged amber ("please confirm").
- `unmatched` — score < 60 → nothing selected, user must pick.

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem (upload temp) | read uploaded bytes | Reject with clear error; no partial parse |
| openpyxl / pandas | read `.xlsx` workbook | Reject with "could not read workbook" + reason |

No network, no LLM, no database. See [architecture.md](../architecture.md).

## Business Rules
- **`.xlsx` only** for this build. `.xls`, `.csv`, `.pdf` are rejected with a clear message (deferred, not silently mis-parsed).
- Fuzzy matching uses `rapidfuzz` `token_sort_ratio` of each source header against each field's synonym seeds; best score per field wins. Threshold is configurable via `AGENT_HEADER_MATCH_THRESHOLD`.
- The mapping-confirmation step is shown and pre-filled **whenever the columns are not confidently recognized** (`auto_mapped=false`); on confident all-high recognition (`auto_mapped=true`) it is **skipped** in favour of a direct-to-dashboard flow with a review affordance (see the default-profile section below and [ui.md](../ui.md)). When shown, any `low`/`unmatched` field is highlighted and blocks Confirm until resolved. This refines the earlier "always ask to map" rule to "only ask when the columns aren't confidently recognized."
- The same source column may not be mapped to two canonical fields; the UI prevents duplicate selection.
- **No row is ever dropped silently.** Rows with parse problems are retained, flagged, and their count surfaced. Compute still runs; flagged rows are handled per the rules in [aging_metrics_engine.md](aging_metrics_engine.md).
- **Data-quality flags raised at parse/map time** (see [QualityFlag in data.md](../data.md)):
  - missing or unparseable `due_date`
  - missing or unparseable `invoice_date`
  - negative or zero `amount`
  - non-numeric `amount`
  - blank `employee`
  - blank `customer`
- Date parsing uses `dayfirst=True` (Indian dd/mm/yyyy convention) and also accepts native Excel date cells, Excel serial numbers, and ISO `yyyy-mm-dd` strings.
  > **Assumed:** `dayfirst=True` — Indian AR exports use dd/mm/yyyy. Ambiguous values (day ≤ 12) are parsed day-first; unparseable values are flagged, never guessed.
- Upload size is capped at `AGENT_MAX_UPLOAD_MB` (default 25) and row count at `AGENT_MAX_ROWS` (default 200000); exceeding either returns a clear error.

## Default mapping profile & auto-skip *(Phase 3.1 enhancement — see [roadmap.md](../roadmap.md))*
Recurring standard ERP/SAP exports use the same headers every period, so re-confirming the mapping on every upload is friction. Detection therefore ships with a **built-in default mapping profile** — a canonical-field → exact-expected-source-header table for the common export — and **auto-skips** the confirmation step when the whole file is confidently recognized.

> **Stateless — this is a built-in PRESET, not saved/persisted state.** The profile is a constant compiled into the app; nothing is written to disk, no database, no per-user learning, no "remember this mapping". Every upload is evaluated fresh against the same constant profile. Consistent with the no-persistence constraint in [roadmap.md](../roadmap.md).

**Default mapping profile (canonical field → exact expected source header):**

| Canonical field | Expected source header |
|-----------------|------------------------|
| `customer` | `Payer Name` |
| `invoice_no` | `Invoice No.` |
| `invoice_date` | `Base Line Date` |
| `due_date` | `Due Date` |
| `amount` | `Amount Due` |
| `employee` | `Current Employee` |
| `hod` *(optional)* | `HoD Name` |

**Detection prefers the profile.** For each field, if its profile source header is present in the uploaded sheet — matched **exact but case- and whitespace-insensitive** (trim + collapse internal whitespace + case-fold; no fuzzy scoring) — that field is pinned to that column at `status=high` (confidence 100). This **takes precedence over fuzzy matching** and over any other column a fuzzy match might otherwise prefer. That precedence is what makes `invoice_date` → `Base Line Date` deterministic even when the sheet carries several date-like columns (`Due Date`, `Base Line Date`, a posting date, …) that fuzzy matching alone could confuse. Fields whose profile header is absent fall back to the existing fuzzy match (synonym seeds + threshold) exactly as before.

**Auto-skip decision (`auto_mapped`).** The `POST /api/preview` response carries a boolean `auto_mapped` (see [api.md](../api.md)). It is `true` when **all six required fields** (`customer`, `invoice_no`, `invoice_date`, `due_date`, `amount`, `employee`) are each resolved by the **built-in default mapping profile** to a **distinct** column present in the sheet at `status=high`, with **no two required fields sharing a column**. A purely-fuzzy match (a sheet without the profile's exact headers) does **not** trigger auto-skip — the confirmation screen is shown. It is `false` if any required field is `low`/`unmatched`, or if any two required fields would collide on the same column. The optional `hod` field **never affects `auto_mapped`** — its presence, absence, or confidence is irrelevant to the decision.

**Fallback.** When `auto_mapped=false` (unrecognized/changed columns, a low/unmatched field, or a duplicate collision) behavior is unchanged from Phase 1: the mapping-confirmation screen is shown, pre-filled with the best proposal (profile-preferred where applicable, else fuzzy), and the user confirms/corrects before compute. The default profile only ever *adds* confidence and *skips a step*; it never blocks the user or forces a mapping they cannot override (the review affordance re-opens the pre-filled mapping — see [ui.md](../ui.md)).

## Summary / total-row detection & exclusion
Real ERP/SAP AR exports routinely embed subtotal / grand-total rows inside the sheet — a row whose customer or employee cell reads "Totals" or "Grand Total", or where all identity columns are blank but an aggregate amount is present. These are **not data rows**: summing them into the metrics double- or triple-counts the balance (a real file showed **3.00×** Total Outstanding because it carried TWO embedded "Totals" rows). Normalization therefore **detects and excludes** them before any aggregation, so the `invoices` handed to the [aging metrics engine](aging_metrics_engine.md) contain real data rows only.

A normalized row is classified as a **SUMMARY/TOTAL row** — and excluded from **ALL** metrics (totals, % overdue, buckets, `customer_count`, Top-20, and every employee/customer aggregate) — when **EITHER**:
- (a) its mapped `customer` **OR** `employee` text matches `/^\s*(grand\s+)?totals?\s*$/i`, or contains the phrase "grand total" (case-insensitive); **OR**
- (b) its mapped `customer`, `due_date`, **AND** `invoice_no` are **all** blank while a numeric `amount` is present.

**This is DISTINCT from "dropping data rows."** Real data rows are still **never dropped** (see the "No row is ever dropped silently" rule above and the flagged-row handling in [aging_metrics_engine.md](aging_metrics_engine.md)). Only detected aggregate/summary rows are removed from the computation set, and the excluded **count is surfaced transparently** — carried on the data-quality report as `by_reason["summary_row_excluded"]` (an integer count, key present only when > 0; see [data.md](../data.md)) and logged in the `metrics.computed`/`node.ingest` events. It is **never silent**. A visible dashboard note (e.g. "N summary/total rows detected and excluded") is a **Phase-2 frontend enhancement**; in Phase 1 the count is surfaced in the API response (`by_reason`) and server logs only.

**Guardrails — the following must NOT be excluded (they are genuine data):**
- a row with a **blank `employee`** but a real `customer` **and** `due_date` (an unassigned invoice — netted in normally, blank employee grouped under `"(blank)"`);
- a **negative credit-note row with full identity** (`customer` + `invoice_no` + `due_date`) — netted in, never dropped, consistent with the negative-amount rule in the metrics engine;
- a row **missing only `invoice_no`** but having `customer` **and** `due_date`.

**Tie-out.** Once summary rows are excluded, `total_outstanding` ties out **exactly** to the file's own embedded "Totals" figure — the real file above drops from 3.00× back to 1.00× (a bit-exact match to its printed grand total).

## Success Criteria
- [ ] Uploading `tests/fixtures/ar_small.xlsx` returns all six fields matched, five with `status=high` and the deliberately-renamed one detected at its documented confidence tier.
- [ ] A file whose headers exactly equal the synonym seeds maps all six at `status=high` with score ≥ 85.
- [ ] A file with an unrecognisable header for one field returns that field as `unmatched`; the compute call is rejected until the user supplies it.
- [ ] Uploading a `.csv` or `.xls` is rejected with a message naming the accepted format.
- [ ] Parse-time flags list exactly the seeded bad rows in `ar_small.xlsx` (missing due date, zero amount, negative amount, blank employee) by row index — none dropped.
- [ ] Unicode customer names (`Müller Traders`, a Devanagari name) round-trip through parse and preview without corruption.
- [ ] A file carrying TWO embedded "Totals" rows (customer cell = `Totals`) yields `total_outstanding` equal to the file's own single printed Totals figure, and `data_quality.by_reason["summary_row_excluded"] == 2` — matching the observed 3.00× → 1.00× correction.
- [ ] A row whose employee cell reads `Grand Total`, and a row with blank `customer`+`due_date`+`invoice_no` but a numeric amount, are both excluded (counted in `by_reason["summary_row_excluded"]`); a blank-`employee`-but-real-`customer`+`due_date` row and a full-identity negative credit-note row are both **retained** and counted in `total_outstanding`.

**Default mapping profile & auto-skip *(Phase 3.1)*:**
- [ ] A file with the exact standard headers (`Payer Name`, `Invoice No.`, `Base Line Date`, `Due Date`, `Amount Due`, `Current Employee`) returns all six required fields at `status=high` mapped via the default profile, and `auto_mapped=true`.
- [ ] **Profile precedence:** given a sheet containing both `Base Line Date` and another date column (e.g. `Due Date`, a posting date), `invoice_date` maps to `Base Line Date` (not the other date column) — confirming profile beats fuzzy.
- [ ] **Case/whitespace-insensitive profile match:** headers `payer name` and `  Amount Due ` still map via the profile at `status=high`.
- [ ] **`hod` does not affect `auto_mapped`:** a file with all six required fields high but NO `HoD Name` column still returns `auto_mapped=true`.
- [ ] A file with one unrecognized required header (neither profile nor fuzzy matches it at high) returns `auto_mapped=false`, and the mapping-confirmation flow is required as in Phase 1.
- [ ] **Duplicate collision:** if two required fields would resolve to the same column, `auto_mapped=false`.
