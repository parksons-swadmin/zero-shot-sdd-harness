# Roadmap

---

## What This Agent Does

A fully-local, deterministic desktop dashboard for **Accounts Receivable (AR) aging**. The user uploads an AR aging export (`.xlsx`), the tool auto-detects the six required columns and asks the user to confirm the mapping, then computes exact AR aging metrics with pandas and renders an interactive browser dashboard — KPI tiles, a Top-20-customers-by-overdue chart, employee summaries, aging breakdowns, proactive risk flags, and Excel/PDF exports. **Nothing leaves the machine:** no LLM, no external API, no database, no network egress.

## Who Uses It

A finance / accounts-receivable owner (credit controller, AR manager, finance lead) at a company that exports its AR aging from an ERP/accounting system to Excel. They need an accurate, trustworthy at-a-glance view of who owes what, how overdue it is, and which accounts and salespeople need chasing — without sending sensitive customer/balance data to any cloud service.

## Core Problem Being Solved

Today this analysis is done by hand in Excel with pivot tables and manual formulas — slow, error-prone, and re-done every period. This tool replaces that with a one-upload, exact, deterministic dashboard whose every number ties out to the source file, and which never risks leaking confidential AR data off the machine.

## Success Criteria

- [ ] Upload → confirm mapping → dashboard works first time, and every KPI ties out **exactly** (integer-paise equality) to the source `.xlsx`.
- [ ] The Top-20 customers by overdue amount render correctly, ranked descending.
- [ ] Auto-detection maps the six fields; low-confidence headers are flagged for the user to confirm before compute.
- [ ] A ≥60,000-row file is handled gracefully and its totals tie out (no sampling/truncation).
- [ ] Employee summary, aging breakdown + weighted-avg-days-overdue, proactive flags, and Excel + PDF export all work (by end of Phase 3).
- [ ] No network call is ever made; no data is persisted.

## What This Agent Does NOT Do (Out of Scope)

- **DSO (Days Sales Outstanding)** — no sales/turnover column exists in the input. It is **never** computed, faked, or added later.
- **`.xls`, `.csv`, `.pdf`** ingestion — `.xlsx` only for this build.
- **No LLM / AI commentary** — every number is deterministic pandas arithmetic.
- **No persistence** — no database, no history, no saved sessions, no multi-file, no auto-watch, no login.
- **No network egress of any kind** — fully offline.

## Key Constraints

- **Correctness is paramount:** every number ties out exactly (integer paise; no float drift, no rounding that changes totals, no sampling).
- **Fully local & stateless:** one file at a time, fresh every upload, nothing persisted, nothing sent anywhere.
- **Currency:** ₹ INR with Indian lakh/crore digit grouping.
- **Deterministic:** identical input → identical output; tests inject a fixed `as_of` date so aging buckets are reproducible.
- **No LLM, no API keys:** `.env` needs no provider keys (none exist). The "real path" the gates exercise is the **real deterministic pandas pipeline over real `.xlsx` fixtures** — there is no external API to call.

---

## Test Fixtures (owned by the Phase-1 `engine` slice, reused by all phases)

A code-generator produces `tests/fixtures/build_fixtures.py` (pandas/openpyxl) generating two workbooks, plus **independent** expected-value oracles.

### `ar_small.xlsx` — hand-computable tie-out fixture (~18 rows)
Fixed, known rows anchored to **`AS_OF = date(2026, 1, 15)`** (tests inject this `as_of`, so buckets never go stale). Deliberately messy headers to exercise fuzzy matching: `Cust Name`, `Invoice #`, `Inv. Date`, `Due Dt`, `Balance Outstanding`, `Sales Person` (the `due_date` header is chosen to land at `low` confidence so the confirm-screen path is exercised).
Required rows / edge cases:
- 5 customers incl. unicode: `Acme Corp`, `Müller Traders`, a Devanagari name (`श्री एंटरप्राइजेज`), `Zenith Ltd`, `Beacon & Co`.
- 3 employees: `Ravi`, `Priya`, and **one blank employee** on one row.
- Due dates spanning every state relative to `AS_OF`: some **current** (due after 2026-01-15), and at least one each in **0-30 / 31-60 / 61-90 / 90+** (use day-of-month > 12 to avoid dd/mm ambiguity).
- Mixed date formats: some native Excel date cells, one ISO string `2025-12-20`, one Excel serial number.
- One row with **missing due date** (blank).
- One **negative amount** (credit), one **zero amount**, rest positive.
- **Zenith Ltd** = only current invoices (0 overdue → `weighted_avg_days_overdue = null`).
- **Beacon & Co** = deep in 90+ (top of the riskiest list & Top-20).
- **`tests/fixtures/expected_small.json`** — hand-authored oracle (NOT computed by the pipeline): exact `total_outstanding`, `total_overdue`, `pct_overdue`, `customer_count`, `bucket_totals`, `worst_bucket`, `top_customers_by_overdue`, `employees` block, per-customer `weighted_avg_days_overdue`, and the exact list of flagged rows by `row_index` + reason.

