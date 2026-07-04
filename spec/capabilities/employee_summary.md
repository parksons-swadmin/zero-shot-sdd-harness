# Capability: Employee-wise Summary

> **Phase 2.** Wires a Phase-1 labelled stub into a real feature.

## What It Does
Produces and renders an employee-wise (salesperson) summary table ranked by total outstanding descending, showing each employee's total outstanding, total overdue, and worst aging bucket.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| invoices | normalized rows | ingest node | yes |
| as_of | `date` | injected | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| employees | `list[EmployeeSummary]` | `DashboardResult.employees` → Employee table |

`EmployeeSummary`: `employee`, `total_outstanding`, `total_overdue`, `pct_overdue`, `worst_bucket`, `invoice_count`.

## External Calls
None. Extends the deterministic compute node. No LLM/network/DB.

## Business Rules
- Grouped by `employee`; blank employee grouped under the literal label `"(blank)"` (visible, not dropped).
- Ranked by `total_outstanding` descending; ties broken by `total_overdue` desc, then `employee` asc.
- All monetary aggregation in integer paise (same exactness guarantee as [aging_metrics_engine.md](aging_metrics_engine.md)).
- `worst_bucket` per employee uses the same definition and tie-break as the overall worst bucket.
- The sum of all employees' `total_outstanding` equals the overall `total_outstanding` exactly (partition invariant).

## Success Criteria
- [ ] On `ar_small.xlsx`, the employee table matches the `employees` block of `expected_small.json` exactly, in ranked order.
- [ ] The `"(blank)"` employee row is present for the seeded blank-employee invoice.
- [ ] Sum of per-employee `total_outstanding` equals the overall `total_outstanding` (partition invariant asserted).
- [ ] The table renders in the UI ranked descending by outstanding with each employee's worst bucket shown.
