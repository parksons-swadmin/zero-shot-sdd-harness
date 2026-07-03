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

- **Goal:** The user can browse a library of every uploaded file, select two or more files to build a session's scope, ask a question that spans them ("this month vs last month"), and get back an answer that used real iterative or planned reasoning (not just a single pass) when the question warrants it — plus 2-3 proactive follow-up suggestions on every answer. Conversations persist across days against the same fixed dataset scope.
- **Capabilities delivered:** `dataset-ingestion` (multi-file library browsing), `library-and-sessions` (full: cross-file join/compare, file inference, session/message persistence across days), `conversational-analysis` (adaptive escalation — real `classify_query`, `plan_steps`, `check_result`/iterate nodes replace the Phase-1 stub — plus proactive follow-up-question suggestions, pulled forward from Phase 3 into Phase 2).

- **Design decisions (Assumed, per orchestrator instruction — not re-litigated here, just recorded):**
  1. **File-scope selection is explicit, not NLP-inferred.** The user builds a session's scope by checkbox-selecting 1+ files from the flat library list (no tags, no search — already decided). There is no free-text "which file did you mean" resolution step. The roadmap's "infer which files a question refers to" success criterion is satisfied one level down: once 2+ datasets are in a session's scope, `load_context` loads all their profiles (as it already does in Phase 1 for a single dataset — see `src/graph/nodes.py::load_context`), each labelled `df`/`df2`/... with its filename in the `generate_code` prompt (see `_build_generate_code_prompt`), and `generate_code`'s single Gemini call decides per-question which named dataframe(s) are relevant when it writes the pandas code. This is real inference, at zero extra LLM-call cost, done by the same call that already runs in Phase 1.
  2. **A new file selection always starts a fresh session over the union of selected datasets — it never mutates an existing session's scope.** Rationale: `Session`/`SessionDataset` already model "one fixed set of datasets, persisted across days" (`spec/data.md`); allowing a session's scope to change mid-conversation would break that invariant and complicate `load_context`/history semantics for no user-facing benefit. Consequence: there is no "add a file to an existing session" endpoint. To ask a cross-file question, the user (re)selects the full set of files they want in scope in the library sidebar, which calls the existing `POST /sessions` with all selected `dataset_ids` and starts a new session. If a session already exists for the exact same dataset-ID set (order-independent), the frontend reuses it (see `frontend-library` below) so re-selecting the same files resumes rather than forks the conversation.
  3. **Follow-up suggestions are produced by extending `compose_answer`'s existing single Gemini call — zero extra LLM calls.** `compose_answer`'s prompt (`src/prompts/compose_answer.md`) is extended to also request a trailing, clearly-delimited follow-up section; the plain-language answer prose is parsed first and is required to end before that delimiter, so `_extract_key_numbers`'s bolded-number regex (which only ever runs against the prose portion) cannot collide with it. Exact format below under `reasoning-upgrade-backend`.

- **Independent slices (parallel build units):**
  - `library-backend` (backend) — deps: none beyond Phase 1 schema (already exists — see confirmation below). Adds `GET /datasets` (library list) and `GET /sessions/{session_id}` (persisted history) to the existing dataset/session API surface. Owns `src/api/datasets.py` and `src/api/sessions.py` exclusively for this phase (`reasoning-upgrade-backend` never touches either file — it only edits graph/LLM files, see below, so there is no path collision).
  - `reasoning-upgrade-backend` (backend) — deps: none beyond Phase 1 graph (already fully wired — no topology change). Replaces the pass-through bodies of `classify_query`, `plan_steps`, `check_result` in `src/graph/nodes.py` with real Gemini calls; adds the optional per-call `model` override needed for the cheap router call; extends `compose_answer` to also emit follow-up questions and wires them into `finalize`'s existing `follow_up_questions_json` write (already a no-op `None` today).
  - `frontend-library` (frontend) — deps: none at the code level (builds against the `spec/api.md` contract for `GET /datasets`, `GET /sessions/{session_id}`, and the existing `POST /sessions`/`POST /sessions/{id}/messages`, all of which are now fully specified below, not against `library-backend`'s or `reasoning-upgrade-backend`'s code). Replaces the Phase-1 "Library" and "Suggested follow-ups" `StubPanel` stubs with functional components; adds persisted chat-thread rendering.

