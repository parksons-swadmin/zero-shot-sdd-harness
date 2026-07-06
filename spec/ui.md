# UI

> Local browser dashboard at `http://localhost:8001/app/` (Next.js 15 static export served by FastAPI). Replaces the skeleton's transform form in `frontend/src/app/page.tsx`. All four view states (empty, loading, error, populated) are designed per `harness/patterns/ui-ux.md`. Every rupee value uses Indian lakh/crore grouping.

---

## UI Type

Web dashboard (single-page flow): **Upload → Mapping-confirm → Dashboard**, where **Mapping-confirm is auto-skipped** when the columns are confidently recognized (see the Auto-skip flow below). No login, no navigation menu — one focused flow, with a minimal top **header** carrying the product title and a light/dark **theme toggle** *(Phase 3.2 — see the Theme section below)*.

---

## INR formatting rule (global)

Every monetary value renders via `Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })` → e.g. `₹1,23,45,678.90` (lakh/crore digit grouping). `pct_overdue` renders as a percentage with one decimal (`41.5%`). One shared formatter utility; used everywhere.

---

## Theme (light / dark) — global *(Phase 3.2 — see [roadmap.md](roadmap.md))*

A **theme toggle** in the app header switches light ↔ dark. On first load the theme follows the OS/browser preference (`prefers-color-scheme`); once the user picks a mode explicitly, that choice is remembered in `localStorage` and re-applied on the next visit. This `localStorage` theme flag is the **only** client-side persistence in the app — it is a UI preference that holds **no AR / business data**, so it does **not** violate the stateless / no-DB constraint. All screens, KPI tiles, charts (Recharts) and tables must be legible with WCAG-AA contrast in **both** themes. The **print / PDF layout always renders in the light style** regardless of the active theme (see the Phase-3 print stylesheet).

---

## Views / Screens

### Screen: Upload *(Phase 1 — real)*
**Purpose:** the user selects the AR aging `.xlsx`.
**Key elements:** drag-and-drop zone + file picker button; accepted-format note ("`.xlsx` only"); size limit note.
**Actions:** choose file → auto-calls `POST /api/preview`.
**States:** empty (guidance: "Upload your AR aging export to begin"); loading ("Reading workbook…"); error (wrong format / too large / unreadable — human message + retry).

### Screen: Mapping Confirmation *(Phase 1 — real)*
**Purpose:** the user confirms/corrects the six-field mapping before compute (the human-in-the-loop checkpoint).
**When shown:** whenever the preview response returns `auto_mapped=false` (columns not confidently recognized, a low/unmatched field, or a duplicate collision). When `auto_mapped=true` this screen is **skipped** and the app goes straight to compute → Dashboard (see the Auto-skip flow below). *(Auto-skip is a Phase 3.1 enhancement; in earlier phases this screen is always shown.)*
**Key elements:**
- One row per canonical field (customer, invoice_no, invoice_date, due_date, amount, employee) with a dropdown of source columns, pre-selected to the detected match.
- Confidence badge per field: green check (`high`), amber "please confirm" (`low`), red "select a column" (`unmatched`).
- A 10-row preview table of the raw sheet.
- Inline parse-time data-quality warnings (e.g. "1 row has a missing due date").
- Sheet picker if the workbook has multiple sheets.
**Actions:** correct any dropdown; **Confirm & Compute** (disabled until all six fields are mapped and no duplicate column is selected) → `POST /api/compute`.
**States:** populated (pre-filled mapping); low-confidence highlighted; error (compute failure).

### Flow: Auto-skip mapping *(Phase 3.1 enhancement — see [roadmap.md](roadmap.md))*
When `POST /api/preview` returns `auto_mapped=true` (all six required fields resolved by the built-in default mapping profile as distinct high-confidence columns; see [api.md](api.md) and [capabilities/xlsx_ingestion_and_mapping.md](capabilities/xlsx_ingestion_and_mapping.md)), the app **skips the Mapping Confirmation screen entirely** and proceeds straight to compute → Dashboard. On the Dashboard it shows a **dismissible review affordance**: a compact, non-blocking banner reading **"Columns auto-mapped from your standard format — Review / change mapping"** whose **Review / change mapping** action reopens the (pre-filled) Mapping Confirmation screen so the user can override and re-compute. Dismissing the banner hides it for the session; it is informational, never an error.
When `auto_mapped=false`, nothing changes: the Mapping Confirmation screen is shown as today. **Stateless** — no preference is stored; the decision is recomputed on every upload.

