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
- "Suggested follow-ups" chip row: greyed-out placeholder chips, non-clickable, captioned "Suggested follow-ups — coming soon" (Phase 3 activates)
- Cost badge: static badge reading "Cost tracking — coming soon" (Phase 3 activates)
- Step-progress indicator: static bar/counter reading "Step tracking — coming soon" (Phase 3 activates; never an animated fake progress bar, per `harness/patterns/ui-ux.md`'s "never fake progress")

**Actions available (Phase 1):** upload a file, submit a question, expand/collapse the code panel.

### Screen: Library (Phase 2 — activates the Phase-1 stub)

**Purpose:** Browse every uploaded/derived dataset, select one or more to scope a session, switch between persisted conversations.

**Key elements:** dataset list (filename, row count, uploaded date, status), multi-select for cross-file questions, persisted chat-thread view (message history survives reload/reopen across days).

### Screen: Audit History (Phase 3 — new screen)

**Purpose:** View the full audit trail — every question, code run, and result, timestamped.

**Key elements:** filterable/paginated table (`session`, `dataset`, `event_type`, `timestamp`, detail), links back to the originating session.

## Error States

- **Upload error** (bad format / too large): the dropzone shows a specific message ("This file is larger than 100MB — try a smaller export" / "Couldn't read this as a CSV") with a retry affordance — never a raw exception.
- **Ask error** (run failed / timed out / 409 already-in-flight): the answer panel shows a plain-language message ("Couldn't answer that — the analysis code failed to run. Try rephrasing." for a code failure; "Still working on the previous question — try again in a moment" for 409) with the question re-editable, never a stack trace.
- **Empty states:** upload screen before any file ("Upload a CSV to get started…"); ask panel before any question ("Ask a question about your data once it's uploaded").
- **Loading states:** upload progress bar (real, reflects actual bytes sent); "Thinking…" indicator while a question is in flight (Phase 1: simple spinner + text; Phase 3: replaced by the real streaming step-progress indicator).

## Tech Stack

Next.js 15 + React 19, TypeScript, Tailwind CSS v4 (existing skeleton: static export, `basePath: '/app'`, `postcss.config.mjs` + `@source` wiring per `harness/patterns/tech-stack.md` — must not be overwritten). Markdown answers rendered via `react-markdown` + `remark-gfm` per `harness/patterns/ui-ux.md`. `tests/e2e/` Playwright smoke tests cover the Phase 1 golden path (upload → profile renders → ask → answer + code panel render) and are extended per phase (`phase2.spec.ts`, `phase3.spec.ts`) as new real functionality lands.
