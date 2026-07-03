import { test, expect } from '@playwright/test'

// A fixture with a numeric `revenue` column and a known exact total, so the answer
// is verifiable end-to-end. 20 rows x 500.00 = 10,000.00 (mirrors sample.csv).
function buildRevenueCsv(): string {
  let csv = 'id,region,signup_date,revenue\n'
  const regions = ['West', 'East', 'North', 'South']
  for (let i = 0; i < 20; i++) {
    csv += `${i + 1},${regions[i % regions.length]},2024-01-${String((i % 27) + 1).padStart(2, '0')},500.00\n`
  }
  return csv
}

const REVENUE_CSV = buildRevenueCsv()

async function uploadCsv(page: import('@playwright/test').Page, name: string, contents: string) {
  const fileInput = page.getByTestId('file-input')
  await fileInput.setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(contents) })
  await expect(page.getByTestId('upload-dropzone')).toContainText(name, { timeout: 60_000 })
}

// Reads the leading USD figure out of the cost badge text (e.g. "$0.0021").
function parseUsd(text: string | null): number {
  const m = (text ?? '').match(/\$([0-9]+\.[0-9]+)/)
  return m ? parseFloat(m[1]) : NaN
}

test.describe('Phase 3c — live progress & cost (streaming)', () => {
  test('answer streams in with a live step counter, and the cost badge shows a real per-query + running total', async ({
    page,
  }) => {
    await page.goto('./')
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // The cost badge is live from mount (no longer a "coming soon" stub).
    const costBadge = page.getByTestId('cost-badge')
    await expect(costBadge).toBeVisible()
    await expect(costBadge).not.toContainText('coming soon')
    await expect(costBadge).toContainText('$')

    // Upload the fixture; a session is auto-created for it.
    await uploadCsv(page, 'revenue.csv', REVENUE_CSV)

    const questionInput = page.getByTestId('question-input')
    await expect(questionInput).toBeEnabled({ timeout: 15_000 })

    // Ask a question with a known exact total.
    await questionInput.fill('What is the total revenue?')
    await page.getByTestId('ask-submit').click()

    // The step-progress indicator is live (not a "coming soon" stub) and shows a
    // real "Step N of ~M" label from the SSE `step` events. The last step remains
    // visible after the run, so this is robust to a fast run.
    const stepProgress = page.getByTestId('step-progress')
    await expect(stepProgress).toBeVisible()
    await expect(page.getByTestId('step-progress-label')).toContainText(/Step \d+ of ~\d+/, {
      timeout: 90_000,
    })

    // The answer renders (progressively via answer_chunk, reconciled by `result`).
    const answerPanel = page.getByTestId('answer-panel')
    await expect(answerPanel).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)
    await expect(page.getByTestId('answer-summary')).toContainText(/10,?000(\.00)?/)

    // The cost badge now shows a real, non-zero per-query + running total.
    await expect(costBadge).toContainText('$')
    await expect(page.getByTestId('cost-latest')).toBeVisible({ timeout: 20_000 })
    const firstTotal = parseUsd(await costBadge.textContent())
    expect(firstTotal).toBeGreaterThan(0)

    // Ask a second question — the running all-time total must strictly increase.
    await questionInput.fill('What is the average revenue?')
    await page.getByTestId('ask-submit').click()
    await expect(page.getByTestId('answer-panel')).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)

    await expect
      .poll(async () => parseUsd(await costBadge.textContent()), { timeout: 20_000 })
      .toBeGreaterThan(firstTotal)
  })
})
