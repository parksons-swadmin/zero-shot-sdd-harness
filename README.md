# AR Aging Dashboard

A fully-local, deterministic desktop dashboard for **Accounts Receivable (AR) aging**.

Upload an AR aging export (`.xlsx`), confirm the auto-detected column mapping, and get an
exact, interactive dashboard — headline KPIs, a Top-20-customers-by-overdue chart, an
employee-wise summary, per-customer / per-employee aging breakdowns with weighted-average
days-overdue, proactive risk flags, and a data-quality audit list.

**Nothing leaves the machine.** No LLM, no external API, no database, no network egress.
Every number ties out **exactly** to the source file (integer-paise arithmetic — no float
drift, no sampling, no truncation).

---

## What it does

- **Upload → Map → Compute.** Fuzzy-matches the six required columns (customer, invoice no,
  invoice date, due date, amount, salesperson) and asks you to confirm; low-confidence
  matches are flagged before compute. Two stateless calls (`/api/preview`, `/api/compute`);
  the server keeps nothing.
- **Exact tie-out.** All money is converted once to integer paise and summed over the full
  sheet, so totals are bit-exact regardless of row count or order. Handles ≥60,000-row files
  with no sampling.
- **Embedded summary-row exclusion.** SAP-style "Totals" / "Grand Total" rows embedded in the
  sheet body are detected and excluded from aggregation (never silently dropped — the excluded
  count is surfaced transparently), so totals never inflate.
- **Indian currency formatting.** ₹ INR with lakh/crore digit grouping.

### Phases

| Phase | Delivered | Surfaces |
|-------|-----------|----------|
| **1 — Headline dashboard** | Upload → confirm mapping → five KPI tiles + Top-20-by-overdue chart, exact tie-out. | done |
| **2 — Employees + breakdown + flags** | Employee-wise ranked summary; per-customer & per-employee aging breakdown with weighted-average days-overdue; proactive riskiest-account flags; full data-quality audit list. | done |
| **3 — Exports + progress** | Multi-sheet Excel export, print-ready PDF, large-file progress bar. | planned |

**What Phase 2 added (this increment):**

- **Employee-wise summary** — each salesperson's total outstanding, total overdue, % overdue,
  worst aging bucket, and invoice count, ranked by outstanding descending (with a visible
  `(blank)` row for unassigned invoices). The per-employee outstanding sums exactly to the
  overall total (partition invariant).
- **Group aging breakdown + weighted-average days-overdue** — per-customer and per-employee
  bucket totals (current / 0-30 / 31-60 / 61-90 / 90+) plus an amount-weighted mean of
  days-past-due over each group's *overdue* invoices. A group with no overdue balance returns
  `null` (rendered `—`), never a fabricated `0`.
- **Proactive risk flags** — the riskiest accounts, ranked by total `90+` overdue amount
  descending (top N via `AGENT_RISK_TOP_N`, default 5), each labelled `largest 90+ overdue`.
- **Data-quality audit list** — every flagged / unparseable row (missing due date, negative
  amount, zero amount, blank employee, etc.) listed by its original row index and reason —
  nothing is hidden and nothing is dropped. Flags are advisory: they never change the totals.

---

## Requirements

- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js + [`pnpm`](https://pnpm.io/) (for the frontend static export)

There are **no API keys** — the tool is fully offline and has no LLM or external provider.

---

## Running it

Build the frontend static export once, then boot the server (it serves the UI at `/app`):

```bash
cd frontend; pnpm build; cd ..; uv run python -m src
```

Then open **http://localhost:8001/app/**.

Upload `tests/fixtures/ar_small.xlsx` (or your own AR `.xlsx`), confirm the mapping on the
confirmation screen (the amber `due_date` field is low-confidence — confirm it), and click
**Confirm & Compute**.

| URL | What |
|-----|------|
| `http://localhost:8001/app/` | The dashboard UI |
| `http://localhost:8001/health` | Liveness check |
| `http://localhost:8001/docs` | Interactive API docs (Swagger) |

The server binds `PORT` from the environment (default `8001`), so an isolated instance can be
started with e.g. `PORT=8011 uv run python -m src` without disturbing the default.

---

## Scheduled daily email report (optional)

An optional Windows ops job renders the dashboard for the newest `.xlsx` in a watched folder
and emails it as a PDF once a day. It starts its **own short-lived backend on an ephemeral
port** — it never touches your `:8001` server — and it is **disabled by default**: until you
configure SMTP it runs in dry-run mode (saves the PDF locally, sends nothing).

```bash
# dry-run: render + save a PDF under frontend/scripts/output/ (no email)
node frontend/scripts/daily-report.mjs --dry-run

# register a daily Windows task at noon (see docs for options)
powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1
```

Full setup, `.env` keys, and the IT note (enable Authenticated SMTP + app password) are in
[docs/daily-report.md](docs/daily-report.md).

---

## Testing

The "real path" is the deterministic pandas pipeline over real `.xlsx` fixtures — there is no
external API to stub. Tests inject a fixed `as_of` date so aging buckets never go stale, and
assert against an **independent** hand-authored oracle (`tests/fixtures/expected_small.json`).

```bash
uv run pytest tests/unit tests/integration -q
```

This covers: exact headline tie-out on `ar_small.xlsx`; full-data tie-out on a generated
≥60,000-row fixture (no truncation); the employee summary, group breakdowns + weighted-avg-DPD
(including the null case), and riskiest-accounts / data-quality audit; partition invariants
(per-group totals sum to the overall totals); and the FastAPI routes over the real pipeline.

Frontend end-to-end (from `frontend/`):

```bash
npx playwright test tests/e2e/ --reporter=line
```

---

## Layout

```
src/
  api/            ← FastAPI routers (analysis: /api/preview, /api/compute; health)
  config/         ← Pydantic settings (no keys — local, no-LLM, no-DB)
  domain/         ← Pydantic models (mapping, aging metrics, quality flags)
  graph/          ← deterministic LangGraph pipeline (ingest → validate → compute → flag → assemble)
  tools/          ← header detect, ingest/normalize, validate, metrics, flags
  observability/  ← structlog JSON events
  __main__.py     ← boots uvicorn (honours PORT)
frontend/         ← Next.js static export, served by FastAPI at /app
tests/
  fixtures/       ← workbook builder + independent expected-value oracles
  unit/           ← tie-outs, partition invariants, weighted-avg oracle, summary-row exclusion
  integration/    ← FastAPI TestClient over the real pipeline
spec/             ← roadmap, architecture, capabilities/, data, api, ui
```

---

## Out of scope (by design)

- **DSO (Days Sales Outstanding)** — no sales/turnover column exists in the input; never computed or faked.
- **`.xls`, `.csv`, `.pdf`** ingestion — `.xlsx` only.
- **No LLM / AI commentary** — every number is deterministic pandas arithmetic.
- **No persistence** — no database, no history, no saved sessions, no login.
- **No network egress from the dashboard** — the interactive app is fully offline; the uploaded
  file never leaves the machine. The **only** exception is the optional, opt-in daily email
  report (above), which you explicitly configure with your own SMTP credentials and which emails
  a rendered PDF to your own address — it is off (dry-run) until you set it up.
