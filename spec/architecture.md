# Architecture

> A fully-local, deterministic, **no-LLM, no-network, stateless** AR aging dashboard. Nothing leaves the machine. The HOW (stack, libraries, graph) lives here and in [agent.md](agent.md); the product narrative stays in the capability/roadmap/data/api/ui files.

---

## System Overview

A single-user runs one local process (`uv run python -m src`) that serves both a JSON API and a static Next.js dashboard at `http://localhost:8001/app/`. The user uploads an AR aging `.xlsx`, confirms an auto-detected column mapping, and gets an interactive dashboard whose every number is computed with deterministic pandas and ties out exactly to the source file. There is **no LLM, no external API, no database, and no network egress** — the file is parsed in memory, computed, rendered, and discarded.

## Component Map

```
Browser (Next.js static export @ /app)
   │  POST /api/preview   (file → proposed mapping + preview)
   │  POST /api/compute   (file + confirmed mapping → DashboardResult)
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
| API (FastAPI) | `/api/preview`, `/api/compute` (+ Phase-3 `/api/compute/stream`, `/api/export/*`); response envelope; error rendering; serves `/app` |
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

**Removed from the skeleton:** `anthropic`, `google-genai` (no LLM); `sqlalchemy`, `alembic` (no DB). Delete `src/llm/`, `src/db/`, `alembic/`, `alembic.ini`, `src/prompts/transform.md`, and `src/api/runs.py`. Rewrite `src/graph/*` per [agent.md](agent.md) and `src/graph/runner.py` to be DB-free.

**Avoid:**
- Any LLM/AI call, any network request, any telemetry — violates "nothing leaves the machine."
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
| `AGENT_AS_OF` | (unset → today) | Optional reproducibility override for the aging reference date; when unset, the pipeline uses `date.today()`. Used to reproduce the bundled demo/tests deterministically. |
| `PORT` | `8001` | Server port |

**`.env` needs NO API keys.** `.env.example` is rewritten to contain only the above (with defaults) — no provider or database entries.

## Deployment Model

A single local process, run on the user's own machine: `uv run python -m src` serves the API and the pre-built static frontend at `http://localhost:8001/app/`. No cloud, no container required, no external services. Fully offline-capable.
