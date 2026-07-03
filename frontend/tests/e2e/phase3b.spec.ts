import { test, expect } from '@playwright/test'

// A fixture with (a) a CONSTANT column `data_source` (single value on every row
// -> distinct_count == 1), (b) a `region` column with a deliberate NULL spike,
// and (c) a clean numeric `revenue` column. The deterministic `_profile_anomalies`
// backend check guarantees at least a constant_column + null_values flag, so the
// anomaly banner is non-empty regardless of model behaviour.
function buildAnomalousCsv(): string {
  const regions = ['West', 'East', 'North', 'South', 'Central']
  let csv = 'id,data_source,region,revenue\n'
  for (let i = 0; i < 60; i++) {
    // `region` is blank on every 3rd row -> a real null spike.
    const region = i % 3 === 0 ? '' : regions[i % regions.length]
    const revenue = (100).toFixed(2)
    csv += `${i + 1},crm_export,${region},${revenue}\n`
  }
  return csv
}

const ANOMALOUS_CSV = buildAnomalousCsv()

async function uploadCsv(page: import('@playwright/test').Page, name: string, contents: string) {
  const fileInput = page.getByTestId('file-input')
  await fileInput.setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(contents) })
  await expect(page.getByTestId('upload-dropzone')).toContainText(name, { timeout: 60_000 })
}

test.describe('Phase 3b — proactive anomaly banner + audit history', () => {
  test('anomaly banner renders real flags on the answer, and audit history lists the run chronologically', async ({
    page,
  }) => {
    await page.goto('./')
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // Upload the anomalous fixture; a session is auto-created for it.
    await uploadCsv(page, 'anomalous.csv', ANOMALOUS_CSV)

    const questionInput = page.getByTestId('question-input')
    await expect(questionInput).toBeEnabled({ timeout: 15_000 })

    // Ask a normal question — the answer must succeed AND surface anomaly flags.
    await questionInput.fill('What is the total revenue?')
    await page.getByTestId('ask-submit').click()

    await expect(page.getByTestId('answer-panel')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)

    // The net-new anomaly banner renders with at least one real flag (not a stub).
    const banner = page.getByTestId('anomaly-banner')
    await expect(banner).toBeVisible({ timeout: 20_000 })
    const flags = page.getByTestId('anomaly-flag')
    expect(await flags.count()).toBeGreaterThanOrEqual(1)

    // Navigate to the Audit History screen via the header link.
    await page.getByTestId('history-link').click()
    await expect(page).toHaveURL(/\/app\/history\/?/)
    await expect(page.getByRole('heading', { name: 'Audit History' })).toBeVisible()

    // The audit table renders the prior run's events in chronological order.
    const table = page.getByTestId('audit-table')
    await expect(table).toBeVisible({ timeout: 20_000 })

    const eventTypes = page.getByTestId('audit-event-type')
    await expect
      .poll(async () => eventTypes.count(), { timeout: 20_000 })
      .toBeGreaterThanOrEqual(3)

    // The trail includes the ask / code_exec / answer events for our question.
    const allText = (await eventTypes.allTextContents()).join(',')
    expect(allText).toContain('ask')
    expect(allText).toContain('answer')

    // The question text is visible in an audit detail cell (raw rows never are).
    await expect(page.getByTestId('audit-detail').filter({ hasText: 'What is the total revenue?' }).first()).toBeVisible()
  })

  test('audit history shows an empty state when over-filtered, never an error', async ({ page }) => {
    await page.goto('./history/')
    await expect(page.getByRole('heading', { name: 'Audit History' })).toBeVisible()

    await page.getByTestId('filter-session').fill('does-not-exist-session-id')
    await page.getByTestId('apply-filters').click()

    await expect(page.getByTestId('audit-empty')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('audit-error')).toHaveCount(0)
  })
})