### Screen: Dashboard *(Phase 1 real for the headline; later surfaces are labelled stubs)*
**Purpose:** show the computed AR aging picture.

**Phase 1 — REAL:**
- **KPI tiles:** Total outstanding · Total overdue · % overdue · Customer count · Worst aging bucket.
- **Top-20 customers by overdue** — horizontal bar chart (Recharts), descending, ₹ tooltips. *The headline.*
- Source filename + `as_of` date + row count header.
- *(Phase 3.1)* When mapping was auto-skipped, a dismissible "Columns auto-mapped from your standard format — Review / change mapping" banner (see the Auto-skip flow above).

**Phase 1 — LABELLED NON-FUNCTIONAL STUBS** (visible so the user sees the vision; each clearly tagged "Coming in Phase 2/3", not interactive in a way that looks broken):
- Employee-wise summary table *(Phase 2)*
- Aging-bucket breakdown chart + weighted-avg-days-overdue *(Phase 2)*
- Risk-flags + data-quality panel *(Phase 2)*
- Export buttons: "Export Excel", "Print / Save as PDF" *(Phase 3)*
- Large-file progress bar *(Phase 3)*

**Phase 2 wires in:** employee table (ranked desc by outstanding), aging breakdown + weighted-avg columns, and the risk-flags + data-quality panel (audit list of flagged/unparseable rows).
**Phase 3 wires in:** working Excel export, working print-to-PDF, live progress bar for large files.
**Phase 3.2 refines:** the **risk-flags** (riskiest 90+ accounts) stay **inline** on the dashboard, but the detailed **data-quality audit** (the per-row flagged-rows table + the by-reason breakdown — the technical "which rows are messy" view) is **no longer shown inline**; a **"Data-quality audit" button** opens it on demand in a modal/drawer, framed as an admin / spot-check view. The small **"N summary/total rows excluded"** tie-out note stays **visible inline** (it explains the totals). See [roadmap.md](roadmap.md) Phase 3.2.

**Phase 4 wires in:** the **Invoice drill-down** — a **"Drill down" button** on the dashboard reveals an inline drill-down **section** (not a modal) with a searchable customer picker, an employee filter, a sortable per-invoice table and a filtered subtotal; **clicking an employee row** in the employee-wise summary opens the same section pre-filtered to that employee. See the dedicated section below and [capabilities/invoice_drilldown.md](capabilities/invoice_drilldown.md).

**States:** empty (before compute — dashboard hidden); loading ("Computing metrics…", real work); error (server/compute error with message + "Start over"); populated (ideal).

### Section: Invoice Drill-down *(Phase 4 — see [roadmap.md](roadmap.md))*
**Purpose:** inspect the individual invoices behind the aggregates.
**Entry points:** (a) a **"Drill down" button** on the dashboard toggles an **inline section** (not a modal) directly below the dashboard; (b) **clicking a row** in the employee-wise summary table opens the same section with the **employee filter pre-set** to that employee (and scrolls it into view).
**Key elements:**
- **Searchable customer picker** — type-to-search combobox over the full distinct customer list (sourced client-side from `DashboardResult.customer_breakdown[].key`; handles 1,000+ customers with client-side filtering). Clearable ("All customers").
- **Employee filter** — dropdown over `DashboardResult.employees[].employee` (incl. `"(blank)"`). Clearable ("All employees"). Filters combine (customer **AND** employee).
- **Filtered subtotal line** — e.g. `Beacon & Co — 12 invoices · ₹37,50,000` — the invoice count + total amount due for the **current filter**, computed over the full filtered set (from `total_count` / `subtotal_amount`), formatted with Indian grouping.
- **Invoice table** — columns: Customer · Invoice no. · Amount due (₹) · Due date · Days overdue · Aging bucket. Sortable by **Amount**, **Days overdue**, **Due date** (client-side over the returned rows; a visible sort indicator on the active column). Missing due dates show `—` and bucket `unclassified`; negative credit notes render with their sign.
- **Truncation prompt** — when the response has `truncated=true` (an unfiltered/broad view over a large file), a non-error banner: "Showing first N of M invoices — pick a customer or employee to see them all."
**Actions:** open/close the section; pick/clear customer; pick/clear employee; click a column header to sort → each change re-calls `POST /api/invoices` (filters) or re-sorts locally (columns). Filter changes show a labelled loading state in the section.
**States:** collapsed (section hidden until "Drill down" or an employee-row click); loading (fetching invoices); empty (a filter matches no rows → "No invoices for this filter", not an error); populated; error (server error → inline message, dashboard above stays intact).

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
