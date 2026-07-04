# Capability: Large-file Progress Feedback

> **Phase 3.** Wires a Phase-1 labelled stub into a real feature.

## What It Does
Shows a progress bar with live row counts during parse and compute for large files, so the user sees real progress instead of a frozen screen on big sheets.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| upload/compute in flight | progress events | server → client | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| progress events | `{ phase, rows_done, rows_total }` | Progress bar UI |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| `GET /api/compute/stream` (SSE) | stream parse/compute progress then final result | Fall back to the plain `POST /api/compute` (no progress bar), still returns the result |

No LLM/network beyond the local API; no DB.

## Business Rules
- Progress reflects **real** work (rows parsed / rows aggregated), never a fake timer — honesty rule from `harness/patterns/ui-ux.md`.
- Emitted in coarse increments (e.g. every 5,000 rows) to avoid event flooding.
- The final SSE event carries the same `DashboardResult` the non-streaming endpoint returns; the two paths are equivalent in output.
- For small files the bar may complete instantly — no artificial delay is added.

## Success Criteria
- [ ] Uploading `ar_large.xlsx` (≥60,000 rows) shows a progress bar advancing with increasing row counts, then the dashboard.
- [ ] The final streamed `DashboardResult` equals the result from the non-streaming `POST /api/compute` for the same file+mapping (identical totals).
- [ ] If the stream endpoint is unavailable, the UI falls back to the non-streaming path and still renders the dashboard.
- [ ] Row counts shown reach the true total (≥60,000), proving no truncation.
