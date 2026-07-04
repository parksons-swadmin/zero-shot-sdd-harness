# Capability: XLSX Ingestion & Column Mapping

> **Phase 1.** Part of the primary user journey.

## What It Does
Accepts an uploaded AR aging export (`.xlsx`), parses the chosen sheet, auto-detects the six required fields by fuzzy header matching, and presents a mapping-confirmation step (pre-filled, always reviewable) so the user confirms or corrects the column mapping before any metric is computed — surfacing data-quality issues at parse time and never dropping a row silently.

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
- The mapping-confirmation step is **always shown** and pre-filled; on all-high-confidence the user still reviews once and clicks Confirm. Any `low`/`unmatched` field is highlighted and blocks Confirm until resolved.
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

## Success Criteria
- [ ] Uploading `tests/fixtures/ar_small.xlsx` returns all six fields matched, five with `status=high` and the deliberately-renamed one detected at its documented confidence tier.
- [ ] A file whose headers exactly equal the synonym seeds maps all six at `status=high` with score ≥ 85.
- [ ] A file with an unrecognisable header for one field returns that field as `unmatched`; the compute call is rejected until the user supplies it.
- [ ] Uploading a `.csv` or `.xls` is rejected with a message naming the accepted format.
- [ ] Parse-time flags list exactly the seeded bad rows in `ar_small.xlsx` (missing due date, zero amount, negative amount, blank employee) by row index — none dropped.
- [ ] Unicode customer names (`Müller Traders`, a Devanagari name) round-trip through parse and preview without corruption.
