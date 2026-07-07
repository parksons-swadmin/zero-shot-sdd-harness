#!/usr/bin/env node
// @ts-check
/*
 * Scheduled daily AR-aging email report (ops/job slice).
 *
 * What it does, in order:
 *   1. Resolve config from the repo-root .env (process.env wins over .env file).
 *   2. Pick the NEWEST *.xlsx in AGENT_REPORT_WATCH_DIR (ignore ~$ lock/temp files).
 *      No file  -> log "no AR file found" and exit 0 (nothing to send).
 *   3. Require the built static export (frontend/out). Missing -> log how to build,
 *      exit non-zero.
 *   4. Start the backend on an EPHEMERAL port (never the user's :8001) and health-check.
 *   5. Drive the real app with the installed Playwright chromium: upload the newest
 *      file; if the standard export auto-maps -> the dashboard renders; if the
 *      mapping-confirm screen appears instead -> log "file not auto-mappable; skipping"
 *      and exit 0 (no send). Then render the dashboard to a print-layout PDF.
 *   6. Always kill the ephemeral backend (finally).
 *   7. Email the PDF via nodemailer when SMTP host+user+password are all set; otherwise
 *      DRY RUN: copy the PDF into frontend/scripts/output/ and skip the send.
 *
 * The SMTP password is NEVER logged. Pass --dry-run to force the dry-run path even when
 * SMTP is fully configured (useful for local testing without sending mail).
 *
 * This is fully local: the job starts its own short-lived server, renders, and stops it.
 * It does not touch the user's :8001 dev server.
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// ----------------------------------------------------------------------------
// Paths
// ----------------------------------------------------------------------------
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url)) // <repo>/frontend/scripts
const FRONTEND_DIR = path.resolve(SCRIPT_DIR, '..') //             <repo>/frontend
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..') //             <repo>
const FRONTEND_OUT = path.join(FRONTEND_DIR, 'out')
const DRYRUN_OUTPUT_DIR = path.join(SCRIPT_DIR, 'output')

// ----------------------------------------------------------------------------
// Structured logging (JSON lines to stdout; errors also carry level=error)
// ----------------------------------------------------------------------------
function log(step, extra = {}) {
  process.stdout.write(
    JSON.stringify({ ts: new Date().toISOString(), level: 'info', step, ...extra }) + '\n',
  )
}
function logError(step, extra = {}) {
  process.stdout.write(
    JSON.stringify({ ts: new Date().toISOString(), level: 'error', step, ...extra }) + '\n',
  )
}

// ----------------------------------------------------------------------------
// .env loading (hand-parsed; no external dep). process.env takes precedence so a
// value exported on the command line overrides the file (handy for testing).
// ----------------------------------------------------------------------------
async function loadDotenv(envPath) {
  const fileEnv = {}
  try {
    const raw = await fs.readFile(envPath, 'utf8')
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) continue
      const eq = trimmed.indexOf('=')
      if (eq === -1) continue
      const key = trimmed.slice(0, eq).trim()
      let val = trimmed.slice(eq + 1).trim()
      // strip surrounding matching quotes
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1)
      }
      if (key) fileEnv[key] = val
    }
  } catch {
    // no .env at repo root -> rely on process.env + defaults only
  }
  return fileEnv
}

function pick(fileEnv, key, fallback = '') {
  const fromProc = process.env[key]
  if (fromProc !== undefined && fromProc !== '') return fromProc
  const fromFile = fileEnv[key]
  if (fromFile !== undefined && fromFile !== '') return fromFile
  return fallback
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------
function todayStamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function findNewestXlsx(dir) {
  let entries
  try {
    entries = await fs.readdir(dir)
  } catch {
    return null // directory missing / unreadable -> treated as "no file"
  }
  const candidates = entries.filter(
    (name) => name.toLowerCase().endsWith('.xlsx') && !name.startsWith('~$'),
  )
  let newest = null
  for (const name of candidates) {
    const full = path.join(dir, name)
    try {
      const st = await fs.stat(full)
      if (!st.isFile()) continue
      if (!newest || st.mtimeMs > newest.mtimeMs) newest = { full, name, mtimeMs: st.mtimeMs }
    } catch {
      /* skip unreadable entry */
    }
  }
  return newest
}

// Kill the backend and its whole child tree. `uv` spawns a child python that
// holds the port, so on Windows we must taskkill the tree, not just the parent.
function killTree(child) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null || child.signalCode !== null) return resolve()
    const pid = child.pid
    if (process.platform === 'win32' && pid) {
      const killer = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
      killer.on('exit', () => resolve())
      killer.on('error', () => {
        try {
          child.kill('SIGKILL')
        } catch {}
        resolve()
      })
    } else {
      try {
        child.kill('SIGKILL')
      } catch {}
      resolve()
    }
  })
}

