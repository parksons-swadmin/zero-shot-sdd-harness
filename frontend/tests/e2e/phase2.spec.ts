import { test, expect } from '@playwright/test'
import path from 'path'

// Repo-root fixture built by the Phase-1 `engine` slice. From frontend/tests/e2e/,
// up three levels reaches the repo root.
const FIXTURE = path.resolve(__dirname, '../../../tests/fixtures/ar_small.xlsx')

test('upload → confirm → dashboard renders Phase-2 employee/breakdown/flags with real values', async ({
  page,
}) => {
  // Walk the full journey: upload → mapping-confirm → Confirm & Compute.
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: /AR Aging Dashboard/i })).toBeVisible()

  await page.locator('input[type="file"]').setInputFiles(FIXTURE)

  const confirm = page.getByRole('button', { name: /Confirm & Compute/i })
  await expect(confirm).toBeVisible({ timeout: 30_000 })
  await expect(confirm).toBeEnabled()
  await confirm.click()

  // Dashboard reached (headline KPI present) before asserting Phase-2 surfaces.
  await expect(page.getByTestId('kpi-total-outstanding')).toBeVisible({ timeout: 30_000 })

  // --- Employee-wise summary ---
  const employeeTable = page.getByTestId('employee-table')
  await expect(employeeTable).toBeVisible()
  // Ranked DESC by outstanding: the first data row is the top salesperson (Ravi).
  const firstEmployeeRow = employeeTable.locator('tbody tr').first()
  await expect(firstEmployeeRow).toContainText('Ravi')
  // The blank-employee invoice is a real row, not an empty state.
  await expect(employeeTable).toContainText('(blank)')

  // --- Aging breakdown ---
  const agingBreakdown = page.getByTestId('aging-breakdown')
  await expect(agingBreakdown).toBeVisible()
  // The overall segmented bar renders one Recharts rectangle per aging bucket. The
  // first stacked segment is the `current` bucket, which can be empty, so we do NOT
  // assert the first segment is visible. Instead: at least one bar exists AND at
  // least one is actually rendered/visible — robust regardless of segment order.
  const chart = page.getByTestId('aging-breakdown-chart')
  await expect(chart).toBeVisible({ timeout: 15_000 })
  const bars = chart.locator('.recharts-bar-rectangle')
  await expect.poll(async () => await bars.count(), { timeout: 15_000 }).toBeGreaterThan(0)
  await expect(chart.locator('.recharts-bar-rectangle:visible').first()).toBeVisible({
    timeout: 15_000,
  })
  // Zenith Ltd has zero overdue → its weighted-avg days cell shows the em-dash "—".
  const zenithRow = agingBreakdown.locator('tbody tr', { hasText: 'Zenith' })
  await expect(zenithRow).toContainText('—')

  // --- Risk flags + data-quality audit ---
  const flagsPanel = page.getByTestId('flags-panel')
  await expect(flagsPanel).toBeVisible()
  // Beacon & Co is deepest in 90+ → listed among the riskiest accounts.
  await expect(page.getByTestId('risk-flags')).toContainText('Beacon & Co')
  // The data-quality audit lists the seeded flagged rows (e.g. the negative-amount row 15).
  const dqList = page.getByTestId('data-quality-list')
  await expect(dqList).toBeVisible()
  await expect(dqList).toContainText(/negative/i)
})
