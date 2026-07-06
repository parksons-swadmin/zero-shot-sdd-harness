import { execSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'

// From frontend/tests/e2e/, up three levels reaches the repo root.
const REPO_ROOT = path.resolve(__dirname, '../../..')
const FIXTURE_DIR = path.join(REPO_ROOT, 'tests', 'fixtures')
const LARGE = path.join(FIXTURE_DIR, 'ar_large.xlsx')
const STANDARD = path.join(FIXTURE_DIR, 'ar_standard.xlsx')

function present(file: string = LARGE): boolean {
  try {
    return fs.statSync(file).size > 0
  } catch {
    return false
  }
}

/**
 * Ensures the small standard-profile `ar_standard.xlsx` fixture exists before the
 * auto-skip E2E. It is small (committable), but we (re)generate it on demand so a
 * fresh checkout that lacks it still runs. Deterministic builder — never touches
 * the confidential real AR export.
 */
function ensureStandard(): void {
  if (present(STANDARD)) return
  console.log('[global-setup] tests/fixtures/ar_standard.xlsx missing — generating…')
  execSync('uv run python tests/fixtures/build_fixtures.py --standard', {
    cwd: REPO_ROOT,
    stdio: 'inherit',
  })
  if (!present(STANDARD)) {
    throw new Error(
      'ar_standard.xlsx could not be generated. Build it manually: ' +
        'uv run python tests/fixtures/build_fixtures.py --standard',
    )
  }
}

/**
 * Ensures the ≥60,000-row `ar_large.xlsx` fixture exists before the E2E run. It is
 * gitignored (multi-MB binary) and is produced by the engine slice's build_fixtures.py.
 * If a fresh checkout lacks it, we generate it here — first via the documented builder
 * flag, then (defensively) via a direct build_large() call that never rewrites the
 * committed ar_small.xlsx.
 */
export default function globalSetup(): void {
  ensureStandard()

  if (present()) return

  console.log('[global-setup] tests/fixtures/ar_large.xlsx missing — generating (>=60k rows)…')

  // Preferred: the documented builder flag (owned by the engine/export-backend slice).
  try {
    execSync('uv run python tests/fixtures/build_fixtures.py --large', {
      cwd: REPO_ROOT,
      stdio: 'inherit',
    })
  } catch (e) {
    console.warn('[global-setup] `build_fixtures.py --large` failed, trying direct build:', e)
  }
  if (present()) return

  // Fallback: call build_large() directly through a temp script. Works whether or not
  // the CLI grew a --large flag, and importing build_fixtures does NOT run its __main__
  // (so ar_small.xlsx is never churned).
  const script = path.join(os.tmpdir(), `build_ar_large_${process.pid}.py`)
  fs.writeFileSync(
    script,
    [
      'import sys',
      'from pathlib import Path',
      `sys.path.insert(0, r"${FIXTURE_DIR}")`,
      'from build_fixtures import build_large',
      `build_large(Path(r"${LARGE}"))`,
      `print("[global-setup] built", r"${LARGE}")`,
    ].join('\n'),
    'utf-8',
  )
  try {
    execSync(`uv run python "${script}"`, { cwd: REPO_ROOT, stdio: 'inherit' })
  } finally {
    try {
      fs.unlinkSync(script)
    } catch {
      /* ignore */
    }
  }

  if (!present()) {
    throw new Error(
      'ar_large.xlsx could not be generated. Build it manually: ' +
        'uv run python tests/fixtures/build_fixtures.py --large',
    )
  }
}
