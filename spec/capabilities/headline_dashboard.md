# Capability: Headline Dashboard (KPIs + Top-20 Chart)

> **Phase 1.** The headline user-facing result — the payoff of the primary journey.

## What It Does
Renders the KPI tiles and the Top-20-customers-by-overdue bar chart from the computed metrics, with all monetary values formatted in ₹ INR using Indian lakh/crore digit grouping.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| result | `DashboardResult` (Phase-1 fields) | `POST /api/compute` response | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| KPI tiles | rendered tiles | Dashboard screen |
| Top-20 bar chart | horizontal bar chart (client-side) | Dashboard screen |

KPI tiles (Phase 1):
- **Total outstanding** — ₹, Indian grouping.
- **Total overdue** — ₹, Indian grouping.
- **% overdue** — percentage (1 decimal).
- **Customer count** — integer.
- **Worst aging bucket** — label (`0-30` / `31-60` / `61-90` / `90+` / `none`).

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| `POST /api/compute` | fetch computed metrics | Render error state with the server message and a "start over" action |

No LLM, no network beyond the local API.

## Business Rules
- Every rupee value uses the single Indian lakh/crore grouping formatter defined once in [ui.md](../ui.md) (e.g. `₹1,23,45,678.90`); `pct_overdue` renders as a percentage to one decimal.
- The chart shows up to 20 customers, longest bar on top (descending overdue). Bars are labelled with the customer name; the value tooltip shows overdue and outstanding in ₹.
- **No dual representation:** each value appears once — the KPI number is not repeated in the chart, and the chart value is not also printed as a KPI.
- All four view states exist: empty (before upload — the dashboard is not shown), loading (during compute, with a labelled indicator), error (server/compute failure), populated (the ideal case).
- Later-phase surfaces (employee summary, aging breakdown, weighted-avg-days-overdue, risk-flags panel, export buttons, progress bar) appear as **clearly-labelled non-functional stubs** ("Coming in Phase 2/3") so the user sees the vision without mistaking a stub for a bug.

## Success Criteria
- [ ] After uploading `ar_small.xlsx` and confirming the mapping, the five KPI tiles show the exact values from `expected_small.json`, formatted with Indian grouping (e.g. a crore-scale value renders `₹#,##,##,###.##`).
- [ ] The Top-20 chart renders one bar per customer with overdue balance, ordered descending, with the deepest-90+ customer at or near the top.
- [ ] A customer with zero overdue does not appear in the Top-20 chart (or shows a zero-length bar), consistent with its `overdue_amount = 0`.
- [ ] The Playwright smoke asserts the headline KPI value text and at least one chart bar are present and non-empty after the full upload→map→compute journey.
- [ ] Stub sections are visibly labelled as forthcoming and are not interactive in a way that looks broken.