async function waitForHealth(port, { timeoutMs = 60_000, intervalMs = 1000 } = {}, backend) {
  const url = `http://127.0.0.1:${port}/health`
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (backend && backend.exitCode !== null) {
      throw new Error(`backend exited early with code ${backend.exitCode}`)
    }
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 3000)
      const res = await fetch(url, { signal: ctrl.signal })
      clearTimeout(t)
      if (res.ok) return true
    } catch {
      /* not up yet */
    }
    await sleep(intervalMs)
  }
  return false
}

// ----------------------------------------------------------------------------
// Main
// ----------------------------------------------------------------------------
async function main() {
  const forceDryRun = process.argv.includes('--dry-run')
  const date = todayStamp()

  const fileEnv = await loadDotenv(path.join(REPO_ROOT, '.env'))

  const cfg = {
    watchDir: pick(fileEnv, 'AGENT_REPORT_WATCH_DIR', 'D:\\Cowork\\AR Dashboard Data'),
    to: pick(fileEnv, 'AGENT_REPORT_TO', 'sabyasachi.thakur@parksonspackaging.com'),
    smtpHost: pick(fileEnv, 'AGENT_SMTP_HOST', 'smtp.office365.com'),
    smtpPort: parseInt(pick(fileEnv, 'AGENT_SMTP_PORT', '587'), 10) || 587,
    smtpUser: pick(fileEnv, 'AGENT_SMTP_USER', 'sabyasachi.thakur@parksonspackaging.com'),
    smtpPass: pick(fileEnv, 'AGENT_SMTP_PASSWORD', ''),
    port: parseInt(pick(fileEnv, 'AGENT_REPORT_PORT', '8971'), 10) || 8971,
  }
  cfg.from = pick(fileEnv, 'AGENT_REPORT_FROM', cfg.smtpUser)
  const smtpConfigured = Boolean(cfg.smtpHost && cfg.smtpUser && cfg.smtpPass)
  const willDryRun = forceDryRun || !smtpConfigured

  // Config summary — password presence only, never the value.
  log('config', {
    watch_dir: cfg.watchDir,
    to: cfg.to,
    from: cfg.from,
    smtp_host: cfg.smtpHost,
    smtp_port: cfg.smtpPort,
    smtp_user: cfg.smtpUser,
    smtp_password_set: Boolean(cfg.smtpPass),
    ephemeral_port: cfg.port,
    force_dry_run: forceDryRun,
    mode: willDryRun ? 'dry-run' : 'send',
  })

  // 2. Newest .xlsx --------------------------------------------------------
  const newest = await findNewestXlsx(cfg.watchDir)
  if (!newest) {
    log('no_file', { watch_dir: cfg.watchDir, message: 'no AR file found' })
    return 0
  }
  log('found_file', { file: newest.full, mtime: new Date(newest.mtimeMs).toISOString() })

  // 3. Built static export required ---------------------------------------
  if (!existsSync(path.join(FRONTEND_OUT, 'index.html'))) {
    logError('out_missing', {
      out_dir: FRONTEND_OUT,
      message: 'frontend/out not built. Run:  cd frontend && pnpm build   (then re-run this job).',
    })
    return 1
  }

  // 4. Start the ephemeral backend ----------------------------------------
  log('backend_starting', { port: cfg.port, cwd: REPO_ROOT })
  const backend = spawn('uv', ['run', 'python', '-m', 'src'], {
    cwd: REPO_ROOT,
    env: { ...process.env, PORT: String(cfg.port) },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  // Ring buffer of recent backend output for diagnostics on failure.
  let backendTail = ''
  const capture = (buf) => {
    backendTail = (backendTail + buf.toString()).slice(-4000)
  }
  backend.stdout.on('data', capture)
  backend.stderr.on('data', capture)

  try {
    // spawn 'error' (e.g. uv not on PATH) surfaces as an early exit / rejected health.
    const spawnErr = new Promise((_, reject) =>
      backend.on('error', (e) => reject(new Error(`could not start backend: ${e.message}`))),
    )
    const healthy = await Promise.race([
      waitForHealth(cfg.port, { timeoutMs: 90_000 }, backend),
      spawnErr,
    ])
    if (!healthy) {
      logError('backend_failed', {
        message: 'backend did not become healthy in time',
        tail: backendTail.slice(-1200),
      })
      return 1
    }
    log('backend_ready', { port: cfg.port })

    // 5. Render the dashboard PDF via Playwright chromium ------------------
    const tmpDir = path.join(os.tmpdir(), 'ar-daily-report')
    await fs.mkdir(tmpDir, { recursive: true })
    const pdfPath = path.join(tmpDir, `AR_Aging_${date}_${process.pid}.pdf`)

    const rendered = await renderDashboardPdf(cfg.port, newest.full, pdfPath)
    if (rendered === 'not_auto_mappable') {
      log('mapping_not_auto', {
        file: newest.full,
        message: 'file not auto-mappable; skipping',
      })
      return 0
    }
    const pdfStat = await fs.stat(pdfPath)
    log('rendered', { pdf: pdfPath, pdf_bytes: pdfStat.size })

    // 7. Send or dry-run ---------------------------------------------------
    if (willDryRun) {
      await fs.mkdir(DRYRUN_OUTPUT_DIR, { recursive: true })
      const outPath = path.join(DRYRUN_OUTPUT_DIR, `AR_Aging_${date}.pdf`)
      await fs.copyFile(pdfPath, outPath)
      const reason = forceDryRun ? '--dry-run flag set' : 'SMTP not configured'
      log('dry_run', {
        reason,
        saved_pdf: outPath,
        pdf_bytes: pdfStat.size,
        message: `${reason} — PDF saved, send skipped`,
      })
    } else {
      log('emailing', { to: cfg.to, from: cfg.from, subject: `AR Aging Dashboard — ${date}` })
      try {
        await sendEmail(cfg, date, pdfPath)
        log('sent', { to: cfg.to, attachment: `AR_Aging_${date}.pdf`, pdf_bytes: pdfStat.size })
      } catch (e) {
        // NEVER include the password; nodemailer errors do not carry it.
        logError('smtp_failed', {
          message: e && e.message ? e.message : String(e),
          code: e && e.code ? e.code : undefined,
        })
        return 1
      }
    }
    return 0
  } catch (e) {
    logError('unhandled', { message: e && e.message ? e.message : String(e) })
    return 1
  } finally {
    // 6. Always stop the ephemeral backend.
    await killTree(backend)
    log('backend_stopped', { port: cfg.port })
  }
}

// ----------------------------------------------------------------------------
// Playwright render: upload -> (auto-map -> dashboard) -> print-layout PDF.
// Returns 'ok' on success or 'not_auto_mappable' when the confirm screen shows.
// ----------------------------------------------------------------------------
async function renderDashboardPdf(port, filePath, pdfPath) {
  const { chromium } = await import('@playwright/test')
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext()
    const page = await context.newPage()
    const baseUrl = `http://127.0.0.1:${port}/app/`
    log('rendering', { url: baseUrl, file: filePath })
    await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 60_000 })

    await page.setInputFiles('input[type=file]', filePath)

    // Race the two possible outcomes: the dashboard (auto-mapped) vs. the
    // mapping-confirm screen (not auto-mappable). Whichever appears first wins.
    const kpi = page.locator('[data-testid=kpi-total-outstanding]')
    const confirmBtn = page.getByRole('button', { name: /Confirm & Compute/i })
    const outcome = await Promise.race([
      kpi
        .waitFor({ state: 'visible', timeout: 90_000 })
        .then(() => 'dashboard')
        .catch(() => null),
      confirmBtn
        .waitFor({ state: 'visible', timeout: 90_000 })
        .then(() => 'mapping')
        .catch(() => null),
    ])

    if (outcome === 'mapping') return 'not_auto_mappable'
    if (outcome !== 'dashboard') {
      throw new Error('neither the dashboard nor the mapping screen appeared')
    }

    // Ensure a KPI carries a real value (not a spinner/empty).
    const kpiText = (await kpi.textContent())?.trim() ?? ''
    if (!kpiText) throw new Error('dashboard KPI rendered empty')

    // Print layout is already light: emulateMedia('print') fires the page's
    // matchMedia('print') handler which strips the dark theme; we also strip the
    // `.dark` class defensively so the PDF is always the clean light style.
    await page.emulateMedia({ media: 'print' })
    await page.evaluate(() => document.documentElement.classList.remove('dark'))
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      landscape: true,
      printBackground: true,
    })
    return 'ok'
  } finally {
    await browser.close()
  }
}

// ----------------------------------------------------------------------------
// Email via nodemailer (STARTTLS on 587). Password is used only for auth and is
// never logged anywhere in this module.
// ----------------------------------------------------------------------------
async function sendEmail(cfg, date, pdfPath) {
  const nodemailer = (await import('nodemailer')).default
  const transport = nodemailer.createTransport({
    host: cfg.smtpHost,
    port: cfg.smtpPort,
    secure: false, // 587 => STARTTLS
    requireTLS: true,
    auth: { user: cfg.smtpUser, pass: cfg.smtpPass },
  })
  await transport.sendMail({
    from: cfg.from || cfg.smtpUser,
    to: cfg.to,
    subject: `AR Aging Dashboard — ${date}`,
    text:
      `Attached is the AR aging dashboard for ${date}.\n\n` +
      `This report was generated automatically from the latest AR export.\n` +
      `Everything is computed locally — no data leaves the machine except this email.\n`,
    attachments: [{ filename: `AR_Aging_${date}.pdf`, path: pdfPath }],
  })
}

main()
  .then((code) => process.exit(code ?? 0))
  .catch((e) => {
    logError('fatal', { message: e && e.message ? e.message : String(e) })
    process.exit(1)
  })
