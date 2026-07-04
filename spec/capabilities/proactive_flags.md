# Capability: Proactive Flags (Rule-based, Deterministic)

> **Phase 2.** Wires a Phase-1 labelled stub into a real feature. **No LLM** — pure rules.

## What It Does
Auto-highlights the riskiest accounts and surfaces all data-quality issues in a dedicated panel with an audit list of every flagged / unparseable row, so nothing is hidden and nothing is dropped.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| invoices | normalized rows with DPD + bucket | compute node | yes |
| quality_flags | `list[QualityFlag]` | validate node | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| risk_flags | `list[RiskFlag]` | Risk panel |
| data_quality_report | `list[QualityFlag]` grouped by reason + counts | Data-quality panel + audit list |

`RiskFlag`: `customer`, `reason`, `amount`, `bucket`. `QualityFlag`: `row_index`, `field`, `reason`, `raw_value`.

## External Calls
None. Deterministic rules only. No LLM/network/DB.

## Business Rules
- **Riskiest accounts** = customers ranked by total `90+` overdue amount, descending; top N (`AGENT_RISK_TOP_N`, default 5) surfaced with reason `"largest 90+ overdue"`. Only customers with a non-zero `90+` balance qualify.
- **Data-quality issues** surfaced (from parse/validate flags): missing/invalid due date, missing/invalid invoice date, negative amount, zero amount, non-numeric amount, blank employee, blank customer.
- Every flagged / unparseable row is listed in the audit list with its **original row index** and raw value — **never dropped silently**. The panel shows counts per reason and lets the user see the offending rows.
- Flags are advisory: they do not alter the computed totals (which include flagged rows per the tie-out rules in [aging_metrics_engine.md](aging_metrics_engine.md)).

## Success Criteria
- [ ] On `ar_small.xlsx`, the riskiest-accounts list ranks the deep-90+ customer first with reason `"largest 90+ overdue"`.
- [ ] The data-quality panel lists exactly the seeded bad rows (missing due date, zero amount, negative amount, blank employee) by original row index and reason — count matches the seeded count.
- [ ] A file with no data-quality issues shows an explicit "no issues found" empty state, not a blank panel.
- [ ] Flags do not change `total_outstanding` (asserted equal to the engine total with and without the flags computed).
