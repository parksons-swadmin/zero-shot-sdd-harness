# Architecture

> A fully-local, deterministic, **no-LLM, stateless** AR aging dashboard. The **interactive app** makes **no network egress — nothing leaves the machine**. There is exactly one deliberate, opt-in exception — the Phase-5 [scheduled email report](capabilities/scheduled_email_report.md), the single authorized egress path (off unless SMTP is configured; see [Network egress — scope of the guarantee](#network-egress--scope-of-the-guarantee)). The HOW (stack, libraries, graph) lives here and in [agent.md](agent.md); the product narrative stays in the capability/roadmap/data/api/ui files.

---

## System Overview

A single-user runs one local process (`uv run python -m src`) that serves both a JSON API and a static Next.js dashboard at `http://localhost:8001/app/`. The user uploads an AR aging `.xlsx`, confirms an auto-detected column mapping, and gets an interactive dashboard whose every number is computed with deterministic pandas and ties out exactly to the source file. For the interactive app there is **no LLM, no external API, no database, and no network egress** — the file is parsed in memory, computed, rendered, and discarded. (The single exception is the opt-in Phase-5 scheduled email report — see [Network egress — scope of the guarantee](#network-egress--scope-of-the-guarantee) — which is off unless SMTP is configured.)

## Component Map

```
Browser (Next.js static export @ /app)
   │  POST /api/preview    (file → proposed mapping + preview)
   │  POST /api/compute    (file + confirmed mapping → DashboardResult)
   │  POST /api/invoices   (file + mapping + optional filters → DrilldownResult)   ← Phase 4
   ▼
FastAPI (src/api)  ── serves frontend/out at /app
   │
   ▼
LangGraph deterministic pipeline (src/graph)   ← NO LLM
   ingest → validate → compute → flag → assemble   (+ handle_error)
   │
   ▼
Pure functions (src/tools): header_detect (rapidfuzz), ingest (openpyxl/pandas),
                            validate, metrics (vectorized int64), flags
   │
   ▼
In-memory pandas DataFrame  →  AgingMetrics (JSON)  →  discarded at end of request
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| Frontend (Next.js static export) | Upload, mapping-confirmation, dashboard rendering, INR formatting, exports |
| API (FastAPI) | `/api/preview`, `/api/compute` (+ Phase-3 `/api/compute/stream`, `/api/export/*`; + Phase-4 `/api/invoices`); response envelope; error rendering; serves `/app` |
| Graph (LangGraph, deterministic) | Orchestrates the fixed ingest→validate→compute→flag→assemble pipeline |
| Tools (pure functions) | Header detection, workbook read, normalization, validation, exact metrics, rule-based flags |
| Observability (structlog) | Structured per-node/per-request JSON logs (counts + timings only) |

## Data Flow

1. **Trigger:** user selects a `.xlsx` in the browser.
2. `POST /api/preview` → read workbook (openpyxl/pandas) → `detect_mapping` (rapidfuzz) → return sheets, columns, proposed mapping (with confidence tiers), 10-row preview, parse-time flags. **Server keeps nothing.**
3. User reviews/corrects the mapping and clicks Confirm (human-in-the-loop checkpoint).
4. `POST /api/compute` (same file bytes + confirmed mapping) → runner builds `AnalysisState` (`as_of = date.today()`) → invoke the deterministic graph → `AgingMetrics` / `DashboardResult`. The aging reference date resolves by precedence **explicit `as_of` param (tests) > `AGENT_AS_OF` (optional reproducibility override) > `date.today()` (default)**; real uploads with the var unset always age to today.
5. **Output:** JSON `DashboardResult` → KPI tiles + Top-20 chart (Phase 1) → later phases add employee summary, breakdowns, flags, exports. File and DataFrame are discarded.

## Statelessness & the mapping round-trip

There is **no server-side cache or session**. The client re-sends the file on `/api/compute`. Over loopback this is negligible for a local tool, and it makes both endpoints pure functions of their inputs — trivial to test and impossible to drift into hidden state. On any structural failure the pipeline returns a clean error; the user re-uploads.

## Exact tie-out guarantee

Every amount is converted once to **integer paise** (`int(Decimal(str(a)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)`) and **all** aggregation is integer `int64` — no float accumulation, so totals are bit-exact and independent of row count/order. No sampling, no `head(N)`, no truncation: every metric is computed over the full frame. See [aging_metrics_engine.md](capabilities/aging_metrics_engine.md).

## Large-file handling

`ar_large.xlsx` (≥60,000 rows) is read with pandas/openpyxl and computed with vectorized int64 ops in well under the 15s budget. Upload is capped by `AGENT_MAX_UPLOAD_MB` (25) and `AGENT_MAX_ROWS` (200000) with a clear error when exceeded. Phase 3 adds an SSE progress stream (`/api/compute/stream`) with live row counts; Phases 1–2 compute synchronously.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| (none — no network, no LLM, no DB, no third-party service) | — | The tool is fully self-contained; the only failure surfaces are a malformed/oversized file or an incomplete mapping, both returned as clean API errors |
| SMTP server (Office 365) — **Phase 5, optional, egress** | Send the daily report PDF by email — the single authorized egress path; the interactive app/server never calls it | Send failure → the standalone job logs the error and exits non-zero (PDF already saved locally). Unconfigured → the job dry-runs (no send). See [scheduled_email_report.md](capabilities/scheduled_email_report.md). |

## Network egress — scope of the guarantee

The "nothing leaves the machine / no network egress" guarantee is **scoped to the interactive app** — the FastAPI server, the LangGraph compute pipeline, and the browser dashboard. Along that whole path the uploaded AR file is parsed in memory, computed, rendered, and discarded; no request ever reaches the network, and no data is persisted.

There is **exactly one deliberate, user-authorized exception**: the Phase-5 [scheduled email report](capabilities/scheduled_email_report.md). It is a **separate, standalone Node/Playwright job** (not the app/server request path) that, on a schedule or on demand, renders the dashboard to a PDF and **emails that PDF via SMTP** — deliberately sending confidential AR data (customer names + balances) **off the machine**. This egress is:

- **Opt-in and off by default** — it sends nothing unless the user configures SMTP (`AGENT_SMTP_HOST`/`AGENT_SMTP_USER`/`AGENT_SMTP_PASSWORD`/`AGENT_REPORT_TO`); otherwise it dry-runs (render + save PDF locally, no send). A `--dry-run` flag forces no-send.
- **The only outbound connection anywhere** — no LLM, no telemetry, no third-party API; SMTP send is the single sanctioned network call, and it never originates from the app/server.
- **Handling a secret** — `AGENT_SMTP_PASSWORD` is an app password kept in `.env` (never committed), never logged.

## Stack

> Concrete choices for **this** project. Generic rules (dev port 8001, static-export/styling, Playwright E2E, DB-driver placement) live in `harness/patterns/tech-stack.md`.

- **Language:** Python 3.11+ (skeleton `requires-python >=3.11`).
  > **Assumed:** target Python 3.12 for dev; keep the `>=3.11` floor from the skeleton.
- **Agent framework:** LangGraph `StateGraph` — **deterministic, no-LLM** (kept from the skeleton; see [agent.md](agent.md)).
- **LLM provider + model:** **NONE.** No provider, no model, no API key. The `src/llm/` package and the `anthropic` + `google-genai` dependencies are **removed**.
- **Backend:** FastAPI + uvicorn (from the skeleton), serving the static frontend at `/app`.
- **Database + ORM:** **NONE.** SQLAlchemy, Alembic, `src/db/`, and `alembic/` are **removed** — the tool is stateless (see [data.md](data.md)). No `alembic upgrade head` in any gate.
- **Frontend:** Next.js 15 + React 19 + Tailwind v4, static export (`output: 'export'`, `basePath: '/app'`, `trailingSlash: true`) served by FastAPI — unchanged from the skeleton's model.
- **Charting:** Recharts (SVG — prints cleanly for PDF export).
- **Excel read:** pandas + openpyxl. **Excel write (Phase 3):** openpyxl (same lib, multi-sheet + Indian number formats).
  > **Assumed:** openpyxl for both read and write (one dependency) rather than adding xlsxwriter.
- **Fuzzy header matching:** rapidfuzz (`token_sort_ratio`), deterministic.
- **PDF export (Phase 3):** client-side `window.print()` + a `@media print` stylesheet — no server renderer, no system deps (see [pdf_export.md](capabilities/pdf_export.md)).
- **Scheduled email report (Phase 5, opt-in):** a standalone Node job (`frontend/scripts/daily-report.mjs`) that reuses the already-present Playwright **Chromium** API to render the same print layout to PDF headlessly, and **`nodemailer`** for the SMTP send. Env is loaded by the script itself — a cwd-independent hand-parse of the repo-root `.env`, with real `process.env` taking precedence (not `node --env-file=.env`); scheduled by a Windows Scheduled Task (`scripts/register-daily-report-task.ps1`). This is the only component that opens a network connection — see [Network egress — scope of the guarantee](#network-egress--scope-of-the-guarantee) and [scheduled_email_report.md](capabilities/scheduled_email_report.md).
- **Dependency management:** uv + `pyproject.toml` (Python); pnpm (frontend).
- **Observability:** structlog (already wired) — structured JSON logs to stdout; no LangSmith (no LLM).

| Key library | Version | Purpose |
|-------------|---------|---------|
| fastapi | ≥0.115 | HTTP API + static mount |
| uvicorn[standard] | ≥0.30 | ASGI server (port 8001) |
| langgraph | ≥0.1 | Deterministic pipeline graph |
| pandas | ≥2.2 | Vectorized in-memory computation |
| openpyxl | ≥3.1 | `.xlsx` read + write |
| rapidfuzz | ≥3.9 | Fuzzy header matching |
| python-multipart | ≥0.0.9 | FastAPI file/form upload parsing |
| pydantic / pydantic-settings | ≥2.7 / ≥2.3 | Domain models + settings (`AGENT_` prefix) |
| structlog | ≥24.1 | Structured logging |
| recharts (frontend) | ≥2.12 | Bar chart + breakdown charts |
| nodemailer (frontend, Phase 5) | ^9.0.3 | SMTP send for the opt-in scheduled email report |

**Removed from the skeleton:** `anthropic`, `google-genai` (no LLM); `sqlalchemy`, `alembic` (no DB). Delete `src/llm/`, `src/db/`, `alembic/`, `alembic.ini`, `src/prompts/transform.md`, and `src/api/runs.py`. Rewrite `src/graph/*` per [agent.md](agent.md) and `src/graph/runner.py` to be DB-free.

**Avoid:**
- Any LLM/AI call, or any network request **from the interactive app** (telemetry, external API) — violates "nothing leaves the machine." The **only** sanctioned network call anywhere is the opt-in Phase-5 SMTP send in the standalone report job — never from the app/server request path.
- Float accumulation for money — use integer paise (tie-out).
- Sampling / `head(N)` / row truncation in compute — every number must reflect the full file.
- Re-introducing SQLite/Postgres or a server-side cache — the tool is stateless by design.
- DSO / any sales-based metric — no sales column exists (see [roadmap.md](roadmap.md)).

## Settings (`AGENT_` prefix, `src/config/settings.py`)

Rewritten to drop all provider/DB keys. Fields (all optional, sensible defaults):

| Setting | Default | Purpose |
|---------|---------|---------|
| `AGENT_LOG_LEVEL` | `INFO` | structlog level |
| `AGENT_MAX_UPLOAD_MB` | `25` | Upload size cap |
| `AGENT_MAX_ROWS` | `200000` | Row-count cap |
| `AGENT_HEADER_MATCH_THRESHOLD` | `85` | rapidfuzz high-confidence cutoff |
| `AGENT_RISK_TOP_N` | `5` | Riskiest-accounts count (Phase 2) |
| `AGENT_DRILLDOWN_MAX_ROWS` | `1000` | Max invoice rows returned by `POST /api/invoices` (Phase 4); the full filtered `total_count`/`subtotal_amount` are always reported regardless of this cap |
| `AGENT_AS_OF` | (unset → today) | Optional reproducibility override for the aging reference date; when unset, the pipeline uses `date.today()`. Used to reproduce the bundled demo/tests deterministically. |

> **`PORT` is NOT an `AGENT_`-prefixed Settings field.** It is a plain/bare env var read directly via `os.environ.get("PORT")` (default `8001`) — used for the E2E harness / port override. It lives outside the `AGENT_`-prefixed `Settings` model above.

**The interactive app needs NO API keys.** `.env.example` contains the above (with defaults) — no provider or database entries. The only secret anywhere in the project is the optional Phase-5 SMTP app password below, used solely by the standalone email-report job.

### Scheduled-report settings *(Phase 5 — consumed by the Node job, not the Python `Settings` model)*

The optional daily email report ([scheduled_email_report.md](capabilities/scheduled_email_report.md)) reads its configuration from the environment. The script loads the repo-root `.env` itself — a cwd-independent hand-parse, with any pre-set `process.env` value taking precedence over the file (not `node --env-file=.env`). These are **not** part of the `AGENT_`-prefixed pydantic `Settings` above (that model serves the interactive backend) — they configure the standalone Node/Playwright job.

| Setting | Default | Purpose |
|---------|---------|---------|
| `AGENT_REPORT_WATCH_DIR` | (required for the job) | Folder watched for the newest AR `.xlsx` (e.g. `D:\Cowork\AR Dashboard Data`); `~$*` lock files and non-`.xlsx` ignored |
| `AGENT_REPORT_TO` | (required to send) | Recipient email (e.g. `sabyasachi.thakur@parksonspackaging.com`) |
| `AGENT_REPORT_FROM` | falls back to `AGENT_SMTP_USER` | From address |
| `AGENT_SMTP_HOST` | (required to send) | SMTP host (Office 365: `smtp.office365.com`) |
| `AGENT_SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `AGENT_SMTP_USER` | (required to send) | SMTP username |
| `AGENT_SMTP_PASSWORD` | **secret — no default** | SMTP **app password**. **Secret: lives in `.env`, never committed, never logged/echoed.** |

> When any of `AGENT_SMTP_HOST` / `AGENT_SMTP_USER` / `AGENT_SMTP_PASSWORD` / `AGENT_REPORT_TO` is unset, the job runs as a **dry-run** (render + save the PDF locally, no send); a `--dry-run` CLI flag forces dry-run regardless of config.
> **Assumed:** the PDF output location defaults to the OS temp directory (optional override `AGENT_REPORT_OUT_DIR`), and the job boots its own backend on an isolated port (default `8971`, optional override `AGENT_REPORT_PORT`). Both are convenience defaults, not required config, so the seven settings above stay the documented surface.

## Deployment Model

A single local process, run on the user's own machine: `uv run python -m src` serves the API and the pre-built static frontend at `http://localhost:8001/app/`. No cloud, no container required, no external services. The interactive app is **fully offline-capable**; only the opt-in Phase-5 scheduled email report (a separate, on-demand/scheduled Node job) makes an outbound SMTP connection, and only when the user configures it.
