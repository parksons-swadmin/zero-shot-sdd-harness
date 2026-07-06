import { test, expect } from '@playwright/test'
import path from 'path'

// Repo-root fixture built by the Phase-1 `engine` slice. From frontend/tests/e2e/,
// up three levels reaches the repo root. ar_small.xlsx has messy headers, so the
// flow goes through the mapping-confirm screen before the dashboard.
const FIXTURE = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')

// Walk upload → confirm mapping → dashboard. Shared by both drill-down tests.
async function gotoDashboard(page: import('@playwright/test').Page) {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()
  await page.locator('input[type="file"]').setInputFiles(FIXTURE)

  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 30_000 })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })
}

test('drill down → pick a customer → their invoices + subtotal tie out', async ({ page }) => {
  await gotoDashboard(page)

  // Drill-down is hidden until the button is clicked.
  await expect(page.getByTestId('drilldown')).toHaveCount(0)

  // Reveal the inline drill-down section. Opening with no filter fetches the list.
  await page.getByTestId('drilldown-toggle').click()
  const drilldown = page.getByTestId('drilldown')
  await expect(drilldown).toBeVisible()

  // Unfiltered load resolves to a real table (spinner clears, rows render).
  await expect(page.getByTestId('drilldown-table')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('drilldown-subtotal')).toContainText('All:')

  // Type-to-search the customer picker, then pick "Acme Corp".
  await page.getByTestId('drilldown-customer-input').fill('Acme')
  const acmeOption = page
    .getByTestId('drilldown-customer-option')
    .filter({ hasText: 'Acme Corp' })
  await expect(acmeOption).toBeVisible()
  await acmeOption.click()

  // The table now shows ONLY Acme Corp rows, with invoice no + amount + days overdue.
  await expect(page.getByTestId('drilldown-table')).toBeVisible({ timeout: 15_000 })
  const rows = drilldown.getByTestId('drilldown-row')
  await expect.poll(async () => rows.count()).toBeGreaterThan(0)
  // A known Acme invoice appears (INV-1003), and every rendered row is Acme Corp.
  await expect(drilldown).toContainText('INV-1003')
  const rowCount = await rows.count()
  for (let i = 0; i < rowCount; i++) {
    await expect(rows.nth(i).locator('td').first()).toHaveText('Acme Corp')
  }
  // Amount column renders ₹; days-overdue column renders a value or em-dash.
  await expect(rows.first()).toContainText('₹')

  // Subtotal/count line is scoped to Acme Corp and (filtered → not truncated) its
  // count equals the number of rendered rows — an internal tie-out.
  const subtotal = page.getByTestId('drilldown-subtotal')
  await expect(subtotal).toContainText('Acme Corp:')
  await expect(subtotal).toContainText('₹')
  await expect(subtotal).toContainText(`${rowCount} invoice`)
  // A filtered result returns ALL matching rows → no truncated banner.
  await expect(page.getByTestId('drilldown-truncated')).toHaveCount(0)

  // Sorting: click the "Amount due" header → rows reorder largest-first (desc default).
  await page.getByTestId('drilldown-sort-amount').click()
  await expect(page.locator('th[aria-sort="descending"]')).toContainText(/Amount due/i)

  // Clear filters returns to the unfiltered ("All") view.
  await page.getByTestId('drilldown-clear').click()
  await expect(page.getByTestId('drilldown-subtotal')).toContainText('All:', { timeout: 15_000 })
})

test('clicking an employee row opens the drill-down filtered to that employee', async ({
  page,
}) => {
  await gotoDashboard(page)

  // The employee table rows are clickable (role=button, aria-label).
  const raviRow = page
    .getByTestId('employee-table')
    .getByTestId('employee-row')
    .filter({ hasText: 'Ravi' })
    .first()
  await expect(raviRow).toBeVisible()
  await expect(raviRow).toHaveAttribute('aria-label', /Drill down to invoices for Ravi/i)
  await raviRow.click()

  // The drill-down reveals, pre-filtered to Ravi.
  const drilldown = page.getByTestId('drilldown')
  await expect(drilldown).toBeVisible()
  await expect(page.getByTestId('drilldown-employee-select')).toHaveValue('Ravi')

  // Ravi's invoices render; the subtotal line is scoped to Ravi.
  await expect(page.getByTestId('drilldown-table')).toBeVisible({ timeout: 15_000 })
  const rows = drilldown.getByTestId('drilldown-row')
  await expect.poll(async () => rows.count()).toBeGreaterThan(0)
  // INV-1001 (Beacon & Co, Ravi) is one of Ravi's invoices.
  await expect(drilldown).toContainText('INV-1001')

  const subtotal = page.getByTestId('drilldown-subtotal')
  await expect(subtotal).toContainText('Ravi:')
  await expect(subtotal).toContainText('₹')
})
