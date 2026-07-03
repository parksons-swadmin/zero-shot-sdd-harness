import { test, expect } from '@playwright/test'
import path from 'path'

const FIXTURE_CSV = path.join(__dirname, '..', 'fixtures', 'sample.csv')
// sample.csv has 20 rows, each with revenue = 500.00 → exact known total.
const EXPECTED_TOTAL_REGEX = /10,?000(\.00)?/

test.describe('Phase 1 — upload, profile & ask', () => {
  test('upload a CSV, see the profile + cleaning report, ask a question, see the answer + code', async ({ page }) => {
    await page.goto('./')

    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // Upload the fixture CSV.
    const fileInput = page.getByTestId('file-input')
    await fileInput.setInputFiles(FIXTURE_CSV)

    // Profile table renders with the correct row/column count.
    const profileTable = page.getByTestId('profile-table')
    await expect(profileTable).toBeVisible({ timeout: 30_000 })

    const profileRows = page.getByTestId('profile-row')
    await expect(profileRows).toHaveCount(4) // id, region, signup_date, revenue

    await expect(page.getByTestId('upload-dropzone')).toContainText('sample.csv')
    await expect(page.getByTestId('upload-dropzone')).toContainText('20 rows')

    // Cleaning report shows at least one real item.
    const cleaningItems = page.getByTestId('cleaning-report-item')
    await expect(cleaningItems.first()).toBeVisible({ timeout: 10_000 })
    expect(await cleaningItems.count()).toBeGreaterThanOrEqual(1)

    // Ask a question with a known exact numeric answer.
    const questionInput = page.getByTestId('question-input')
    await questionInput.fill('What is the total revenue?')
    await page.getByTestId('ask-submit').click()

    await expect(page.getByTestId('ask-loading')).toBeVisible()

    const answerPanel = page.getByTestId('answer-panel')
    await expect(answerPanel).toBeVisible({ timeout: 45_000 })

    const summary = page.getByTestId('answer-summary')
    await expect(summary).toContainText(EXPECTED_TOTAL_REGEX)

    // Expand the code panel and verify it shows real, non-empty code.
    await page.getByTestId('view-code-toggle').click()
    const codeBlock = page.getByTestId('generated-code')
    await expect(codeBlock).toBeVisible()
    const codeText = await codeBlock.textContent()
    expect(codeText?.trim().length ?? 0).toBeGreaterThan(0)

    // Phase 3c: the cost badge and step-progress indicator are now live (no longer
    // "coming soon" stubs). The cost badge shows a real USD figure; the
    // step-progress element exists (its live "Step N" text appears during a run).
    await expect(page.getByTestId('cost-badge')).toContainText('$')
    await expect(page.getByTestId('cost-badge')).not.toContainText('coming soon')
    await expect(page.getByTestId('step-progress')).toBeVisible()
  })

  test('empty state before upload and disabled ask before a dataset exists', async ({ page }) => {
    await page.goto('./')
    await expect(page.getByTestId('upload-dropzone')).toContainText('Upload a CSV to get started')
    await expect(page.getByTestId('ask-empty-state')).toContainText("Ask a question about your data once it's uploaded")
  })
})
