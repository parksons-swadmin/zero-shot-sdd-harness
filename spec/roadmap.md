# Roadmap

---

## What This Agent Does

A personal data-analysis agent for CSV/spreadsheet exports (CRM exports, business/ops reports). The user uploads a file, the agent auto-cleans and auto-profiles it, and the user asks natural-language questions about it. Depending on how hard the question is, the agent answers instantly from a single reasoning pass or escalates to iterative code-refinement or full upfront planning — always by writing and running real analysis code against the actual data locally, never by asking an LLM to eyeball a sample. Answers come back as a plain-language summary with key numbers highlighted, an optional table/chart/export, and the underlying code in a collapsible panel so the user can verify it. Over time the agent holds a library of uploaded files, can join/compare across them, remembers conversation context within a dataset across sessions that may span days, and keeps a full audit trail of every question asked, every piece of code run, and every result stored — because this is a tool whose answers the user acts on.

## Who Uses It

A single person (analyst / ops / business owner) working directly with their own spreadsheet exports, a few times a day — sometimes one quick lookup, sometimes an extended back-and-forth against the same dataset over several days.

## Core Problem Being Solved

Replaces manually opening a spreadsheet, writing throwaway pivot tables/formulas, and re-deriving the same cleaning steps every time a new export lands — with a tool that cleans, profiles, and answers questions over the data on demand, and shows its work.

## Success Criteria

- [ ] A CSV up to 100MB can be uploaded, auto-cleaned (with a report of what was fixed), and auto-profiled (columns, types, row counts) in one flow.
- [ ] A natural-language question about the uploaded data returns a plain-language answer containing the numerically correct result, computed from the FULL dataset (not a truncated sample), within 30 seconds.
- [ ] The exact analysis code that produced the answer is visible and re-runnable by inspection.
- [ ] No row-level data value from an uploaded file is ever included in a prompt sent to the LLM provider — only schema/summary metadata and code/results.
- [ ] Every question asked, code run, and result produced is persisted with a timestamp in an audit log, from Phase 1 onward.
- [ ] By the end of the requirements phases: the user can browse a library of multiple uploaded files, ask a question that spans two files, and get a joined/compared answer; the agent proactively suggests 2–3 follow-up questions and flags anomalies it notices.

## What This Agent Does NOT Do (Out of Scope)

- No external integrations (no CRM/API connectors, no email/Slack delivery) — standalone, local-file-in/answer-out only.
- No multi-user accounts, auth, or sharing — single local user, no login system.
- No natural-language write-back to the source files — the agent never mutates the user's original upload; cleaning produces a separate cleaned copy.
- No support for file formats beyond CSV/spreadsheet exports readable by pandas (`.csv`, `.tsv`, `.xlsx`) in v1.
- No cloud/remote execution of analysis code — code execution is always local to the machine running the agent.
- No open-ended chat unrelated to the loaded dataset(s) — the agent's scope is data analysis over uploaded files.

## Key Constraints

- **Raw data never leaves the machine.** Only schema/summary/profile metadata and generated code/results may appear in any Gemini API call — never row-level values. See `spec/architecture.md` for the structural enforcement.
- **File size:** CSVs up to 100MB must be accepted; profiling and analysis run against the full file, not a sample.
- **Latency:** sub-30s response for the on-path single-call reasoning mode; iterative/planning modes are bounded so they cannot run unboundedly (see `spec/agent.md`).
- **Production-grade from day one:** full audit trail (what was asked, what code ran, what result was stored, timestamped) is a hard requirement, not a later polish item — the underlying log is written starting in Phase 1 even before it has a UI.
- **Cost awareness:** every LLM call's token usage is recorded from Phase 1 onward (even before a cost UI exists), since keeping Gemini costs low matters.

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win.** It must work perfectly the first time the user tests it — zero rough edges on the tested path. Its backend is minimal but REAL on the one core path. Its frontend is visually complete: real UI for the one working path PLUS clearly-labelled NON-FUNCTIONAL stubs for everything coming later. Each later phase wires those stubs into real functionality.

### Phase 1 — Upload, Profile & Ask