### `ar_large.xlsx` — scale / full-data fixture (≥60,000 rows)
Deterministically generated with a **seeded** RNG (reproducible). **High-value rows are placed in the last 100 rows** so any sampling/prefix/truncating implementation produces a wrong total → this is the full-data gate. The builder writes **`tests/fixtures/expected_large.json`** using a **dead-simple independent summation** (`sum(round(a*100))` over all rows — not the pipeline) as the oracle: exact `total_outstanding` (paise), `total_overdue`, `row_count`, and the Top-20 identity.

---

## Phases of Development

> **DB dropped → no `alembic upgrade head` in any gate** (the tool is stateless; see [data.md](data.md)). The Phase-1 gate keeps every other harness gate item: boots via the documented run command; agentic-stack (graph compiles, state flows through nodes); styled-render of the static export; Playwright E2E; observability (structlog). There is **no LLM/API key** — the "real path" is the real deterministic pipeline over real `.xlsx` fixtures.

### Phase 1 — Upload → Map → Headline Dashboard (Top-20 + KPIs)

- **Goal:** The user uploads an AR `.xlsx`, confirms the auto-detected column mapping, and sees the Top-20-customers-by-overdue bar chart plus the five headline KPI tiles — with every number tying out **exactly** to the source file. Later surfaces appear as labelled stubs.
- **Capabilities:** [xlsx_ingestion_and_mapping](capabilities/xlsx_ingestion_and_mapping.md), [aging_metrics_engine](capabilities/aging_metrics_engine.md), [headline_dashboard](capabilities/headline_dashboard.md).
- **Independent slices (parallel build units):**
  - `engine` (backend) — **deps: none.** The deterministic LangGraph pipeline (no LLM) + pure-function tools + domain models + fixtures. Removes the LLM/DB skeleton. Ships unit tests incl. exact tie-out (small) and full-data (large).
  - `api` (backend) — **deps: `engine`** (imports the runner + domain models; both build against the contract in [api.md](api.md)/[data.md](data.md)). FastAPI `preview`/`compute` routes. Ships integration tests (TestClient over the real pipeline + real fixture files).
  - `frontend` (frontend) — **deps: none for build** (builds against the [api.md](api.md) contract); its Playwright E2E runs at phase assembly once `engine`+`api` are present. Upload + mapping-confirm + dashboard (real KPIs + Top-20; labelled stubs for later).
- **Key surfaces / files:**
  - `engine`: `src/graph/{state,nodes,edges,agent,runner}.py`, `src/tools/{header_detect,ingest,validate,metrics,flags}.py`, `src/domain/{aging,quality,mapping}.py`, `src/config/settings.py` (rewritten), `pyproject.toml` (deps: +pandas/openpyxl/rapidfuzz/python-multipart, −anthropic/google-genai/sqlalchemy/alembic), `.env.example` (rewritten, no keys), `tests/fixtures/build_fixtures.py` + generated `ar_small.xlsx`/`ar_large.xlsx` + `expected_small.json`/`expected_large.json`, `tests/unit/**`. **Deletes** `src/llm/`, `src/db/`, `alembic/`, `alembic.ini`, `src/prompts/transform.md`, `src/api/runs.py`'s domain (`src/domain/run.py`).
  - `api`: `src/api/analysis.py` (new), `src/api/__init__.py` (register router, keep `/app` mount + `health`), delete `src/api/runs.py`, `tests/integration/test_pipeline.py` (rewritten for the AR pipeline).
  - `frontend`: `frontend/src/app/page.tsx`, `frontend/src/app/components/**` (Upload, MappingConfirm, KpiTiles, TopCustomersChart, Stubs), `frontend/src/lib/format.ts` (INR formatter), `frontend/src/app/globals.css` (extend below `@source`), `frontend/package.json` (+recharts), `frontend/tests/e2e/smoke.spec.ts`, `frontend/playwright.config.ts`.
