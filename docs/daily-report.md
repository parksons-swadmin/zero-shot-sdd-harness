# Scheduled daily AR-aging email report

A local ops job that, once a day, renders the AR aging dashboard for the newest export
in a watched folder and emails it as a PDF. It is completely separate from the
interactive app: it starts its **own short-lived backend on an ephemeral port** and
stops it again — it never touches your `:8001` dev server, and nothing is persisted.

## What it does

1. Reads config from the repo-root `.env` (see below).
2. Picks the **newest `*.xlsx`** in `AGENT_REPORT_WATCH_DIR` (Excel `~$…` lock/temp files
   are ignored). If the folder has no AR file, it logs `no AR file found` and exits `0`.
3. Requires the built static export (`frontend/out`). If it is missing it tells you to run
   `pnpm build` and exits non-zero.
4. Starts the backend on an **ephemeral port** (`AGENT_REPORT_PORT`, default `8971`) and
   health-checks `/health`.
5. Drives the real app with the installed **Playwright chromium** (headless): uploads the
   newest file. If your standard export **auto-maps**, the dashboard renders and the job
   captures it as a **print-layout PDF** (A4 landscape, light style). If the file is *not*
   auto-mappable (the mapping-confirm screen would appear), it logs
   `file not auto-mappable; skipping` and exits `0` without sending.
6. Always stops the ephemeral backend.
7. **Emails** the PDF when SMTP is fully configured; otherwise **dry-run**: it copies the
   PDF to `frontend/scripts/output/AR_Aging_<date>.pdf` and logs `send skipped`.

Every step prints a structured JSON log line to stdout. The password is **never** logged.

## Configuration (repo-root `.env`)

All keys are documented in `.env.example`. Copy the ones you need into `.env`
(the `.env` file is git-ignored and must never be committed).

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_REPORT_WATCH_DIR` | `D:\Cowork\AR Dashboard Data` | Folder watched for AR exports (newest `.xlsx` wins). |
| `AGENT_REPORT_TO` | `sabyasachi.thakur@parksonspackaging.com` | Recipient. |
| `AGENT_REPORT_FROM` | = `AGENT_SMTP_USER` | From address. |
| `AGENT_SMTP_HOST` | `smtp.office365.com` | SMTP host. |
| `AGENT_SMTP_PORT` | `587` | SMTP port (STARTTLS). |
| `AGENT_SMTP_USER` | `sabyasachi.thakur@parksonspackaging.com` | SMTP login / mailbox. |
| `AGENT_SMTP_PASSWORD` | *(blank)* | App password from IT. **Blank ⇒ dry-run.** Never commit a real value. |
| `AGENT_REPORT_PORT` | `8971` | Ephemeral port for the throwaway backend. |

The job is in **dry-run mode** until `AGENT_SMTP_HOST`, `AGENT_SMTP_USER` **and**
`AGENT_SMTP_PASSWORD` are all set. `--dry-run` forces dry-run even when SMTP is configured.

## IT note — enabling send (Office 365)

Modern Office 365 tenants disable basic/authenticated SMTP by default. To send:

1. Ask IT to **enable Authenticated SMTP (SMTP AUTH)** for the mailbox
   `sabyasachi.thakur@parksonspackaging.com`.
2. Because the tenant enforces MFA, generate an **app password** for this job (basic SMTP
   AUTH cannot use an interactive MFA prompt).
3. Put that app password in `.env` as `AGENT_SMTP_PASSWORD=...` — **only in `.env`**, never
   in `.env.example` or any committed file.

Until that is done the job renders the PDF and saves it locally (dry-run), so you can start
using it immediately and switch on email later with no code change.

## Testing the job

Prerequisites: `node` (v20+) and `uv` on PATH, and the frontend built once:

```
cd frontend && pnpm build && cd ..
```

Run it (dry-run — renders + saves a PDF, sends nothing):

```
node frontend/scripts/daily-report.mjs --dry-run
```

The saved PDF appears at `frontend/scripts/output/AR_Aging_<date>.pdf` (git-ignored).
Omit `--dry-run` to send for real once SMTP is configured.

## Scheduling (Windows Task Scheduler)

Register a daily task named **`AR-Daily-Report`** that runs at **12:00 PM**:

```
powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1
```

Pick a different time (24-hour `HH:mm`):

```
powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1 -Time 09:30
```

Run it on demand / inspect the log / remove it:

```
Start-ScheduledTask -TaskName AR-Daily-Report
Get-Content scripts\daily-report.log -Tail 40
powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1 -Unregister
```

The task runs the wrapper `scripts\run-daily-report.cmd`, which `cd`s to the repo root and
appends all output to `scripts\daily-report.log`.

### Laptop-must-be-on caveat

The task runs as **you** and **only while you are logged on** (no stored password). The
laptop must be **on and unlocked-into-your-session** at the scheduled time. `-StartWhenAvailable`
is set, so a run missed while the machine was asleep/off fires the next time it is available.
If you need it to run headless/unattended on a server, register it with
`-RunLevel Highest` + a service account instead (out of scope for this laptop setup).

## Notes

- Generated PDFs and `scripts/daily-report.log` are git-ignored — they may contain
  confidential AR data and must never be committed.
- The job is stateless: no database, no history. It always renders the single newest file.
