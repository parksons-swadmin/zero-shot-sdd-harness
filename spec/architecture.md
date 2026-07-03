# Architecture

---

## System Overview

A single-user, locally-run FastAPI service backed by SQLite, fronted by a Next.js static-export UI served at `/app`. The user uploads a CSV; the backend cleans and profiles it with real pandas code running against the full file; the user asks questions in natural language, which a LangGraph agent answers by having Gemini write pandas analysis code, running that code locally in a guarded sandbox against the real dataframe, and having Gemini compose the final plain-language answer from the code's structured (never raw-row) output. Everything the agent does — questions, code, results, cost — is written to a persistent audit trail.

## Component Map

```
Browser (Next.js static export, served at :8001/app/)
    │  fetch() — multipart upload / JSON ask
    ▼
FastAPI app (:8001)
    │
    ├── api/datasets.py    ── upload, list, profile detail
    ├── api/sessions.py    ── ask (runs the graph), session/message history
    ├── api/audit.py       ── audit log + cost summary (Phase 3)
    │
    ▼
graph/runner.py → graph/agent.py (LangGraph StateGraph)
    │
    ├── tools/cleaning.py, tools/profiling.py   (trusted, our code — runs on FULL dataframe)
    ├── llm/client.py → llm/providers/gemini.py (Gemini calls — schema/summary + code/results ONLY)
    └── execution/code_guard.py + execution/sandbox.py  (LLM-authored code — runs on FULL dataframe, real data never returns raw)
    │
    ▼
db/session.py (SQLAlchemy) ──→ SQLite file (AGENT_DATABASE_URL)
storage/files.py ──→ local filesystem (AGENT_DATA_DIR) — original + cleaned CSVs, exports
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| API (`src/api/`) | HTTP boundary: validation, response envelope, maps requests to graph runs / tool calls |
| Graph (`src/graph/`) | Orchestrates the adaptive reasoning loop (see `spec/agent.md`) |
| Tools (`src/tools/`) | Trusted, non-LLM-generated code: cleaning, profiling — always operates on the full dataframe |
| Execution (`src/execution/`) | Sandboxes and guards LLM-*generated* analysis code before/while it runs against the full dataframe |
| LLM (`src/llm/`) | Single choke point for every Gemini call; the only code allowed to build a prompt string |
| Storage (`src/storage/`) | Local filesystem layout for uploaded/cleaned/exported files |
| DB (`src/db/`) | SQLAlchemy models + session management against SQLite |

## Data Flow

1. Trigger: user uploads a CSV via the browser.
2. `api/datasets.py` streams the file to disk (`storage/files.py`), then `tools/cleaning.py` and `tools/profiling.py` run against the **full** file and write `Dataset`, `CleaningReport`, `DatasetProfile` rows. An `AuditLogEntry` is written for `upload`, `clean`, `profile`.
3. User asks a question. `api/sessions.py` invokes `graph/runner.py`, which loads the relevant `DatasetProfile`(s) (never raw rows) and any prior `Message` history into `AgentState`, and runs the graph described in `spec/agent.md`.
4. The graph has Gemini generate pandas code from the profile + question, executes it locally against the real dataframe via `execution/sandbox.py`, and has Gemini compose the final answer from the sandbox's structured, size-capped result.
5. Output: a `Message` (assistant) + `QueryResult` (summary, key numbers, code, artifacts) are persisted; `CostRecord`(s) and `AuditLogEntry`(entries for `ask`, `code_exec`, `answer`) are written; the API returns the `QueryResult` to the browser.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Gemini API (`AGENT_GEMINI_API_KEY`) | Code generation, query classification/planning, answer composition | Node catches the exception, sets `state.error`, routes to `handle_error`; API returns a readable error, never a raw stack trace; `AuditLogEntry` records the failure |
| Local filesystem (`AGENT_DATA_DIR`) | Stores original/cleaned CSVs and exports | Upload rejected with a clear error if disk write fails or the 100MB cap is exceeded (413) |
| SQLite (`AGENT_DATABASE_URL`) | All persisted state: datasets, profiles, sessions, messages, results, audit log, cost | Connection failure fails the request with a 500 and is logged; the app fails fast at startup if the DB file's directory is not writable |

## Stack

- **Language:** Python 3.12+ (backend, matches the existing skeleton); TypeScript (frontend, Next.js).
- **Agent framework:** LangGraph — chosen because the adaptive reasoning loop (single-call vs. iterative-refine vs. full-plan, with bounded escalation) is exactly the conditional, stateful multi-step flow LangGraph is built for. See `spec/agent.md` for the full graph.
- **LLM provider + model:** Google Gemini (per intake decision; `AGENT_GEMINI_API_KEY` in `.env`). Default model `gemini-3.1-pro` for code generation, planning, and answer composition (quality-sensitive nodes); `gemini-2.5-flash` for the cheap/fast `classify_query` router (Phase 2+) — a latency/cost trade-off, not a quality one, since it only picks a reasoning mode. Both are env-configurable (`AGENT_LLM_MODEL`, `AGENT_LLM_ROUTER_MODEL`) per the model-naming rule in `harness/patterns/tech-stack.md`.
- **Backend:** FastAPI (existing skeleton).
- **Database + ORM:** SQLite + SQLAlchemy 2.0 (existing skeleton).
  > **Assumed:** SQLite is the correct choice per `harness/patterns/tech-stack.md`'s default ("SQLite only for an explicitly local/single-user tool") — this agent is explicitly single-user and local, and the intake brief itself specified "Python + SQLite (defaults from skeleton)". SQLite's single-writer limitation is addressed below under Concurrency.
- **Frontend:** Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`) served by FastAPI at `:8001/app/` (existing skeleton pattern).
- **Dependency management:** uv (Python) / pnpm (TypeScript) (existing skeleton).
- **Observability:** structured JSON logging via `structlog` (existing `src/observability/events.py`) to stdout for every LLM call (prompt size, model, latency, token usage, status) and every graph node transition — wired from Phase 1. LangSmith tracing is **not** added: the app already has first-party structured logging via `structlog` covering every node and every LLM call, which meets the "observability wired from day one" bar; LangSmith would duplicate this without adding a capability the roadmap needs. > **Assumed:** structured stdout logging (already scaffolded) is the sole observability mechanism; LangSmith is not introduced.

