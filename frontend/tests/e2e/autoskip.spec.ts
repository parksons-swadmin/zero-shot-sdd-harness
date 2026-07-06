import { test, expect } from '@playwright/test'
import path from 'path'

// Repo-root fixtures. From frontend/tests/e2e/, up three levels reaches the repo root.
// ar_standard.xlsx uses the EXACT default-profile headers → backend returns
// auto_mapped=true; ar_small.xlsx has messy headers (low-confidence due_date) →
// auto_mapped=false, so it must STILL show the confirm screen.
const STANDARD = path.resolve(__dirname, '../../../tests/fixtures/ar_standard.xlsx')
const SMALL = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')

test('standard export auto-skips the confirm screen straight to the dashboard', async ({ page }) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()

  // Upload the recognized standard export. NO "Confirm & Compute" click — the app
  // must compute automatically and land on the dashboard.
  await page.locator('input[type="file"]').setInputFiles(STANDARD)

  // KPIs render with a real money value — proving we went straight to the dashboard.
  const totalOutstanding = page.getByTestId('kpi-total-outstanding')
  await expect(totalOutstanding).toBeVisible({ timeout: 30_000 })
  await expect(totalOutstanding).toContainText('₹')

  // The mapping-confirm screen was skipped entirely — its Confirm button never renders.
  await expect(page.getByRole('button', { name: /Confirm & Compute/i })).toHaveCount(0)

  // The dismissible auto-mapped banner is visible above the KPIs.
  const banner = page.getByTestId('auto-mapped-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toContainText(/auto-mapped from your standard format/i)

  // "Review / change mapping" reopens the confirm screen PRE-FILLED with the mapping.
  await page.getByTestId('review-mapping').click()
  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible()
  await expect(page.getByRole('heading', { name: /Confirm the column mapping/i })).toBeVisible()

  // Pre-filled: every required field carries its auto-detected column, and the
  // optional HoD row is pre-selected to "HoD Name" (proving hod flows through).
  await expect(page.locator('#map-customer')).toHaveValue('Payer Name')
  await expect(page.locator('#map-invoice_date')).toHaveValue('Base Line Date') // pinned, not a decoy
  await expect(page.locator('#map-hod')).toHaveValue('HoD Name')

  // Re-confirming recomputes and returns to the dashboard; having been reviewed,
  // the auto-mapped banner is retired.
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('auto-mapped-banner')).toHaveCount(0)
})

test('auto-mapped banner is dismissible', async ({ page }) => {
  await page.goto('/app/')
  await page.locator('input[type="file"]').setInputFiles(STANDARD)

  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })
  const banner = page.getByTestId('auto-mapped-banner')
  await expect(banner).toBeVisible()

  await banner.getByRole('button', { name: /Dismiss/i }).click()
  await expect(banner).toHaveCount(0)
})

test('messy-header export still shows the confirm screen (no auto-skip)', async ({ page }) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()

  // ar_small.xlsx does NOT match the profile → auto_mapped=false → confirm screen.
  await page.locator('input[type="file"]').setInputFiles(SMALL)

  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: /Confirm the column mapping/i })).toBeVisible()
  // No auto-mapped banner on the confirm screen for a non-standard export.
  await expect(page.getByTestId('auto-mapped-banner')).toHaveCount(0)

  // Confirming proceeds to the dashboard, and (not auto-mapped) NO banner appears.
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('auto-mapped-banner')).toHaveCount(0)
})
