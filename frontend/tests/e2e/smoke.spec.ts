import { test, expect } from '@playwright/test'
import path from 'path'

// Repo-root fixture built by the Phase-1 `engine` slice. From frontend/tests/e2e/,
// up three levels reaches the repo root.
const FIXTURE = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')

test('upload → confirm mapping → dashboard shows real KPI + chart bar', async ({ page }) => {
  // 1. Page loads and is styled (heading present).
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()

  // 2. Primary input works: upload the fixture .xlsx (hidden input accepts setInputFiles).
  await page.locator('input[type="file"]').setInputFiles(FIXTURE)

  // 3. Mapping-confirm screen appears; the due_date field is pre-filled at low confidence
  //    (amber) — we just proceed. Confirm & Compute is enabled once all six are mapped.
  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 30_000 })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  // 4. Dashboard: assert a REAL headline KPI money value (contains ₹, non-empty) — not a
  //    spinner or an error.
  const totalOutstanding = page.getByTestId('kpi-total-outstanding')
  await expect(totalOutstanding).toBeVisible({ timeout: 30_000 })
  await expect(totalOutstanding).toContainText('₹')
  const kpiText = (await totalOutstanding.textContent())?.trim() ?? ''
  expect(kpiText.length).toBeGreaterThan(1)

  // 5. At least one Top-20 chart bar is rendered (real content, not empty).
  const chart = page.getByTestId('top-customers-chart')
  await expect(chart).toBeVisible()
  const bars = chart.locator('.recharts-bar-rectangle')
  await expect(bars.first()).toBeVisible({ timeout: 15_000 })
  expect(await bars.count()).toBeGreaterThan(0)
})
