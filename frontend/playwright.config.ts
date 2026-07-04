import { defineConfig, devices } from '@playwright/test'

// The backend serves the built static export at http://localhost:8001/app/ ONLY after
// `pnpm build` has produced frontend/out/. The orchestrator's gate builds first, then
// runs `npx playwright test tests/e2e/`. The webServer boots the single FastAPI process.
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
    baseURL: 'http://localhost:8001/app/',
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
    url: 'http://localhost:8001/app/',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
})