- **Gate command (all must pass, from repo root unless noted):**
  1. `uv run pytest tests/unit tests/integration -q` — unit + integration: exact tie-out on `ar_small.xlsx` vs `expected_small.json`; full-data tie-out on `ar_large.xlsx` vs `expected_large.json`; graph compiles + state flows through nodes; `preview`/`compute` via TestClient over the real pipeline; the `.csv`/`.xls` rejection and incomplete-mapping error paths.
  2. `uv run python -m src` — boots on the documented command with no `ImportError`/`ModuleNotFoundError` (test path == run path).
  3. `cd frontend; pnpm build` — static export builds; `frontend/out/` produced; built CSS bundle contains real Tailwind utility selectors (no unexpanded `@tailwind`/`@source`).
  4. from `frontend/`: `npx playwright test tests/e2e/ --reporter=line` — Playwright (config `webServer: uv run python -m src`, baseURL `http://localhost:8001/app/`) walks upload `ar_small.xlsx` → confirm mapping → asserts a headline KPI value text and ≥1 Top-20 chart bar are present and non-empty (not a spinner/error).
  5. A structlog JSON line appears for the compute run (observability wired).
- **How the user tests it (handoff seed):**
  1. From repo root: `cd frontend; pnpm build; cd ..; uv run python -m src`.
  2. Open **http://localhost:8001/app/**.
  3. Upload `tests/fixtures/ar_small.xlsx` (or your own AR `.xlsx`). Confirm the mapping on the confirmation screen (the `due_date` field is amber — confirm it), click **Confirm & Compute**.
  4. **Expected:** five KPI tiles (total outstanding/overdue in ₹ with Indian grouping, % overdue, customer count, worst bucket) and a Top-20 bar chart with `Beacon & Co` at the top. The numbers match `expected_small.json`.
  5. **Labelled stubs (not bugs):** Employee summary, Aging breakdown, Risk flags, Export buttons, Progress bar are visibly tagged "Coming in Phase 2/3".

### Phase 2 — Employees + Breakdown + Weighted-Avg + Proactive Flags

- **Goal:** Wire three Phase-1 stubs into real features: the employee-wise ranked summary, the full aging-bucket breakdown with weighted-average days overdue (per customer & per employee), and the proactive risk-flags + data-quality audit panel.
- **Capabilities (≥3):** [employee_summary](capabilities/employee_summary.md), [group_aging_breakdown](capabilities/group_aging_breakdown.md), [proactive_flags](capabilities/proactive_flags.md).
- **Independent slices (parallel build units):**
  - `engine-phase2` (backend) — **deps: none** (extends the compute/flag nodes). Owns per-employee + per-customer aggregation, weighted-avg-DPD, risk-flag rules, full data-quality report. Files: `src/tools/metrics.py`, `src/tools/flags.py`, `src/graph/nodes.py` (`node_flag` real), `src/domain/aging.py` (+breakdown models). Unit tests: partition invariants + weighted-avg oracle.
  - `frontend-phase2` (frontend) — **deps: none for build** (builds against the extended [api.md](api.md) contract). Employee table, aging-breakdown chart + weighted-avg columns, risk/data-quality panel with the audit list. Files: `frontend/src/app/components/{EmployeeTable,AgingBreakdown,FlagsPanel}.tsx`, `frontend/tests/e2e/phase2.spec.ts`.
- **Key surfaces / files:** as above (disjoint: backend owns `src/`, frontend owns `frontend/`).
- **Gate command:**
  1. `uv run pytest tests/unit tests/integration -q` — employee/customer breakdowns vs `expected_small.json`; partition invariants (per-group totals sum to overall); weighted-avg-DPD oracle incl. the null case (Zenith); riskiest-accounts ranks `Beacon & Co` first; data-quality panel lists exactly the seeded flagged rows.
  2. from `frontend/`: `npx playwright test tests/e2e/ --reporter=line` — E2E asserts the employee table (ranked desc by outstanding), the breakdown chart, and the flags panel render with real values after upload→map→compute.
- **How the user tests it (handoff seed):** rebuild frontend + boot; upload `ar_small.xlsx`; confirm mapping; verify the employee table is ranked by outstanding (with the `(blank)` employee row), the aging breakdown + weighted-avg columns show (Zenith shows `—`), and the risk panel lists `Beacon & Co` plus the four seeded data-quality rows by row index. Export buttons + progress bar remain labelled stubs.

### Phase 3 — Excel Export + Print-PDF + Large-file Progress

