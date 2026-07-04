# Capability: Group Aging Breakdown & Weighted-Average Days Overdue

> **Phase 2.** Wires a Phase-1 labelled stub into a real feature.

## What It Does
Produces and renders the aging-bucket breakdown (0-30 / 31-60 / 61-90 / 90+, plus current) overall and per group (customer, employee), and the amount-weighted average days-overdue per customer and per employee — all surfaced in the UI.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| invoices | normalized rows with per-row DPD + bucket | compute node | yes |
| as_of | `date` | injected | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| overall_breakdown | `bucket_totals` (current + four buckets) | Aging breakdown chart (stacked/segmented) |
| customer_breakdown | `list[CustomerBreakdown]` | Per-customer aging table |
| employee_breakdown | `list[EmployeeBreakdown]` | Per-employee aging table |
| weighted_avg_dpd | per customer and per employee | breakdown tables + tooltip |

`CustomerBreakdown` / `EmployeeBreakdown`: `key`, `bucket_totals`, `weighted_avg_days_overdue`, `pct_overdue`, `total_outstanding`.

## External Calls
None. Extends the deterministic compute node. No LLM/network/DB.

## Business Rules — Exact Definitions (assert verbatim)
- **Weighted-average days overdue** for a group = amount-weighted mean of days-past-due over that group's **overdue** invoices only:
  `wavg = sum(amount_paise_i * dpd_i for overdue i) / sum(amount_paise_i for overdue i)`.
  - When a group has no overdue balance, `weighted_avg_days_overdue = null` (rendered `—`), never `0`-as-if-computed and never a divide-by-zero.
  - `dpd_i` uses the same definition as [aging_metrics_engine.md](aging_metrics_engine.md).
- **% overdue** per group = group overdue ÷ group outstanding (same definition as overall).
- Per-group bucket totals sum (across groups) to the overall bucket totals exactly (partition invariant), and each group's five bucket amounts sum to that group's outstanding.
- Blank customer/employee grouped under `"(blank)"`.

## Success Criteria
- [ ] Overall `bucket_totals` on `ar_small.xlsx` equals `expected_small.json` (current + four buckets sum to `total_outstanding`).
- [ ] Per-customer weighted-average days overdue matches the hand-authored oracle for at least three customers, including the deep-90+ customer and a customer with mixed buckets.
- [ ] A customer with only current invoices returns `weighted_avg_days_overdue = null` and renders `—`.
- [ ] Sum of per-customer bucket totals equals the overall bucket totals (partition invariant asserted).
- [ ] The aging breakdown and weighted-avg columns render in the UI.
