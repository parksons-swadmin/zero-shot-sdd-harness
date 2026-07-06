import { defineConfig, devices } from '@playwright/test'

// Hermetic E2E gate. The backend serves the built static export at /app/ ONLY after
// `pnpm build` has produced frontend/out/. The orchestrator's gate builds first, then
// runs `npx playwright test tests/e2e/`.
//
// Port isolation: the gate binds an ISOLATED port (default 8011), never the user's dev
// server on :8001. The FastAPI process honors the PORT env var; Playwright sets PORT to
// E2E_PORT for its webServer and points baseURL at the same port. reuseExistingServer is
// false so the gate never latches onto (or clobbers) a server already on the user's port.
//
// Determinism: the bundled demo fixture ar_small.xlsx is dated to a fixed reference
// (2026-01-15) so the documented spread reproduces exactly. The backend honors the
// server-level AGENT_AS_OF override (spec-backed), so we pin it here — otherwise aging is
// computed as of date.today() and the fixture "ages" out of the documented buckets.
const E2E_PORT = process.env.E2E_PORT ?? '8011'
const BASE_URL = `http://localhost:${E2E_PORT}/app/`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'line',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'uv run python -m src',
    cwd: '..',
    env: { PORT: E2E_PORT, AGENT_AS_OF: '2026-01-15' },
    url: BASE_URL,
    timeout: 120_000,
    reuseExistingServer: false,
  },
})
