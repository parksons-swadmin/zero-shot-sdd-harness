import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

// Repo-root fixtures built by the engine slice. From frontend/tests/e2e/, up three
// levels reaches the repo root. ar_large.xlsx is gitignored and (re)built by
// global-setup.ts if a fresh checkout lacks it.
const SMALL = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')
const LARGE = path.resolve(__dirname, '../../../tests/fixtures/ar_large.xlsx')

/** Walk upload → mapping-confirm → dashboard for a fixture; resolves once KPIs render. */
async function toDashboard(page: import('@playwright/test').Page, fixture: string, timeout = 30_000) {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()
  await page.locator('input[type="file"]').setInputFiles(fixture)

  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout })
}

test('Export Excel triggers a non-empty .xlsx download', async ({ page }) => {
  await toDashboard(page, SMALL)

  // Clicking "Export Excel" re-posts the file+mapping to /api/export/xlsx and downloads
  // the returned workbook via a temporary <a download>. Wait for the download event.
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30_000 }),
    page.getByTestId('export-excel').click(),
  ])

  const name = download.suggestedFilename()
  expect(name.toLowerCase()).toMatch(/\.xlsx$/)

  const savedPath = await download.path()
  expect(savedPath).toBeTruthy()
  const size = fs.statSync(savedPath!).size
  expect(size).toBeGreaterThan(0)
})

test('Print media hides chrome while KPIs + chart stay visible, and page.pdf() is non-empty', async ({
  page,
}) => {
  await toDashboard(page, SMALL)

  // Sanity: the export bar is visible on screen before emulating print media.
  await expect(page.getByTestId('export-bar')).toBeVisible()

  await page.emulateMedia({ media: 'print' })

  // KEEP on paper: the headline KPI tiles and the Top-20 chart remain visible.
  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible()
  await expect(page.getByTestId('top-customers-chart')).toBeVisible()

  // HIDE on paper: the export/print bar, the "Start over" button, and any file input.
  await expect(page.getByTestId('export-bar')).toBeHidden()
  await expect(page.getByRole('button', { name: /Start over/i }).first()).toBeHidden()
  await expect(page.locator('input[type="file"]')).toBeHidden()

  // The dashboard prints to a non-empty PDF (headless Chromium supports page.pdf()).
  const pdf = await page.pdf({ printBackground: true })
  expect(pdf.length).toBeGreaterThan(0)

  await page.emulateMedia({ media: null })
})

test('Large file streams the full sheet — progress bar appears and row count reaches >=60,000', async ({
  page,
}) => {
  test.setTimeout(180_000)

  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()
  await page.locator('input[type="file"]').setInputFiles(LARGE)

  // Preview of the large workbook can take a few seconds before the confirm screen shows.
  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 90_000 })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  // The progress bar appears during the streamed compute (shown immediately, then driven
  // by real {rows_done, rows_total} frames).
  await expect(page.getByTestId('progress-bar')).toBeVisible({ timeout: 60_000 })

  // Dashboard renders after the full sheet is processed. The row-count line proves the
  // entire >=60,000-row file streamed through with no sampling/truncation.
  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 120_000 })
  const rowCountText = (await page.getByTestId('dashboard-rowcount').textContent()) ?? ''
  const rows = Number(rowCountText.replace(/[^0-9]/g, ''))
  expect(rows).toBeGreaterThanOrEqual(60_000)
})
