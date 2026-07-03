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

*(Requirements phase 1 — this is also the Agentic Stack Upgrade phase: adds planning + reflection + iteration beyond the Phase 1 base loop, per `spec/agent.md`. The remaining requirements work is split across Phases 3a/3b/3c below.)*

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

> **Phase 3 split (spec-writer decision).** The original single Phase 3 bundled six distinct, independently-testable features (charts, tables+exports+derived datasets, anomaly flags, audit-history UI, cost accounting, streaming). That violates "smallest user-testable win, first-time-right." It is split into three sequential sub-phases — **3a Rich answer artifacts**, **3b Proactive quality + audit trail**, **3c Cost accounting + streaming** — each a genuine standalone user-testable increment. Phase 4 Hardening remains the trailing phase. Phase 3a below is specified to build-ready depth; 3b and 3c are at slice-sketch depth (fully specified when they are next up).

### Phase 3a — Rich Answer Artifacts

*(Requirements phase 2 of 4 remaining — the first of the split Phase-3 increments.)*

- **Goal:** A completed answer can carry (a) a ranked/summary **table**, (b) an interactive **chart**, and (c) a downloadable **export file** of a cleaned/derived dataset, and that derived dataset **appears in the library** (`GET /datasets`) as a reusable entry the user can immediately query like any upload. All three are computed **locally in the sandbox from the already-capped aggregate result** — no raw rows ever reach the client in the answer payload, and no extra LLM call is added (chart/table intent comes from the existing `compose_answer` call; the export-dataframe decision comes from the existing `generate_code` call).
- **Capabilities delivered:** `conversational-analysis` (charts + tables go live — anomaly flags stay stubbed until 3b), `dataset-ingestion` (derived/exported datasets become reusable library entries — the `derived_from_query_result_id` machinery goes live).

