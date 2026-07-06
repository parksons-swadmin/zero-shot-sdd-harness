# Capability: Excel Export (Multi-sheet .xlsx)

> **Phase 3.** Wires a Phase-1 labelled stub into a real feature.

## What It Does
Generates a downloadable multi-sheet `.xlsx` workbook containing the ranked tables and summary from the current dashboard, with numbers that tie out exactly to the on-screen figures.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file + mapping | same `.xlsx` + confirmed mapping | re-posted by the client (stateless) | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| workbook | `.xlsx` bytes (multi-sheet) | Browser download (`Content-Disposition: attachment`) |

Sheets: **Summary** (KPIs + overall buckets), **Customers** (Top ranked by overdue, with bucket columns + weighted-avg-DPD), **Employees** (ranked by outstanding), **Flagged Rows** (audit list of every flagged/unparseable row).

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| openpyxl (write engine) | build workbook in memory | Return a clear error; no partial file |

No LLM/network/DB.

## Business Rules
- Built server-side from the **same computed `AgingMetrics`** the dashboard renders — the export cannot diverge from the screen.
- Monetary cells written as numbers with an INR-style number format; the underlying value equals `paise / 100` (exact).
- Currency and grouping preserved via cell number format `"₹"#,##,##,##0.00` (Indian grouping).
- Filename includes the source name and the `as_of` date.

## Success Criteria
- [ ] The exported workbook opens and contains the four named sheets.
- [ ] The Summary sheet's total outstanding/overdue equal the API `AgingMetrics` values exactly (read back with openpyxl in the test).
- [ ] The Customers sheet row order matches the Top-ranked-by-overdue order from the API.
- [ ] The Flagged Rows sheet contains exactly the flagged rows (count matches the data-quality report).