- **Goal:** Upload a single CSV, see its auto-profile (columns, types, row counts) immediately, ask one natural-language question about it, and get back a plain-language answer with key numbers plus the underlying pandas code that produced it (collapsible). Single-call reasoning only.
- **Independent slices (parallel build units):**
  - `db-schema` (backend) — deps: none. Adds all Phase-1+ tables (see `spec/data.md`) to `src/db/models.py`, Pydantic domain models in `src/domain/`, and the initial Alembic migration. This is a true dependency for the two slices below (they read/write these models), so it is built and gated first; `ingestion-backend` and `qa-backend` then run in parallel against the finished schema.
  - `ingestion-backend` (backend) — deps: `db-schema`. Upload endpoint, full-dataset cleaning (`src/tools/cleaning.py`), full-dataset profiling (`src/tools/profiling.py`), local file storage (`src/storage/files.py`).
  - `qa-backend` (backend) — deps: `db-schema`. The graph (`src/graph/*`), the sandboxed code executor + AST guard (`src/execution/*`), the ask endpoint (`src/api/sessions.py`), Gemini prompt templates (`src/prompts/*`), and per-call token/cost capture. Builds against the `Dataset`/`DatasetProfile` contract in `spec/data.md`, not against `ingestion-backend`'s code, so it does not block on it.
  - `frontend-phase1` (frontend) — deps: none. Builds against the documented `spec/api.md` contract: upload panel + profile/cleaning-report display, question box + answer + collapsible code panel, plus labelled non-functional stubs for everything deferred (see "How the user tests it" below).
- **Key surfaces/files:**
  - `db-schema`: `src/db/models.py`, `src/domain/*.py`, `alembic/versions/000x_phase1_schema.py`
  - `ingestion-backend`: `src/api/datasets.py`, `src/tools/cleaning.py`, `src/tools/profiling.py`, `src/storage/files.py`
  - `qa-backend`: `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py`, `src/execution/code_guard.py`, `src/execution/sandbox.py`, `src/api/sessions.py`, `src/prompts/generate_code.md`, `src/prompts/compose_answer.md`, `src/llm/client.py` (usage capture)
  - `frontend-phase1`: `frontend/src/app/page.tsx`, `frontend/src/components/*.tsx`, `frontend/tests/e2e/phase1.spec.ts`
- **Gate command(s):**
  1. `uv run alembic revision --autogenerate -m "phase1 schema"` (against the configured SQLite `AGENT_DATABASE_URL`)
  2. `uv run alembic upgrade head` then `uv run alembic current` (must print a revision hash)
  3. `uv run python -m src` boots with no `ImportError`/`ModuleNotFoundError`; `curl http://localhost:8001/health` returns 200
  4. `uv run pytest tests/unit tests/integration -q` — real `AGENT_GEMINI_API_KEY` from `.env`, real SQLite file DB (not `:memory:`), real CSV parsing. `tests/integration/test_phase1_pipeline.py` uses a fixture CSV of **10,000+ rows** with a pre-computed exact aggregate (e.g. total of a numeric column, or a distinct-count) and asserts the returned answer contains that exact value — proving the answer was computed over the full file, not a truncated sample.
  5. `cd frontend && pnpm install && pnpm build` — CSS bundle contains real Tailwind utility selectors (no unexpanded `@tailwind`/`@source`)
  6. `cd frontend && npx playwright test tests/e2e/phase1.spec.ts --reporter=line` — against `http://localhost:8001/app/` with the backend running: upload a fixture CSV, see the profile render, ask the fixture's known question, see the real answer and code panel render (not a spinner/error)
  7. Structured request/response logging visible on stdout for the Gemini call (prompt size, latency, model, status) during the e2e run; `AuditLogEntry` rows exist in the DB for `upload`, `clean`, `profile`, `ask`, `code_exec`, `answer` after the run
  8. Working tree clean and pushed
- **How the user tests it (handoff seed):**
  1. `cd frontend && pnpm build`, then from the repo root `uv run python -m src`
  2. Open `http://localhost:8001/app/`
  3. Upload a CSV — the profile (columns, types, row count) and cleaning report (what was fixed) appear immediately and are **real**
  4. Type one question about the data (e.g. "what's the total of column X") and submit — a plain-language answer with the key number appears, and clicking "View code" expands the exact pandas code that ran. **Real**, single-call only.
  5. Labelled, non-functional stubs visible on the same screen (must not be mistaken for bugs): a greyed "Library" sidebar showing only the one uploaded file with a "Multi-file library — coming soon" note; a disabled "Export" button; a "Charts" placeholder panel; greyed "Suggested follow-ups" chips; a static "Cost tracking — coming soon" badge; a static step-progress indicator labelled "coming soon". None of these respond to clicks except the disabled/tooltip affordance.

### Phase 2 — Library, Cross-File Analysis & Adaptive Reasoning

*(Requirements phase 1 of 2 — this is also the Agentic Stack Upgrade phase: adds planning + reflection + iteration beyond the Phase 1 base loop, per `spec/agent.md`.)*