- **Design decisions (Assumed, recorded not deferred):**
  1. **Chart & table intent are produced by the existing `compose_answer` Gemini call — zero extra LLM calls** (mirrors the Phase 2 follow-ups decision). `src/prompts/compose_answer.md` is extended to end its response, *after* the existing `---FOLLOW-UPS---` block, with a second literal marker `---ARTIFACTS---` followed by a single strict-JSON object describing chart/table *intent only* (chart type + which result column maps to x/y, whether to render a table, titles) — never the data values themselves. The prose→follow-ups→artifacts sections are split by their markers in order, so `_extract_key_numbers` still runs against the prose portion alone.
  2. **The chart series and table rows are assembled deterministically by our own code from the capped `ExecutionResult`, never emitted by the LLM.** `_build_table_data(execution_result)` and `_build_chart_spec(execution_result, chart_intent)` read only `execution_result["result"]["data_json"]` — which `src/execution/sandbox.py::_cap_result` has already capped to `RESULT_ROW_CAP=200` rows / `RESULT_CELL_CAP=2000` cells of aggregate output — and further cap chart series to `AGENT_CHART_MAX_POINTS` (default 100). This is the structural enforcement of "a chart spec sent to the client carries only aggregated/binned series, not raw rows." If the final result is not tabular (a scalar), `table_data`/`chart_spec` are `None`.
  3. **Exports carry the FULL derived dataset, and are the one artifact NOT capped — because the export never enters the answer payload and never reaches the LLM.** The generated analysis code may optionally assign a second reserved variable `export_df` (a full pandas DataFrame — e.g. a cleaned/filtered/ranked derivation) *in addition to* `result`. Trusted sandbox code (not the LLM's code — `open`/filesystem remain blocked for generated code) writes `export_df` to a temp parquet on disk locally and returns only aggregate metadata (`row_count`, `column_count`, `temp_path`) — never its rows — to `AgentState`. `finalize` then promotes it into a derived `Dataset` (see 3a `data.md` note). The full-row export file lives on the local disk and only crosses to the client on an **explicit** `GET /query-results/{id}/export` download over localhost — which is the user retrieving their own derived data to their own machine, never a network hop to the LLM provider. This is consistent with "raw data never leaves the machine": the constraint bars raw rows from reaching the *LLM provider* and from riding along in the *answer payload*; an explicit user download of their own file over localhost is the intended export feature, not a violation. Stated explicitly here so it is not mistaken for one.
  4. **Derived datasets reuse the existing `Dataset`/library machinery, not a parallel structure.** A promoted export is an ordinary `Dataset` row (with a `DatasetProfile` + a trivial empty `CleaningReport`) whose `derived_from_query_result_id` is set; it therefore shows up in `GET /datasets` (Phase 2) and is selectable/queryable exactly like an upload with no new code path.
  5. **Anomaly flags are NOT in 3a.** `anomaly_flags` remains `[]`/`None` (the Phase-1 stubbed field) until Phase 3b, so 3a's `compose_answer` change is limited to the `---ARTIFACTS---` block. Recorded so 3a does not accidentally pull 3b scope forward.

- **Independent slices (parallel build units — disjoint file ownership, no true cross-slice code dependency; each builds against the contracts in `spec/api.md`/`spec/data.md`/`spec/ui.md`, not against another slice's code):**
  - `artifacts-graph` (backend) — deps: none beyond the existing Phase-1/2 graph (no topology change). Produces table/chart from the capped result, captures `export_df`, and promotes an export into a derived `Dataset` in `finalize`. Owns exclusively:
    - `src/execution/sandbox.py` — after `exec`, if `namespace.get("export_df")` is a `pd.DataFrame`, trusted code writes it to a temp parquet (`AGENT_DATA_DIR/exports/_tmp/<uuid>.parquet`) and adds `export={"temp_path","row_count","column_count"}` to the returned dict; the capped `result` channel is unchanged. `export_df` rows never enter `result`/`stdout`.
    - `src/graph/nodes.py` — extend `compose_answer` to parse the `---ARTIFACTS---` block (new `_split_answer_sections(text) -> (prose, follow_ups, artifact_intent)` generalising the existing `_split_answer_and_follow_ups`); add `_build_table_data` / `_build_chart_spec` (deterministic, capped, from `execution_result` only); have `execute_code` pop `result["export"]` into `state["export_meta"]` and strip it from what is appended to `accumulated_summaries` (so no export path/metadata ever reaches a later prompt); extend `finalize` to persist `table_json`/`chart_spec_json` and, when `export_meta` is present, call `storage/exports.promote_export(...)`, create the derived `Dataset` + `DatasetProfile` (via `tools/profiling.build_profile`, imported read-only) + empty `CleaningReport`, set `query_result.export_dataset_id`, and write an `AuditLogEntry(event_type="answer", detail_json={..., "export_dataset_id": ...})`.
    - `src/graph/state.py` — add `export_meta: dict | None` (the `table_data`/`chart_spec`/`export_path`/`anomaly_flags` fields already exist, per `spec/agent.md`).
    - `src/config/settings.py` — add `chart_max_points: int` (`AGENT_CHART_MAX_POINTS`, default 100).
    - `src/storage/exports.py` (new) — `exports_dir(query_result_id)`, `promote_export(query_result_id, temp_path) -> {csv_path, parquet_path, row_count, column_count}` (reads the temp parquet, writes `export.csv` + `export.parquet` under `exports/<qr_id>/`, deletes the temp), `export_csv_path(query_result_id)`.
    - `src/prompts/compose_answer.md` — append the `---ARTIFACTS---` intent-JSON instruction (chart type + x/y column names + table on/off + titles; explicitly "intent only, never data values").
    - `src/prompts/generate_code.md` — document the optional `export_df` convention (assign a full derived DataFrame to `export_df` when the user asks for the data itself — a cleaned/filtered/ranked list — not just an aggregate; `result` is still always required).
    - `tests/unit/test_artifacts_nodes.py` (new) — pure unit tests (LLM mocked at `LLMClient.call_model_with_usage`) for `_split_answer_sections`, `_build_table_data`, `_build_chart_spec` (assert series capped to `AGENT_CHART_MAX_POINTS`, assert built only from `data_json`), and `execute_code`'s stripping of `export` from `accumulated_summaries`.
  - `export-download-api` (backend) — deps: none (reads the `Dataset`/`QueryResult` rows written by `artifacts-graph` at runtime, but shares no code; builds against the `spec/api.md` contract). Owns exclusively:
    - `src/api/query_results.py` (new) — `GET /query-results/{query_result_id}/export`: look up `QueryResult` → `export_dataset_id` → the derived `Dataset`; stream its `original_path` (the `export.csv`) as a `FileResponse` with `Content-Disposition: attachment; filename="<original>_derived.csv"`; `404` if the result has no export.
    - `src/api/__init__.py` — add `from api import query_results` and `app.include_router(query_results.router)` (this is the ONLY slice that edits this file this phase, so no collision with `artifacts-graph`).
    - `tests/unit/test_export_endpoint.py` (new) — create a `QueryResult` + a derived `Dataset` with an on-disk `export.csv` fixture against the real SQLite file DB; assert the endpoint streams the file with the attachment header and the exact byte content, and returns `404` for a result with no export.
  - `frontend-artifacts` (frontend) — deps: none (builds against `spec/api.md`/`spec/ui.md`; the `table`/`chart_spec`/`export_dataset_id` fields are already present in the Phase-1/2 `QueryResultOut` contract). Owns exclusively:
    - `frontend/src/components/ChartPanel.tsx` (new) — replaces the Phase-1 "Charts" `StubPanel`; renders `query_result.chart_spec` via `recharts` (bar/line/pie) from the `series` array; renders nothing (or an "no chart for this answer" caption) when `chart_spec` is null.
    - `frontend/src/components/ResultTable.tsx` (new) — renders `query_result.table` (`columns`/`rows`) as a scrollable ranked/summary table with a "showing N of M rows" caption when `truncated`.
    - `frontend/src/components/ExportButton.tsx` (new) — replaces the Phase-1 disabled "Export" stub; enabled only when `query_result.export_dataset_id` is non-null; on click, navigates/downloads `GET /query-results/{id}/export`; stays disabled with the "no export for this answer" tooltip otherwise.
    - `frontend/src/app/page.tsx` (modify) — swap the "Charts" and "Export" `StubPanel`s for `<ChartPanel>`/`<ResultTable>`/`<ExportButton>`; after an ask response whose `export_dataset_id` is non-null, force the Phase-2 `LibrarySidebar` to refetch by bumping a `libraryRefreshKey` passed as its React `key` (no edit to `LibrarySidebar.tsx` — disjoint from `frontend-library`). The "Cost tracking" / "Step tracking" / anomaly `StubPanel`s are untouched (they go live in 3b/3c).
    - `frontend/src/lib/types.ts` (modify) — add `ChartSpec`, `ChartPoint`, `TableData` types; `QueryResult.table`/`chart_spec`/`export_dataset_id` already typed from Phase 1's contract, now populated for real.
    - `frontend/package.json` (modify) — add `recharts` (^2) as the charting library.
    - `frontend/tests/e2e/phase3a.spec.ts` (new) — see Gate command below.

- **Schema note:** **No new Alembic migration is required for Phase 3a.** Every column 3a writes already exists in the head migration (verified against `src/db/models.py`): `Dataset.derived_from_query_result_id` (nullable FK → `query_results.id`), `QueryResult.table_json` / `chart_spec_json` / `export_dataset_id` / `anomaly_flags_json` (all nullable JSON/FK). 3a is the first *writer* of these existing-but-unused columns, not a schema change. See `spec/data.md` → "Phase 3a note".

- **Gate command(s):**
  1. `uv run alembic current` — confirm the DB is already at the Phase-1 head revision with no pending migration (no `alembic revision --autogenerate` this phase — see schema note).
  2. `uv run pytest tests/unit tests/integration -q` — full suite (all Phase 1/2 tests still pass, plus the new files), real `AGENT_GEMINI_API_KEY` from `.env`, real SQLite file DB, LLM mocked only in the new unit files:
     - `tests/integration/test_phase3a_artifacts.py` (new, real Gemini): uploads a fixture CSV of **10,000+ rows** with a categorical column of exactly 5 distinct values (`region`) and a known per-region revenue total; asks "Show me total revenue by region, ranked" → asserts the returned `query_result["table"]` has 5 rows matching the pre-computed per-region totals AND `query_result["chart_spec"]["series"]` has ≤ `AGENT_CHART_MAX_POINTS` points drawn from those aggregates (not 10,000). Then asks "Export the rows for the West region as a dataset" → asserts a non-null `export_dataset_id`, asserts the derived `Dataset` appears in `GET /datasets`, and asserts the **exported file's row count equals the full number of West-region rows** (not capped to 200) — proving the export is the full derived data while the chart/table remain capped. **Raw-data assertion:** captures every prompt string passed to `LLMClient.call_model_with_usage` during the run (via a spy) and asserts none contains a raw row value from the fixture (only aggregate profile fields + capped structured results), and that the `chart_spec.series` length ≤ cap.
     - `tests/unit/test_artifacts_nodes.py`, `tests/unit/test_export_endpoint.py` — as described above.
  3. `cd frontend && pnpm install && pnpm build` — `recharts` installs; CSS bundle contains real Tailwind utility selectors.
  4. `cd frontend && npx playwright test tests/e2e/phase3a.spec.ts --reporter=line` — against `http://localhost:8001/app/` with the backend running: upload the fixture, ask the ranked-by-region question, see a real chart render (an `<svg>`/recharts container, not the "coming soon" stub) and a real ranked table; ask the export question, click the now-enabled Export button and assert a file download is triggered; confirm the derived dataset now appears as a new checkbox in the Library sidebar without a manual reload.
  5. Structured request/response logging on stdout shows the single `compose_answer` call producing the artifacts (no extra LLM call for charts/tables) during the e2e run.
  6. Working tree clean and pushed.

- **How the user tests it (handoff seed):**
  1. `cd frontend && pnpm install && pnpm build`, then from the repo root `uv run python -m src`
  2. Open `http://localhost:8001/app/`, upload a CSV with a categorical column (e.g. `region`) and a numeric column (e.g. `revenue`)
  3. Ask "show me total revenue by region, ranked" — a **real ranked table** and a **real interactive chart** now render where the "coming soon" placeholders used to be (Charts stub is gone)
  4. Ask something like "export the West-region rows as a dataset" — the **Export** button (previously greyed) is now enabled; click it and a CSV downloads containing the **full** derived rows
  5. Notice the derived dataset now appears as a new entry in the Library sidebar automatically — select it and ask a question against it, exactly like an uploaded file
  6. Still-labelled stubs (not bugs): the "Cost tracking — coming soon" badge, the "Step tracking — coming soon" indicator, and anomaly banners remain stubbed (they go live in 3b/3c)

### Phase 3b — Proactive Quality & Audit Trail *(slice sketch)*

*(Requirements phase 3 of 4 remaining.)*

- **Goal:** While answering, the agent proactively surfaces anomalies / data-quality issues it noticed (e.g. a column with a suspicious null spike, an outlier, an inconsistent category), and the user can open an Audit History screen showing every question asked, code run, and result — the `AuditLogEntry` table already written since Phase 1 finally gets a UI.
- **Capabilities delivered:** `conversational-analysis` (anomaly flags complete the capability — charts/tables/exports already live as of 3a), `audit-and-cost-tracking` (audit-history UI portion; cost UI stays for 3c).
- **Independent slices (sketch):**
  - `anomaly-graph` (backend) — extend `compose_answer`'s existing single call to also emit an `---ANOMALIES---` block (zero extra LLM calls, mirroring 3a's `---ARTIFACTS---`); persist `anomaly_flags_json` in `finalize`. Owns `src/graph/nodes.py`, `src/prompts/compose_answer.md`.
  - `audit-api` (backend) — `GET /audit-log` (paginated, filterable by `session_id`/`dataset_id`, chronological). Owns `src/api/audit.py` (new) + its router registration; new `tests/unit/test_audit_endpoint.py`.
  - `frontend-audit` (frontend) — new Audit History screen + anomaly banners on the answer panel (replacing the anomaly `StubPanel`). Owns new `frontend/src/components/AnomalyBanner.tsx`, `frontend/src/app/history/page.tsx`, `frontend/tests/e2e/phase3b.spec.ts`; modifies `page.tsx`.
- **Gate command (sketch):** `uv run pytest tests/integration/test_phase3b_anomalies.py tests/unit/test_audit_endpoint.py -q` against real Gemini + real SQLite (fixture dataset with a deliberately anomalous column asserts a non-empty `anomaly_flags`; `GET /audit-log?session_id=...` returns a known run's entries in order); `npx playwright test tests/e2e/phase3b.spec.ts` covering the anomaly banner render and the history screen.
- **How the user tests it:** ask a question against a dataset with a known bad column and see an anomaly banner; open the History screen and see the prior questions/code/results listed.

### Phase 3c — Cost Accounting & Streaming *(slice sketch)*

*(Requirements phase 4 of 4 remaining — completes all requirements capabilities.)*

- **Goal:** Every answer shows its per-query token/cost estimate and a running session + all-time total, and answers stream in token-by-token with a live step-progress indicator as the graph executes — replacing the last two Phase-1 "coming soon" stubs.
- **Capabilities delivered:** `audit-and-cost-tracking` (cost/token UI + streaming complete the capability; `CostRecord`s have been written since Phase 1).
- **Independent slices (sketch):**
  - `cost-api` (backend) — `GET /cost-summary` (per-session + running-total from `CostRecord`). Owns `src/api/cost.py` (new) + router registration; new `tests/unit/test_cost_endpoint.py`.
  - `streaming-backend` (backend) — SSE endpoint `GET /sessions/{id}/messages/{message_id}/stream` emitting `step` events per node + `answer_chunk` events via Gemini streaming in `compose_answer`. Owns `src/api/sessions.py` (add the SSE route), `src/graph/runner.py` (emit step events), `src/llm/*` (streaming call). **Dep:** must not collide with any 3b edit to `nodes.py` — 3c's `compose_answer` streaming change and 3b's anomaly change both touch `compose_answer`; since 3b ships before 3c, 3c builds on 3b's merged `nodes.py` (sequential sub-phases, so no parallel collision).
  - `frontend-cost-stream` (frontend) — running-total cost badge (replaces the cost stub) + streamed answer text + live step-progress bar (replaces the step stub). Owns new `frontend/src/components/CostBadge.tsx`, `frontend/src/components/StepProgress.tsx`, `frontend/tests/e2e/phase3c.spec.ts`; modifies `page.tsx`.
- **Gate command (sketch):** `uv run pytest tests/integration/test_phase3c_cost.py tests/integration/test_phase3c_stream.py -q` against real Gemini + real SQLite (`GET /cost-summary` running total equals an independently-summed `CostRecord` total; the SSE stream emits ≥1 `step` event and reassembles to the final answer); `npx playwright test tests/e2e/phase3c.spec.ts` covering the streamed answer + live step counter + cost badge.
- **How the user tests it:** ask a question and watch the answer stream in with a live step counter; see the per-query cost and a running total that increases with each question.

### Phase 4 — Hardening & Production Readiness *(trailing phase)*

- **Goal:** The system is safe and fast under its stated hard constraints, not just functionally complete.
- **Scope:** Confirm/handle a genuine 100MB CSV end-to-end within the storage and memory budget; measure and enforce the sub-30s latency budget on the single-call path (regression test with a timing assertion); security review of the sandboxed executor (attempt known escape patterns — `__import__`, `os.system`, dunder attribute traversal, oversized `result` payloads — and assert each is rejected or capped); log rotation/retention policy for the audit log; README/`.env.example` final pass.
- **Gate command (sketch):** `uv run pytest tests/security/test_sandbox_escapes.py tests/performance/test_latency_budget.py -q` against the real Gemini key and a real 100MB fixture CSV (generated once and cached under `tests/fixtures/`).
- **How the user tests it:** upload a real ~100MB export and confirm profiling/answering still completes within the stated budget; no separate UI change expected.
