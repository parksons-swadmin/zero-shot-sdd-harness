# Capability: Scheduled Daily Email Report

> **Phase 5. Opt-in.** This is the **single authorized network-egress path** in an otherwise fully-local tool: it deliberately sends confidential AR data (customer names + balances, inside the report PDF) **off the machine** via SMTP, by explicit user configuration. The interactive dashboard app remains fully local with no egress. See the egress scope in [architecture.md](../architecture.md#network-egress--scope-of-the-guarantee). **Off unless SMTP is configured.**

## What It Does
A daily background job on the user's own laptop (a Windows Scheduled Task, default **12:00 PM**; also runnable on demand) that picks the **newest** AR aging `.xlsx` from a watched folder, computes the dashboard with the existing deterministic pipeline, renders that dashboard to a **PDF** headlessly (the same light print layout the user prints by hand), and **emails the PDF** as an attachment to a configured recipient. It only proceeds when the file is confidently **auto-mapped** by the default mapping profile (a scheduled job cannot resolve an ambiguous mapping interactively); otherwise it logs and skips. When SMTP is not configured it runs as a **dry-run** — render + save the PDF locally, no send.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| newest `.xlsx` in the watched folder | file | `AGENT_REPORT_WATCH_DIR` (e.g. `D:\Cowork\AR Dashboard Data`) | yes |
| schedule trigger | Windows Scheduled Task (daily 12:00 PM) / manual CLI run | Task Scheduler / terminal | yes |
| SMTP + recipient config | env vars | repo-root `.env` (`AGENT_SMTP_*`, `AGENT_REPORT_TO`/`AGENT_REPORT_FROM`) | no — absent → dry-run |
| `as_of` reference date | date | `date.today()` (real run) / `AGENT_AS_OF` (deterministic gate only) | implicit |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dashboard PDF | PDF file (light print layout) | saved locally (report output dir) **and** attached to the email |
| email | SMTP message with the PDF attached | `AGENT_REPORT_TO` |
| job log | structured log lines (file picked, auto-map result, render ok, send/dry-run, errors) | stdout / job log file |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem (watched folder) | list + read the newest non-lock `.xlsx` | empty / missing / unreadable / no eligible file → log a clear message, exit **without sending** |
| Local app (`/app`, headless Chromium via Playwright) | drive upload → auto-skip → dashboard → print → PDF | mapping-confirm screen appears (not auto-mapped), render error, or timeout → log + exit, **no send** |
| SMTP server (Office 365 `smtp.office365.com:587`, STARTTLS) | authenticated send with the PDF attachment | send error → log the error (**never** the password), non-zero exit; the PDF is already saved locally |

**This SMTP send is the ONE authorized egress path** in the whole tool. It is off unless the user configures SMTP; the interactive app never calls it. No LLM, no third-party API, no database — the only outbound connection anywhere is this send.

## Business Rules
- **Trigger.** Runs daily at a configured time (default **12:00 PM**) via a Windows Scheduled Task; the laptop must be **on and awake** at that time (the task does not wake the machine). Also runnable on demand from a terminal. Otherwise **deterministic and stateless** — the same watched file + config yields the same PDF + email; nothing is persisted beyond the sent email, the saved PDF, and the logs.
- **File selection.** Picks the **newest** (by modification time) `.xlsx` in `AGENT_REPORT_WATCH_DIR`, **ignoring Excel lock files** (`~$*`) and any non-`.xlsx` file. If the folder is empty, missing, unreadable, or has no eligible file → log a clear message (stable step `no_file`, e.g. `"no AR file found"`) and exit **without rendering or sending**.
- **Auto-map-or-skip (no interactive mapping).** The job reuses the existing pipeline unchanged: default-profile auto-mapping → normalize → [summary-row exclusion](xlsx_ingestion_and_mapping.md#summary--total-row-detection--exclusion) → [metrics](aging_metrics_engine.md). It proceeds **only** when the file is confidently auto-mapped — i.e. the app's upload flow reaches the dashboard via auto-skip (`auto_mapped=true`; see [xlsx_ingestion_and_mapping.md](xlsx_ingestion_and_mapping.md) and [api.md](../api.md)). If instead the mapping-confirmation screen appears (`auto_mapped=false`), the job **logs the `mapping_not_auto` step (`"file not auto-mappable; skipping"`) and exits without sending** — a scheduled job cannot resolve an ambiguous mapping.
- **Render.** Produces a **PDF of the dashboard** — the same dashboard the user sees — in the **light print layout**, by reusing the existing headless Playwright + `@media print` machinery ([pdf_export.md](pdf_export.md), `frontend/src/app/print.css`): navigate `/app/`, upload the file, wait for the dashboard, `emulateMedia({ media: 'print' })`, `page.pdf({ printBackground: true })`. On a real run the reference date is `date.today()` (numbers age to today).
- **Email.** When SMTP is configured, sends the PDF as an attachment to `AGENT_REPORT_TO` from `AGENT_REPORT_FROM` (falling back to `AGENT_SMTP_USER`), authenticating to `AGENT_SMTP_HOST`:`AGENT_SMTP_PORT` (Office 365 `smtp.office365.com:587`, STARTTLS) with `AGENT_SMTP_USER` / `AGENT_SMTP_PASSWORD` (an **app password**). Subject + body name the source filename and the report date. Exactly one email per successful run.
- **Dry-run when SMTP is not configured.** "Configured" means **all** of `AGENT_SMTP_HOST`, `AGENT_SMTP_USER`, `AGENT_SMTP_PASSWORD` are present (the recipient `AGENT_REPORT_TO` always has a default and does **not** gate send/dry-run). If any is missing → **dry-run**: render + save the PDF locally and log the `dry_run` step (`"SMTP not configured — PDF saved, send skipped"`), then exit 0. This makes the whole path testable without credentials. A `--dry-run` CLI flag **forces** dry-run (never send) even when SMTP *is* configured — used by the gate and for safe manual testing.
- **Secret hygiene.** `AGENT_SMTP_PASSWORD` is a **secret**: it lives in `.env` (never committed — see [architecture.md](../architecture.md#settings-agent_-prefix-srcconfigsettingspy)), and is **never** logged, printed, or echoed — not on success, not in any error message.
- **Self-contained run.** The job boots its own backend (`uv run python -m src`) on an isolated port and tears it down when done, so the scheduled task needs no pre-running server. It does require the built static frontend (`frontend/out/` from `pnpm build`).

## Success Criteria
- [ ] Given a watched folder whose newest `.xlsx` is a standard-header (auto-mappable) export, a dry-run (no SMTP / `--dry-run`) produces a **non-empty PDF** locally and logs the `dry_run` step (`"SMTP not configured — PDF saved, send skipped"`), exiting 0.
- [ ] `~$*` lock files and non-`.xlsx` files in the watched folder are ignored; the newest eligible `.xlsx` is the one processed.
- [ ] An empty / missing / unreadable watched folder logs a clear message (stable step `no_file`, `"no AR file found"`) and exits without attempting to render or send.
- [ ] A watched file that is **not** confidently auto-mapped (the mapping-confirm screen would appear) is logged as skipped and **no email is sent**.
- [ ] When SMTP is configured (and `--dry-run` is not set), the job sends exactly one email to `AGENT_REPORT_TO` with the PDF attached; the password never appears in logs/stdout.
- [ ] The rendered PDF uses the **light print layout** (interactive chrome hidden; KPI tiles + Top-20 chart present) — byte-for-byte the same layout as manual Print / Save as PDF.
