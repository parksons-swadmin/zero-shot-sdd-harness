import { test, expect } from '@playwright/test'

// A fixture with a categorical `region` column (5 distinct values) and a numeric
// `revenue` column, so "total revenue by region" produces a real ranked table and
// a bar chart with 5 aggregated points (never the raw rows).
function buildRegionCsv(): string {
  const regions = ['West', 'East', 'North', 'South', 'Central']
  let csv = 'id,region,signup_date,revenue\n'
  let id = 1
  for (let i = 0; i < 40; i++) {
    const region = regions[i % regions.length]
    const revenue = (100 * ((i % regions.length) + 1)).toFixed(2)
    csv += `${id},${region},2024-01-${String((i % 27) + 1).padStart(2, '0')},${revenue}\n`
    id++
  }
  return csv
}

const REGION_CSV = buildRegionCsv()

async function uploadCsv(page: import('@playwright/test').Page, name: string, contents: string) {
  const fileInput = page.getByTestId('file-input')
  await fileInput.setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(contents) })
  await expect(page.getByTestId('upload-dropzone')).toContainText(name, { timeout: 60_000 })
}

test.describe('Phase 3a — rich answer artifacts (chart, table, export, derived dataset)', () => {
  test('ranked-by-region answer renders a real chart + table, and export downloads a derived dataset that appears in the library', async ({
    page,
  }) => {
    await page.goto('./')
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // Upload the categorical fixture; a session is auto-created for it.
    await uploadCsv(page, 'regions.csv', REGION_CSV)

    const questionInput = page.getByTestId('question-input')
    await expect(questionInput).toBeEnabled({ timeout: 15_000 })

    // 1) Ask for a ranked-by-region aggregate → real chart + real table.
    await questionInput.fill('show me total revenue by region, ranked')
    await page.getByTestId('ask-submit').click()

    const answerPanel = page.getByTestId('answer-panel')
    await expect(answerPanel).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)

    // The Charts stub is gone — a real recharts container with an <svg> renders,
    // NOT the "coming soon" placeholder.
    await expect(page.getByTestId('stub-charts')).toHaveCount(0)
    const chartContainer = page.getByTestId('chart-container')
    await expect(chartContainer).toBeVisible({ timeout: 20_000 })
    await expect(chartContainer.locator('svg')).toBeVisible()

    // A real ranked/summary table renders with one row per region.
    const resultTable = page.getByTestId('result-table')
    await expect(resultTable).toBeVisible({ timeout: 20_000 })
    const tableRows = page.getByTestId('result-table-row')
    expect(await tableRows.count()).toBeGreaterThanOrEqual(2)

    // 2) Ask an export question → the previously-disabled Export button enables.
    await questionInput.fill('export the West-region rows as a dataset')
    await page.getByTestId('ask-submit').click()
    await expect(page.getByTestId('answer-panel')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)

    const exportButton = page.getByTestId('export-button')
    await expect(exportButton).toBeEnabled({ timeout: 20_000 })

    // Clicking it triggers a file download over localhost.
    const downloadPromise = page.waitForEvent('download')
    await exportButton.click()
    const download = await downloadPromise
    expect(download.suggestedFilename().length).toBeGreaterThan(0)

    // 3) The derived dataset now appears in the Library sidebar without a reload.
    // The fixture upload plus the derived export means at least two library items.
    const items = page.getByTestId('library-item')
    await expect
      .poll(async () => items.count(), { timeout: 20_000 })
      .toBeGreaterThanOrEqual(2)
    // The newly-derived dataset is selectable like any upload.
    await expect(items.last().getByTestId('library-item-checkbox')).toBeVisible()
  })

  test('export button is disabled with a "No export for this answer" tooltip before any export answer', async ({
    page,
  }) => {
    await page.goto('./')
    await uploadCsv(page, 'regions.csv', REGION_CSV)

    // Before asking anything that produces an export, the button stays disabled
    // and clearly captioned — never presented as broken.
    const exportButton = page.getByTestId('export-button')
    await expect(exportButton).toBeDisabled()
    await expect(exportButton).toHaveAttribute('title', 'No export for this answer')
    await expect(page.getByTestId('export-caption')).toContainText('No export for this answer')

    // And the chart area shows its "No chart for this answer" caption, not a stub.
    await expect(page.getByTestId('stub-charts')).toHaveCount(0)
    await expect(page.getByTestId('chart-empty')).toContainText('No chart for this answer')
  })
})
