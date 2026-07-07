# Capability: Print-ready PDF Export

> **Phase 3.** Wires a Phase-1 labelled stub into a real feature.

## What It Does
Produces a print-ready PDF of the dashboard using the browser's native print-to-PDF, driven by a dedicated print stylesheet so the exported page is clean (no nav chrome, charts and tables laid out for paper).

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| current dashboard view | rendered DOM | in-browser | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| PDF | browser-generated PDF | User's chosen save location (native "Save as PDF") |

## External Calls
None — fully client-side (`window.print()`), fully local, no server round-trip, no network.
> **Assumed:** client-side print-to-PDF (print CSS + `window.print()`) rather than a server-side renderer (WeasyPrint/headless Chromium). Rationale: zero extra system dependencies, works offline on any OS including Windows, deterministic, and matches "nothing leaves the machine."

> **Reused headlessly in Phase 5.** The **interactive** export stays client-side as above. The opt-in Phase-5 [scheduled email report](scheduled_email_report.md) — which has no interactive browser — reuses this **same `@media print` stylesheet** (`frontend/src/app/print.css`), driving it headlessly via Playwright's Chromium (`emulateMedia({ media: 'print' })` + `page.pdf()`) to produce the identical light print layout. No conflict: one stylesheet, two triggers (a human clicking Print, or the headless job).

## Business Rules
- A "Print / Save as PDF" button triggers `window.print()`.
- A `@media print` stylesheet hides interactive chrome (upload controls, buttons, stubs), sets page size/margins, and ensures KPI tiles, the Top-20 chart, and the ranked tables render legibly on paper.
- Charts must be visible in print (SVG-based Recharts prints natively; `prefers-reduced-motion`/animation disabled in print).
- The printed header names the source file and the `as_of` date.

## Success Criteria
- [ ] A "Print / Save as PDF" button is present on the dashboard and calls `window.print()`.
- [ ] The print stylesheet hides the upload/mapping controls and stub labels (asserted via the print-media CSS rules / Playwright `emulateMedia({ media: 'print' })`).
- [ ] A Playwright test emulates print media and confirms the KPI values and chart remain in the DOM and visible.
- [ ] `page.pdf()` in the E2E test produces a non-empty PDF for the dashboard.
