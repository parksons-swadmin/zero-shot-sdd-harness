# UI

---

## UI Type

Single-page web app (Next.js static export, served by FastAPI at `http://localhost:8001/app/`).

## Views / Screens

Phase 1 ships one screen containing both the real Phase-1 flow and clearly-labelled stubs for what's coming. Later phases activate the stubs in place rather than adding new screens, except the audit-history page (Phase 3).

### Screen: Workspace (Phase 1 — real, plus labelled stubs)

**Purpose:** Upload a dataset, see its profile, ask a question, see the answer.

**Key elements (real, Phase 1):**
- Upload dropzone / file picker (empty state: "Upload a CSV to get started — drag & drop or click to browse")
- Upload progress indicator while the file streams to the server
- Profile card once ready: row count, column count, a table of columns (name, type, null %, distinct count)
- Cleaning report panel: list of what was auto-fixed, with any `needs_review` items visually flagged (not blocking)
- Question textbox + submit button (disabled while empty or while a prior question is in flight)
- Answer panel: plain-language summary rendered through a markdown renderer (bold key numbers survive as **bold**, not literal asterisks) — per `harness/patterns/ui-ux.md`
- "View code" collapsible/disclosure panel showing the exact generated pandas code, monospace, preserved formatting

**Key elements (labelled, non-functional stubs — Phase 1 must visibly mark these, never presented as broken):**
- Library sidebar: shows only the single current dataset, with a persistent caption "Multi-file library — coming soon" (Phase 2 activates)
- "Charts" panel: placeholder illustration + "Charts — coming soon" (Phase 3 activates)
- "Export" button: visibly disabled with a tooltip "Export — coming soon" (Phase 3 activates)
- "Suggested follow-ups" chip row: greyed-out placeholder chips, non-clickable, captioned "Suggested follow-ups — coming soon" (Phase 2 activates — real, clickable chips populate the question box)
- Cost badge: static badge reading "Cost tracking — coming soon" (Phase 3 activates)
- Step-progress indicator: static bar/counter reading "Step tracking — coming soon" (Phase 3 activates; never an animated fake progress bar, per `harness/patterns/ui-ux.md`'s "never fake progress")

**Actions available (Phase 1):** upload a file, submit a question, expand/collapse the code panel.

### Screen: Library (Phase 2 — activates the Phase-1 stub)

**Purpose:** Browse every uploaded/derived dataset, select one or more to scope a session, switch between persisted conversations.

**Key elements:** dataset list (filename, row count, uploaded date, status), multi-select for cross-file questions, persisted chat-thread view (message history survives reload/reopen across days).

### Screen: Workspace answer artifacts (Phase 3a — activates the Phase-1 Charts/Export stubs)

**Purpose:** Render the table, chart, and export produced by an answer, and surface a derived dataset in the library.

**Key elements (real, Phase 3a — replacing the Phase-1 "Charts" placeholder and disabled "Export" stub):**
- **Ranked/summary table** (`ResultTable.tsx`): renders `query_result.table` (`columns`/`rows`) as a scrollable table with a "showing N of M rows" caption when `table.truncated` is true. Hidden when `table` is null.
- **Chart panel** (`ChartPanel.tsx`): renders `query_result.chart_spec` via `recharts` — a bar/line/pie chart built from the `chart_spec.series` array (aggregated points only, never raw rows). When `chart_spec` is null, shows a small "No chart for this answer" caption rather than the old "coming soon" placeholder.
- **Export button** (`ExportButton.tsx`): enabled only when `query_result.export_dataset_id` is non-null; clicking it downloads `GET /query-results/{id}/export` (a full-data CSV, `Content-Disposition: attachment`). When the answer produced no export, the button stays disabled with a "No export for this answer" tooltip (never presented as broken).
- **Derived dataset appears in Library:** after an answer whose `export_dataset_id` is non-null, the Phase-2 Library sidebar refreshes automatically (the workspace bumps a `libraryRefreshKey` used as the sidebar's React `key`, forcing a `GET /datasets` refetch) so the new derived dataset shows up as a selectable checkbox with no manual reload. The derived entry is queryable exactly like an uploaded file.

**Still-stubbed on this screen after 3a (labelled "coming soon", not bugs):** the cost badge (3c) and the step-progress indicator (3c). *(Note: there is no anomaly "coming soon" stub in the Phase-1 UI — the anomaly banner is a net-new element added in 3b, not a stub swap; see `spec/roadmap.md` Phase 3b design decision #7.)*

### Screen: Workspace anomaly banner (Phase 3b — net-new element, no prior stub)

**Purpose:** Proactively surface the data-quality issues the agent noticed while answering.

**Key elements (real, Phase 3b):**
- **Anomaly banner** (`AnomalyBanner.tsx`, `data-testid="anomaly-banner"`): renders `query_result.anomaly_flags` (`list[{type, column, severity, message}]`) as a coloured banner on the answer — one row per flag showing the `column` and plain-language `message`, styled by `severity` (`critical`→red, `warning`→amber, `info`→slate). Renders nothing when `anomaly_flags` is null/empty (a clean answer has no banner — never a "no anomalies" placeholder). Zero extra LLM call — flags come from the existing `compose_answer` call merged with a deterministic profile check (see `spec/roadmap.md` Phase 3b).

**Still-stubbed on the workspace after 3b (labelled "coming soon", not bugs):** the cost badge (3c) and the step-progress indicator (3c).

### Screen: Audit History (Phase 3b — new screen at `/app/history/`)

**Purpose:** View the full audit trail — every question, code run, and result, timestamped — reading the `AuditLogEntry` table written since Phase 1.

**Key elements (real, Phase 3b):**
- Filter controls: `session_id`, `dataset_id`, `event_type`; Prev/Next paging over `limit`/`offset`.
- Chronological table (`data-testid="audit-table"`, oldest-first): `timestamp`, `event_type`, session/dataset, and a summary of `detail` (question text for `ask`, a code snippet for `code_exec`, status for `answer`), each row linking back to its originating session.
- **Raw-data boundary:** shows questions, generated code, and result metadata/summaries only — never raw spreadsheet rows (the `GET /audit-log` payload carries no row data; see `spec/api.md`).

### Screen: Workspace live progress & cost (Phase 3c — activates the last two Phase-1 stubs)

**Purpose:** Show the run happening live (streamed answer + step counter) and make cost visible, replacing the final two "coming soon" stubs.

**Key elements (real, Phase 3c — replacing the Phase-1 cost badge and step-progress stubs):**
- **Cost badge** (`CostBadge.tsx`, keeps `data-testid="cost-badge"`): replaces the static "Cost tracking — coming soon" badge. Fetches `GET /cost-summary` for the all-time running total on mount and refetches after each answer; shows the running total (USD + token count) and the latest answer's per-query `query_result.cost` inline. The running total visibly increases with each question.
- **Step-progress indicator** (`StepProgress.tsx`, `data-testid="step-progress"`): replaces the static "Step tracking — coming soon" stub (the old `stub-step-progress` id is retired). During a streamed ask it renders the live "Step N of ~M: {label}" from incoming `step` events — an honest step-wise/indeterminate indicator, **never a fabricated percentage bar** (per `harness/patterns/ui-ux.md` "never fake progress").
- **Streamed answer:** the Ask flow uses `POST /sessions/{id}/messages/stream` (SSE over `fetch()`+`ReadableStream`, via `frontend/src/lib/stream.ts`) by default: `answer_chunk` events render the answer progressively, then the authoritative `result` event reconciles the full `QueryResultOut` (charts/table/export/anomalies/follow-ups/cost) into the existing rendering. The non-streaming POST remains the fallback if the stream errors before any event.

**No "coming soon" stubs remain on the workspace after 3c** — every Phase-1 placeholder is now live functionality.

## Error States

- **Upload error** (bad format / too large): the dropzone shows a specific message ("This file is larger than 100MB — try a smaller export" / "Couldn't read this as a CSV") with a retry affordance — never a raw exception.
- **Ask error** (run failed / timed out / 409 already-in-flight): the answer panel shows a plain-language message ("Couldn't answer that — the analysis code failed to run. Try rephrasing." for a code failure; "Still working on the previous question — try again in a moment" for 409) with the question re-editable, never a stack trace.
- **Empty states:** upload screen before any file ("Upload a CSV to get started…"); ask panel before any question ("Ask a question about your data once it's uploaded").
- **Loading states:** upload progress bar (real, reflects actual bytes sent); "Thinking…" indicator while a question is in flight (Phase 1: simple spinner + text; Phase 3c: replaced by the real streaming step-progress indicator).

## Tech Stack

Next.js 15 + React 19, TypeScript, Tailwind CSS v4 (existing skeleton: static export, `basePath: '/app'`, `postcss.config.mjs` + `@source` wiring per `harness/patterns/tech-stack.md` — must not be overwritten). Markdown answers rendered via `react-markdown` + `remark-gfm` per `harness/patterns/ui-ux.md`. `tests/e2e/` Playwright smoke tests cover the Phase 1 golden path (upload → profile renders → ask → answer + code panel render) and are extended per phase (`phase2.spec.ts`, `phase3.spec.ts`) as new real functionality lands.