- **Goal:** Wire the remaining stubs: multi-sheet Excel export, print-ready PDF, and a live progress bar for large files.
- **Capabilities (≥3):** [excel_export](capabilities/excel_export.md), [pdf_export](capabilities/pdf_export.md), [large_file_progress](capabilities/large_file_progress.md).
- **Independent slices (parallel build units):**
  - `export-backend` (backend) — **deps: none** (uses existing `AgingMetrics`). Owns `src/tools/excel_export.py`, `src/api/analysis.py` (+`GET /api/export/xlsx`, +`POST /api/compute/stream` SSE). Unit/integration: read the workbook back and assert sheet totals equal the API metrics; stream final result equals non-streaming result.
  - `frontend-phase3` (frontend) — **deps: none for build**. Owns the working "Export Excel" download, "Print / Save as PDF" button + `@media print` stylesheet, and the SSE-driven progress bar with fallback. Files: `frontend/src/app/components/{ExportBar,ProgressBar}.tsx`, `frontend/src/app/print.css`, `frontend/tests/e2e/phase3.spec.ts`.
- **Key surfaces / files:** disjoint (backend `src/`, frontend `frontend/`).
- **Gate command:**
  1. `uv run pytest tests/unit tests/integration -q` — exported `.xlsx` has the four named sheets and its Summary totals equal the API `AgingMetrics` exactly (openpyxl read-back); streamed result == non-streaming result for `ar_large.xlsx`; row counts reach ≥60,000.
  2. from `frontend/`: `npx playwright test tests/e2e/ --reporter=line` — E2E: clicking "Export Excel" triggers a non-empty `.xlsx` download; `emulateMedia({media:'print'})` hides upload/stub chrome while KPIs+chart stay visible; `page.pdf()` yields a non-empty PDF; uploading `ar_large.xlsx` shows the progress bar reaching the true row count.
- **How the user tests it (handoff seed):** rebuild + boot; upload `ar_large.xlsx` and watch the progress bar climb to the full row count; on the dashboard click **Export Excel** (opens a multi-sheet workbook whose numbers match the screen) and **Print / Save as PDF** (clean print layout — no upload controls/stubs — save as PDF). All stubs are now real; nothing left labelled "coming soon".

### Phase 3.1 (post-Phase-3 enhancement) — Default mapping profile + auto-skip

- **Goal:** Recurring standard ERP/SAP exports stop requiring a mapping re-confirmation on every upload. Detection ships a **built-in default mapping profile** (canonical field → exact expected header for the common export) that it **prefers** over fuzzy matching; when all six required fields are confidently recognized the app **auto-skips** the mapping-confirmation screen and lands straight on the dashboard, with a dismissible **Review / change mapping** affordance to reopen the (pre-filled) mapping. **Stateless** — the profile is a compiled-in preset; nothing is saved or persisted.
- **Capabilities:** extends [xlsx_ingestion_and_mapping](capabilities/xlsx_ingestion_and_mapping.md) (no new capability file) — the default profile, profile-preferred detection, the `auto_mapped` preview signal ([api.md](api.md)), and the auto-skip flow ([ui.md](ui.md)).
- **Independent slices (parallel build units):**
  - `engine` (backend) — **deps: none.** Add the default-profile constant + profile-preferred detection to header detection, and compute + return `auto_mapped` on the preview response. Adds fixture `tests/fixtures/ar_standard.xlsx` (the `ar_small` rows re-headed with the exact default-profile headers). Unit tests: profile precedence (`Base Line Date` beats other date columns), case/whitespace-insensitive match, and `auto_mapped` true/false incl. the hod-irrelevance and duplicate-collision cases.
  - `frontend` (frontend) — **deps: none for build** (builds against the extended [api.md](api.md) contract). Branch on `auto_mapped`: skip the confirm screen and render the dismissible review affordance; unchanged path when false. Files: `frontend/src/app/page.tsx`, mapping/dashboard components, `frontend/tests/e2e/`.
- **Gate command:**
  1. `uv run pytest tests/unit tests/integration -q` — a preview of `ar_standard.xlsx` returns all six via the profile at `status=high` with `auto_mapped=true`; `invoice_date` pins to `Base Line Date` when multiple date columns exist; a renamed/unrecognized required header returns `auto_mapped=false`; `hod` presence/absence does not change `auto_mapped`; a duplicate-collision case returns `auto_mapped=false`.
  2. from `frontend/`: `npx playwright test tests/e2e/ --reporter=line` — E2E: uploading a standard-header `.xlsx` lands directly on the dashboard (no confirm screen), the "Columns auto-mapped…" affordance is present, clicking **Review / change mapping** reopens the pre-filled mapping; uploading a non-standard `.xlsx` still shows the confirmation screen.
- **How the user tests it (handoff seed):** rebuild + boot; upload a standard export whose headers are `Payer Name / Invoice No. / Base Line Date / Due Date / Amount Due / Current Employee` → you land straight on the dashboard (no mapping step) with a "Columns auto-mapped from your standard format" banner; click **Review / change mapping** to see the pre-filled mapping and optionally re-compute. Upload a file with a renamed column → the mapping-confirmation screen appears as before.
