import { test, expect } from '@playwright/test'
import path from 'path'

// Repo-root fixture built by the Phase-1 `engine` slice. From frontend/tests/e2e/,
// up three levels reaches the repo root.
const FIXTURE = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')

test('theme toggle switches the dark class on <html>', async ({ page }) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()

  const html = page.locator('html')
  const toggle = page.getByTestId('theme-toggle')
  await expect(toggle).toBeVisible()

  // With nothing stored the app defaults to DARK.
  await expect(html).toHaveClass(/dark/)

  // Toggle → light (dark class removed from <html>).
  await toggle.click()
  await expect(html).not.toHaveClass(/dark/)

  // Toggle again → back to dark.
  await toggle.click()
  await expect(html).toHaveClass(/dark/)
})

test('an explicit light choice persists across a reload', async ({ page }) => {
  await page.goto('/app/')
  // Default is DARK; toggling makes an EXPLICIT 'light' choice (stored under `ar-theme`).
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByTestId('theme-toggle').click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)

  // Reload: the pre-paint script must restore the stored 'light' preference before
  // first paint — otherwise it would fall back to the dark default.
  await page.reload()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('Data-quality audit button opens an accessible modal listing the flagged rows', async ({
  page,
}) => {
  // Walk upload → mapping-confirm → dashboard.
  await page.goto('/app/')
  await page.locator('input[type="file"]').setInputFiles(FIXTURE)

  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 30_000 })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })

  // The audit list is NOT inline — it opens from the admin/spot-check button.
  // (The summary-row-note, when a file has embedded totals, stays inline — ar_small
  // has none, so it is simply absent here.)
  await expect(page.getByTestId('data-quality-list')).toHaveCount(0)

  const auditButton = page.getByTestId('data-quality-audit-button')
  await expect(auditButton).toBeVisible()
  await expect(auditButton).toContainText(/Data-quality audit/i)
  await auditButton.click()

  // Modal opens: dialog role, labelled, and the flagged-rows list is visible with real content.
  const modal = page.getByTestId('data-quality-modal')
  await expect(modal).toBeVisible()
  await expect(modal).toHaveAttribute('role', 'dialog')
  await expect(modal).toHaveAttribute('aria-modal', 'true')
  const dqList = page.getByTestId('data-quality-list')
  await expect(dqList).toBeVisible()
  await expect(dqList).toContainText(/negative/i)

  // Esc closes the modal (accessible dismiss).
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)
})