| Key library | Version | Purpose |
|-------------|---------|---------|
| `pandas` | >=2.2 | Cleaning, profiling, and the dataframe the sandbox executes analysis code against |
| `numpy` | >=1.26 | Available inside the sandbox namespace for generated code |
| `google-genai` | >=2.9.0 | Gemini client (existing skeleton dependency) |
| `langgraph` | >=0.1 | Agent graph (existing skeleton dependency) |
| `python-multipart` | >=0.0.9 | FastAPI file-upload parsing |
| `pyarrow` | >=16.0 | Fast columnar storage for cleaned datasets (`.parquet`) |

**Avoid:** any library that grants the sandbox network access (`requests`, `httpx`, `urllib3`) must never be imported inside `src/execution/` — enforced by the AST guard below, not just convention. No ORM "repository pattern" (per `harness/patterns/project-layout.md` rule 2) — direct SQLAlchemy queries in API handlers and graph nodes.

## Deployment Model

Long-running local process: `uv run python -m src` serves the API and the built static frontend on port 8001. No containerization or cloud deployment in scope — this is a personal tool run on the user's own machine, which is also why the raw-data-never-leaves-the-machine constraint is meaningful (data literally never crosses a network boundary except the LLM call itself).

---

## The Raw-Data-Never-Leaves-The-Machine Boundary (Structural Enforcement)

**Hard constraint:** row-level values from an uploaded file must never appear in any Gemini API call. This is enforced structurally, not by convention, at four points:

1. **The LLM only ever sees typed summary objects, never a DataFrame.** `src/llm/client.py`'s `LLMClient.call_model(prompt: str, ...)` only accepts a `str`. Every prompt string fed to it is built by a small set of prompt-builder functions in `src/graph/nodes.py` that accept only `DatasetProfile` (aggregate column stats — see `spec/data.md`) and `ExecutionResult` (the sandbox's capped structured output) domain objects — never a `pandas.DataFrame`, never a raw file path read directly into a prompt. There is no code path in the graph that serializes an uploaded file's rows into a string destined for `call_model`.

2. **Profiling computes aggregates over the full data, never a row sample.** `src/tools/profiling.py` (`build_profile(df) -> DatasetProfile`) computes, per column: dtype, null count, distinct count, and for numeric columns min/max/mean/median, for low-cardinality categorical columns the top-5 value **counts** (a count is an aggregate, not a row) — all computed with `df.describe()`/`.isnull().sum()`/`.value_counts()` over the **entire** dataframe. It never calls `.head()`/`.sample()`/`.to_dict(orient="records")` on the raw dataframe as a way to "show the LLM some examples." This `DatasetProfile` object is the only representation of the data's shape the LLM ever receives.

3. **Generated analysis code executes locally with the real dataframe in scope, but its return channel is capped and structural.** `src/execution/sandbox.py`'s `run_analysis_code(code, dataframes, timeout_s) -> ExecutionResult` runs Gemini-authored code against the actual pandas dataframe(s) loaded from disk. The code must assign its answer to a reserved `result` variable. If `result` is a DataFrame/Series, it is converted via `.head(RESULT_ROW_CAP)`/`.to_dict()`, capped at `RESULT_ROW_CAP=200` rows and `RESULT_CELL_CAP=2000` cells (both env-configurable); captured `stdout` is similarly length-capped. This capped `ExecutionResult` is the *only* thing that crosses back into `AgentState`, and therefore the only thing `compose_answer`/`check_result` can ever interpolate into a subsequent Gemini prompt. There is no code path where the executor's full DataFrame, or a full `.to_csv()`/`.to_json()` dump of it, is available to a prompt-builder.

