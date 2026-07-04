# UI

> Local browser dashboard at `http://localhost:8001/app/` (Next.js 15 static export served by FastAPI). Replaces the skeleton's transform form in `frontend/src/app/page.tsx`. All four view states (empty, loading, error, populated) are designed per `harness/patterns/ui-ux.md`. Every rupee value uses Indian lakh/crore grouping.

---

## UI Type

Web dashboard (single-page flow): **Upload → Mapping-confirm → Dashboard**. No login, no navigation menu — one focused flow.

---

## INR formatting rule (global)

Every monetary value renders via `Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })` → e.g. `₹1,23,45,678.90` (lakh/crore digit grouping). `pct_overdue` renders as a percentage with one decimal (`41.5%`). One shared formatter utility; used everywhere.

---

## Views / Screens

### Screen: Upload *(Phase 1 — real)*
**Purpose:** the user selects the AR aging `.xlsx`.
**Key elements:** drag-and-drop zone + file picker button; accepted-format note ("`.xlsx` only"); size limit note.
**Actions:** choose file → auto-calls `POST /api/preview`.
**States:** empty (guidance: "Upload your AR aging export to begin"); loading ("Reading workbook…"); error (wrong format / too large / unreadable — human message + retry).

### Screen: Mapping Confirmation *(Phase 1 — real)*
**Purpose:** the user confirms/corrects the six-field mapping before compute (the human-in-the-loop checkpoint).
**Key elements:**
- One row per canonical field (customer, invoice_no, invoice_date, due_date, amount, employee) with a dropdown of source columns, pre-selected to the detected match.
- Confidence badge per field: green check (`high`), amber "please confirm" (`low`), red "select a column" (`unmatched`).
- A 10-row preview table of the raw sheet.
- Inline parse-time data-quality warnings (e.g. "1 row has a missing due date").
- Sheet picker if the workbook has multiple sheets.
**Actions:** correct any dropdown; **Confirm & Compute** (disabled until all six fields are mapped and no duplicate column is selected) → `POST /api/compute`.
**States:** populated (pre-filled mapping); low-confidence highlighted; error (compute failure).

### Screen: Dashboard *(Phase 1 real for the headline; later surfaces are labelled stubs)*
**Purpose:** show the computed AR aging picture.

**Phase 1 — REAL:**
- **KPI tiles:** Total outstanding · Total overdue · % overdue · Customer count · Worst aging bucket.
- **Top-20 customers by overdue** — horizontal bar chart (Recharts), descending, ₹ tooltips. *The headline.*
- Source filename + `as_of` date + row count header.

**Phase 1 — LABELLED NON-FUNCTIONAL STUBS** (visible so the user sees the vision; each clearly tagged "Coming in Phase 2/3", not interactive in a way that looks broken):
- Employee-wise summary table *(Phase 2)*
- Aging-bucket breakdown chart + weighted-avg-days-overdue *(Phase 2)*
- Risk-flags + data-quality panel *(Phase 2)*
- Export buttons: "Export Excel", "Print / Save as PDF" *(Phase 3)*
- Large-file progress bar *(Phase 3)*

**Phase 2 wires in:** employee table (ranked desc by outstanding), aging breakdown + weighted-avg columns, risk-flags panel with the audit list of flagged/unparseable rows.
**Phase 3 wires in:** working Excel export, working print-to-PDF, live progress bar for large files.

**States:** empty (before compute — dashboard hidden); loading ("Computing metrics…", real work); error (server/compute error with message + "Start over"); populated (ideal).

---

## Error States

- Wrong file type / oversized / unreadable workbook → human message naming the fix, retry button. Never a raw traceback.
- Incomplete mapping → Confirm button disabled with inline reason ("Map all six fields to continue").
- Compute error → error card with the server message + "Start over" (re-upload). Follows the "render an error state, never surface a raw HTTPException" rule from `harness/patterns/code.md`.
- Empty/zero-data file → dashboard renders with zeroes and an explicit "no outstanding balances found" note, not a broken layout.

## Accessibility & quality
- Real `<button>`/`<label>`/`<table>` semantics; keyboard-reachable with visible focus; WCAG-AA contrast; responsive (survives narrow and wide windows, no horizontal scroll on the primary flow); `prefers-reduced-motion` respected (and animation disabled under print media). Stub sections are labelled with plain copy, never lorem ipsum.

## Tech Stack
Next.js 15 + React 19 + Tailwind v4 (static export, `basePath: '/app'`), Recharts for charts. Playwright for E2E (`frontend/tests/e2e/`). See [architecture.md](architecture.md) `## Stack`.