- **Key surfaces/files:**
  - `library-backend`:
    - `src/api/datasets.py` — add `GET /datasets` handler (list every `Dataset` row, newest first)
    - `src/api/sessions.py` — add `GET /sessions/{session_id}` handler (session metadata + full `Message`/`QueryResult` history, ordered by `created_at`); no change to the existing `POST /sessions` or `POST /sessions/{session_id}/messages` handlers
    - `src/domain/dataset.py` — add `DatasetListItemOut` (id, filename, row_count, column_count, status, created_at) and `DatasetListResponse`
    - `src/domain/session.py` — add `MessageOut`, `SessionHistoryResponse` (session_id, dataset_ids, messages: list[MessageOut with nested query_result])
    - `tests/unit/test_library_endpoints.py` (new) — unit tests for both new endpoints against the real SQLite file DB (upload 2 fixtures, list them; create a session, ask via a mocked graph run or reuse `finalize` directly, fetch history, assert ordering and shape)
  - `reasoning-upgrade-backend`:
    - `src/graph/nodes.py` — real `classify_query` (calls `LLMClient().call_model_with_usage(prompt, system=..., model=settings.llm_router_model or "gemini-2.5-flash")`, parses `{"mode": ...}` JSON, falls back to `"simple"` on any parse/LLM error so a router hiccup never blocks the answer), real `plan_steps` (ordered sub-questions capped at `settings.max_plan_steps`, only reachable on the `planned` path), real `check_result` (judges `execution_result` against the current question/step, returns `accept`/`refine`, forces `accept` at `iteration_count >= max_iterations` or `step_count >= max_total_steps`), `compose_answer` extended to also emit `follow_up_questions` (see format below), `finalize` updated to persist `state["follow_up_questions"]` into `QueryResult.follow_up_questions_json` (currently hardcoded `None`)
    - `src/llm/client.py` — `LLMClient.call_model_with_usage(self, prompt, *, system=None, model=None)`: when `model` is passed, it overrides the provider's configured model for this call only (does not mutate `self._provider`'s stored model, so subsequent calls on the same client instance are unaffected)
    - `src/llm/providers/gemini.py` — `GeminiProvider.call_model_with_usage(self, prompt, *, system=None, model=None)`: uses `model or self._model` when calling `self._client.models.generate_content(...)`
    - `src/llm/providers/anthropic.py` — same optional `model` kwarg added for interface parity (Anthropic is not the router-model path in this phase, since `AGENT_LLM_ROUTER_MODEL` is Gemini-only per `spec/agent.md`, but the shared `LLMClient` interface must not diverge per-provider)
    - `src/prompts/classify_query.md` (new) — system prompt instructing the router to return strict JSON `{"mode": "simple"|"iterative"|"planned"}` given the question + column names only (no aggregate values needed for routing)
    - `src/prompts/plan_steps.md` (new) — system prompt instructing an ordered JSON list of sub-questions, capped instruction included in-prompt
    - `src/prompts/check_result.md` (new) — system prompt instructing strict JSON `{"decision": "accept"|"refine", "feedback": "..."}`
    - `src/prompts/compose_answer.md` (modify) — append an instruction to end the response with a line `---FOLLOW-UPS---` followed by 2-3 questions, one per line, prefixed `- `; parsed by a new `_split_answer_and_follow_ups(text)` helper in `nodes.py` that splits on the literal `---FOLLOW-UPS---` marker (the prose before it is what `_extract_key_numbers` runs against, unaffected)
    - `tests/unit/test_reasoning_nodes.py` (new) — pure unit tests for `classify_query`/`plan_steps`/`check_result`/`_split_answer_and_follow_ups` with the LLM call mocked at `LLMClient.call_model_with_usage`, asserting routing/parsing/capping logic without any network call
  - `frontend-library`:
    - `frontend/src/components/LibrarySidebar.tsx` (new) — replaces the Phase-1 "Library" `StubPanel` usage in `page.tsx`; fetches `GET /datasets` on mount, renders a checkbox list, a "Start session" button that calls `POST /sessions` with the checked `dataset_ids` (or reuses a matching in-progress session — see design decision #2)
    - `frontend/src/components/ChatThread.tsx` (new) — renders the array from `GET /sessions/{session_id}` as a scrollable list of user/assistant turns, each assistant turn reusing the existing `AnswerPanel`; called on session load/resume (including a page reload) instead of starting with an empty answer area
    - `frontend/src/components/FollowUpChips.tsx` (new) — replaces the Phase-1 static "Suggested follow-ups" `StubPanel` block in `page.tsx`; renders `answer.follow_up_questions` as clickable chips, `onClick` sets the question textarea's value (does not auto-submit)
    - `frontend/src/app/page.tsx` (modify) — swap the `StubPanel` "Library" block for `<LibrarySidebar>`, swap the `StubPanel` "Suggested follow-ups" block for `<FollowUpChips>`, add `ChatThread` rendering when a session with existing history is resumed; "Charts"/"Export"/cost badge/step-progress `StubPanel`s are untouched
    - `frontend/src/lib/types.ts` (modify) — add `DatasetListItem`, `SessionHistoryResponse`, `MessageOut` types; `QueryResult.follow_up_questions` already typed from Phase 1's contract, now populated for real
    - `tests/e2e/phase2.spec.ts` (new) — see Gate command below

- **Schema confirmation:** no new Alembic migration is needed for Phase 2. `alembic/versions/0002_phase1_schema.py` (per `src/db/models.py`) already creates `Session`(`sessions`)/`SessionDataset`(`session_datasets`)/`Message`(`messages`)/`QueryResult`(`query_results`, including `follow_up_questions_json`) in full — every field Phase 2 needs already exists and is nullable where Phase 2 is the first writer (`follow_up_questions_json`).

- **Gate command(s):**
  1. `uv run alembic current` — confirm the DB is already at the head revision from Phase 1 with no pending migration (no `alembic revision --autogenerate` step this phase — see schema confirmation above)
  2. `uv run pytest tests/unit tests/integration -q` (runs the full suite, including the four new files below alongside all Phase 1 tests, unchanged and still passing) — real `AGENT_GEMINI_API_KEY` from `.env` for the two new integration tests, real SQLite file DB, LLM mocked only in the two new unit test files:
     - `tests/integration/test_phase2_cross_file.py` — uploads two fixture CSVs, `month1.csv` (rows dated in month 1, a `revenue` column) and `month2.csv` (same schema, month 2 dates), each with an independently pre-computed total; creates one session over both `dataset_ids`; asks "What is the combined total revenue across both months?"; asserts the response contains the exact pre-computed sum of both files' totals (proving both dataframes, labelled `df`/`df2` with filenames in the prompt, were actually joined/combined, not just one read)
     - `tests/integration/test_phase2_adaptive_reasoning.py` — uploads one fixture CSV with two independent numeric columns (e.g. `revenue`, `units_sold`) across enough rows that a single `result = ...` line reliably can't answer both parts at once; asks a two-part question such as "What is the total revenue, and separately what is the average units_sold per region?"; asserts `query_result["reasoning_mode"] in ("planned", "iterative")` and `query_result["step_count"] > 1` as stored, and that the answer text contains both pre-computed exact values
     - `tests/unit/test_library_endpoints.py`, `tests/unit/test_reasoning_nodes.py` — as described in Key surfaces/files above, LLM mocked, real SQLite file DB
  3. `cd frontend && pnpm build` — CSS bundle contains real Tailwind utility selectors (unchanged bar from Phase 1)
  4. `cd frontend && npx playwright test tests/e2e/phase2.spec.ts --reporter=line` — against `http://localhost:8001/app/` with the backend running: upload `month1.csv` and `month2.csv` as two separate uploads, check both boxes in the library sidebar, click "Start session", ask the cross-file question, see a real (non-stub, non-spinner) answer render; reload the page, re-select the same two files (or otherwise resume the session per the frontend's resume logic) and confirm the prior user/assistant turn still renders via `ChatThread`; click one of the rendered follow-up chips and confirm the question textarea's value updates to that chip's text (not auto-submitted)
  5. Structured request/response logging visible on stdout for the `classify_query` router call (model, latency, status) distinct from the `generate_code`/`compose_answer` calls, during the e2e run
  6. Working tree clean and pushed

- **How the user tests it (handoff seed):**
  1. `cd frontend && pnpm build`, then from the repo root `uv run python -m src`
  2. Open `http://localhost:8001/app/`
  3. Upload a first CSV (as in Phase 1), then upload a second, different CSV — both now appear as checkboxes in the (now-functional, no longer greyed) "Library" sidebar
  4. Check both boxes and click "Start session" — a session scoped to both files begins
  5. Ask a question that requires both files (e.g. "what's the combined total of column X across both files") — get back a correct, real answer that used both dataframes
  6. Ask a harder, multi-part question (e.g. "what's the total of X, and separately the average of Y per region") — notice the answer may take a bit longer (visible step activity in the backend logs) because the agent planned/iterated rather than answering in one pass, and the final answer correctly covers both parts
  7. See 2-3 real, clickable "Suggested follow-ups" chips under the answer — click one and see it populate the question box (it does not auto-submit; you still click Ask)
  8. Close the browser tab entirely, reopen `http://localhost:8001/app/`, re-select the same two files and resume — the prior conversation (both questions and answers) is still there, exactly as before

### Phase 3 — Rich Answer Artifacts, Audit Trail & Cost Accounting

*(Requirements phase 2 of 2 — the final requirements phase: every remaining capability goes live end-to-end.)*

- **Goal:** Answers can include a ranked/summary table, an interactive chart, and a cleaned/derived export file; the agent flags anomalies/data-quality issues it notices while answering (follow-up-question suggestions already shipped in Phase 2); the user can view the audit-trail history and see per-query + running-total cost/token estimates; partial answers stream in as the agent works, with a live step-progress indicator.
- **Capabilities delivered:** `conversational-analysis` (charts, exports, anomaly flags — completing the capability; follow-ups already full as of Phase 2), `audit-and-cost-tracking` (full: history UI, cost/token UI, streaming), `dataset-ingestion` (derived/exported datasets become reusable library entries).
- **Independent slices (sketch):**
  - `artifacts-backend` (backend) — chart-spec generation, export-file writer, anomaly-flag synthesis in `compose_answer` (alongside the Phase 2 follow-up-question output already in that same call).
  - `audit-cost-backend` (backend) — `GET /audit-log`, `GET /cost-summary`, SSE streaming endpoint for partial answers + step events.
  - `frontend-artifacts` (frontend) — chart rendering, working export button, anomaly banners (follow-up chips already wired in Phase 2's `FollowUpChips.tsx`).
  - `frontend-audit-cost` (frontend) — history page, running-total cost badge, streaming answer text, live step-progress bar.
- **Gate command (sketch):** `uv run pytest tests/integration/test_phase3_artifacts.py tests/integration/test_phase3_audit_cost.py -q` against real Gemini + SQLite — assert a chart spec and export file are produced for a fixture question, assert `GET /audit-log` returns entries matching a known run, assert `GET /cost-summary` running total increases by the recorded `CostRecord` sum; `npx playwright test tests/e2e/phase3.spec.ts` covering the streaming answer and chart render.
- **How the user tests it:** ask a question that produces a chart and an export, download the export, see an anomaly banner on a dataset with a known bad column, open the history page and see the prior questions/results, and watch the answer stream in with a live step counter.

### Phase 4 — Hardening & Production Readiness *(trailing phase)*

- **Goal:** The system is safe and fast under its stated hard constraints, not just functionally complete.
- **Scope:** Confirm/handle a genuine 100MB CSV end-to-end within the storage and memory budget; measure and enforce the sub-30s latency budget on the single-call path (regression test with a timing assertion); security review of the sandboxed executor (attempt known escape patterns — `__import__`, `os.system`, dunder attribute traversal, oversized `result` payloads — and assert each is rejected or capped); log rotation/retention policy for the audit log; README/`.env.example` final pass.
- **Gate command (sketch):** `uv run pytest tests/security/test_sandbox_escapes.py tests/performance/test_latency_budget.py -q` against the real Gemini key and a real 100MB fixture CSV (generated once and cached under `tests/fixtures/`).
- **How the user tests it:** upload a real ~100MB export and confirm profiling/answering still completes within the stated budget; no separate UI change expected.
