# Capabilities Index

> One file per capability. Each describes exactly one discrete thing the AR Aging Dashboard does. Phase tags map each capability to its build phase (see [roadmap.md](../roadmap.md)).

---

## What Is a Capability?

A single, discrete behaviour of the dashboard — e.g. "compute the exact aging metrics", "render the Top-20 overdue chart", "export a multi-sheet Excel".

## Capabilities in This Project

| Capability | Phase | File |
|-----------|-------|------|
| XLSX Ingestion & Column Mapping | 1 (+3.1: default profile + auto-skip) | [xlsx_ingestion_and_mapping.md](xlsx_ingestion_and_mapping.md) |
| Aging Metrics Engine (exact, deterministic) | 1 | [aging_metrics_engine.md](aging_metrics_engine.md) |
| Headline Dashboard (KPIs + Top-20 chart) | 1 | [headline_dashboard.md](headline_dashboard.md) |
| Employee-wise Summary | 2 | [employee_summary.md](employee_summary.md) |
| Group Aging Breakdown & Weighted-Avg Days Overdue | 2 | [group_aging_breakdown.md](group_aging_breakdown.md) |
| Proactive Flags (rule-based) | 2 | [proactive_flags.md](proactive_flags.md) |
| Excel Export (multi-sheet .xlsx) | 3 | [excel_export.md](excel_export.md) |
| Print-ready PDF Export | 3 | [pdf_export.md](pdf_export.md) |
| Large-file Progress Feedback | 3 | [large_file_progress.md](large_file_progress.md) |
| Invoice Drill-down (row-level view + filters) | 4 | [invoice_drilldown.md](invoice_drilldown.md) |

## Explicitly NOT a Capability (out of scope)

- **DSO (Days Sales Outstanding)** — no sales/turnover column exists in the input; it is never computed, faked, or added as a future capability. See [roadmap.md](../roadmap.md).
- **`.xls` / `.csv` / `.pdf` ingestion** — this build accepts `.xlsx` only.
- **Persistence / history / multi-file / login / auto-watch** — the tool is stateless, one file at a time.
- **Any LLM / AI-generated commentary** — every number is deterministic pandas arithmetic.

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer creates a new `<name>.md`, updates this index, flags dependencies, and self-reviews before returning.