- **Goal:** The user can browse a library of every uploaded file, ask a question that spans two files ("this month vs last month"), and get back an answer that used real iterative or planned reasoning (not just a single pass) when the question warrants it. Conversations persist across days against the same dataset(s).
- **Capabilities delivered:** `dataset-ingestion` (multi-file library browsing), `library-and-sessions` (full: cross-file join/compare, file inference, session/message persistence across days), `conversational-analysis` (adaptive escalation: real `classify_query`, `plan_steps`, `check_result`/iterate nodes replace the Phase-1 stub).
- **Independent slices (sketch):**
  - `library-backend` (backend) — `GET /datasets`, session CRUD, `SessionDataset` join logic; deps: none beyond Phase 1 schema.
  - `reasoning-upgrade-backend` (backend) — real `classify_query`, `plan_steps`, `check_result` nodes, bounded-iteration routing; deps: none beyond Phase 1 graph.
  - `frontend-library` (frontend) — functional library sidebar, multi-file selection, persisted chat thread UI; deps: none (builds against `spec/api.md`).
- **Gate command (sketch):** `uv run pytest tests/integration/test_phase2_cross_file.py tests/integration/test_phase2_adaptive_reasoning.py -q` against real Gemini + SQLite, using a two-file fixture pair (e.g. "month 1" / "month 2" exports) and a question whose correct answer requires joining both, plus a question complex enough to force the `planned` reasoning path (assert `reasoning_mode == "planned"` and `step_count > 1` in the stored `QueryResult`); `npx playwright test tests/e2e/phase2.spec.ts`.
- **How the user tests it:** re-upload a second file, see both in the library, ask a cross-file question, get a correct joined answer; close and reopen the browser the next day and see the prior conversation still there against the same dataset.

### Phase 3 — Rich Answer Artifacts, Audit Trail & Cost Accounting

*(Requirements phase 2 of 2 — the final requirements phase: every remaining capability goes live end-to-end.)*

- **Goal:** Answers can include a ranked/summary table, an interactive chart, and a cleaned/derived export file; the agent proactively suggests 2–3 follow-up questions and flags anomalies/data-quality issues; the user can view the audit-trail history and see per-query + running-total cost/token estimates; partial answers stream in as the agent works, with a live step-progress indicator.
- **Capabilities delivered:** `conversational-analysis` (charts, exports, follow-ups, anomaly flags — full), `audit-and-cost-tracking` (full: history UI, cost/token UI, streaming), `dataset-ingestion` (derived/exported datasets become reusable library entries).
- **Independent slices (sketch):**
  - `artifacts-backend` (backend) — chart-spec generation, export-file writer, follow-up/anomaly synthesis in `compose_answer`.
  - `audit-cost-backend` (backend) — `GET /audit-log`, `GET /cost-summary`, SSE streaming endpoint for partial answers + step events.
  - `frontend-artifacts` (frontend) — chart rendering, working export button, clickable follow-up chips, anomaly banners.
  - `frontend-audit-cost` (frontend) — history page, running-total cost badge, streaming answer text, live step-progress bar.
- **Gate command (sketch):** `uv run pytest tests/integration/test_phase3_artifacts.py tests/integration/test_phase3_audit_cost.py -q` against real Gemini + SQLite — assert a chart spec and export file are produced for a fixture question, assert `GET /audit-log` returns entries matching a known run, assert `GET /cost-summary` running total increases by the recorded `CostRecord` sum; `npx playwright test tests/e2e/phase3.spec.ts` covering the streaming answer and chart render.
- **How the user tests it:** ask a question that produces a chart and an export, download the export, click a suggested follow-up, see an anomaly banner on a dataset with a known bad column, open the history page and see the prior questions/results, and watch the answer stream in with a live step counter.

### Phase 4 — Hardening & Production Readiness *(trailing phase)*

- **Goal:** The system is safe and fast under its stated hard constraints, not just functionally complete.
- **Scope:** Confirm/handle a genuine 100MB CSV end-to-end within the storage and memory budget; measure and enforce the sub-30s latency budget on the single-call path (regression test with a timing assertion); security review of the sandboxed executor (attempt known escape patterns — `__import__`, `os.system`, dunder attribute traversal, oversized `result` payloads — and assert each is rejected or capped); log rotation/retention policy for the audit log; README/`.env.example` final pass.
- **Gate command (sketch):** `uv run pytest tests/security/test_sandbox_escapes.py tests/performance/test_latency_budget.py -q` against the real Gemini key and a real 100MB fixture CSV (generated once and cached under `tests/fixtures/`).
- **How the user tests it:** upload a real ~100MB export and confirm profiling/answering still completes within the stated budget; no separate UI change expected.