4. **Static + runtime guard on the sandbox closes the "LLM writes code that exfiltrates rows" loophole.** Before executing any Gemini-authored code, `src/execution/code_guard.py` parses it with `ast.parse` and rejects (raises `UnsafeCodeError`, routes to `handle_error`) any of: an `Import`/`ImportFrom` outside the allowlist `{pandas, numpy, math, statistics, datetime, re, json, collections}`; any `Name`/`Attribute` referencing `os`, `sys`, `socket`, `subprocess`, `shutil`, `pathlib`, `requests`, `urllib`, `http`, `ftplib`, `__import__`, `eval`, `exec`, `compile`, `open`, `input`; any dunder-prefixed attribute access. The code then runs in a `multiprocessing.Process` (cross-platform — works on Windows and POSIX) whose namespace's `__builtins__` is an explicit allow-listed subset (no `open`, `eval`, `exec`, `__import__`) and which never has `socket`/`requests`/`urllib` bound — so even a guard bypass has no network-capable module available to call. A hard wall-clock timeout (`AGENT_SANDBOX_TIMEOUT_S`, default 25s) kills the process via `.terminate()` on overrun. This defense-in-depth (block network entirely) is stronger than the stated requirement (no *rows* to Gemini) and simpler to verify.

Together: (1) makes it structurally impossible for a raw dataframe to reach the prompt-building code even by an implementation mistake; (2) and (3) guarantee only aggregates/capped-results ever exist in a form (2) could pass to (1); (4) prevents the one remaining attacker-controlled surface — LLM-generated code — from both reading arbitrary rows-back-out via a huge uncapped result (closed by the cap in (3)) or exfiltrating rows over the network directly (closed by the import/network guard).

## File Storage Layout

```
${AGENT_DATA_DIR}/                       (default ./data, gitignored)
├── agent.db                             (SQLite — AGENT_DATABASE_URL=sqlite:///./data/agent.db)
├── uploads/
│   └── <dataset_id>/
│       ├── original.csv                 (byte-for-byte as uploaded, never mutated)
│       └── cleaned.parquet              (post-cleaning, loaded for profiling + analysis)
└── exports/
    └── <query_result_id>/
        └── export.csv                   (Phase 3 — derived/exported dataset, becomes a new Dataset row)
```

Upload handling: the file is streamed to `original.csv` in chunks (never fully buffered in memory); requests exceeding `AGENT_MAX_UPLOAD_BYTES` (default `100_000_000`) are rejected with HTTP 413 before the write completes. Cleaning/profiling then loads the **full** file into a pandas DataFrame — a 100MB CSV (a few million rows of typical CRM/ops data) fits comfortably in memory on a personal machine; no row-sampling is used at any stage (see Phase-1 gate in `spec/roadmap.md`, which specifically tests this with a 10,000+ row fixture).

## Streaming Approach (Phase 3)

Phase 1 is synchronous request/response (fits the sub-30s single-call budget; no streaming needed). Phase 3 adds a Server-Sent-Events endpoint (`GET /sessions/{id}/messages/{message_id}/stream`) that emits: (a) a `step` event after every graph node completes (`step_count`, `step_label`) for the live progress indicator, and (b) token-level `answer_chunk` events by using Gemini's streaming `generate_content` call inside `compose_answer`. Phase 1's UI stub for this is a static, clearly-labelled "coming soon" progress bar — never a fake animation.

## Cost / Token Estimation Approach

`src/llm/client.py`'s `LLMClient.call_model` reads `response.usage_metadata.prompt_token_count` / `.candidates_token_count` from every Gemini response and returns them alongside the text. Every graph node that calls the LLM writes one `CostRecord` row (`provider="gemini"`, `model`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`) computed via a configurable price table (`AGENT_GEMINI_INPUT_PRICE_PER_1K`, `AGENT_GEMINI_OUTPUT_PRICE_PER_1K` env vars). This is wired and real starting Phase 1 (writes happen on every call) even though the UI that displays it is a Phase-1 stub and goes live in Phase 3.
> **Assumed:** the per-1K-token price env-var defaults are placeholders set from public Gemini pricing at spec-writing time; they must be re-verified against current Gemini pricing before the Phase 3 cost UI is shown to the user, since prices change.

## Concurrency

SQLite is opened in WAL mode (`PRAGMA journal_mode=WAL`) to allow concurrent reads during a write. Because this is a single local user asking "a few times a day," the app does not add a job queue: `graph/runner.py` acquires an in-process lock keyed by `session_id` before invoking the graph and releases it in a `finally`; a second request for the same session while one is in flight gets `409 Conflict` ("A question is already being answered for this dataset — wait for it to finish"). Different sessions (different datasets) may run concurrently. No LangGraph parallel-node fan-out is used — each node's output is a genuine input to the next (sequential ReAct-style loop), so parallelizing nodes would add complexity without benefit (see `spec/agent.md`).
