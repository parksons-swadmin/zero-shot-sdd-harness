import { test, expect } from '@playwright/test'

// Two small, distinct fixtures with independently pre-computed revenue totals.
// month1: 5 rows @ 100 = 500 ; month2: 5 rows @ 200 = 1000 ; combined = 1500.
const MONTH1_CSV =
  'id,region,signup_date,revenue\n' +
  '1,West,2024-01-05,100.00\n' +
  '2,East,2024-01-06,100.00\n' +
  '3,West,2024-01-07,100.00\n' +
  '4,East,2024-01-08,100.00\n' +
  '5,West,2024-01-09,100.00\n'

const MONTH2_CSV =
  'id,region,signup_date,revenue\n' +
  '6,West,2024-02-05,200.00\n' +
  '7,East,2024-02-06,200.00\n' +
  '8,West,2024-02-07,200.00\n' +
  '9,East,2024-02-08,200.00\n' +
  '10,West,2024-02-09,200.00\n'

const COMBINED_TOTAL_REGEX = /1,?500(\.00)?/

async function uploadCsv(page: import('@playwright/test').Page, name: string, contents: string) {
  const fileInput = page.getByTestId('file-input')
  await fileInput.setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(contents) })
  // Wait for the upload+profile round-trip to finish.
  await expect(page.getByTestId('upload-dropzone')).toContainText(name, { timeout: 60_000 })
}

test.describe('Phase 2 — library, cross-file sessions, follow-ups & persisted thread', () => {
  test('upload two files, run a cross-file session, click a follow-up, resume after reload', async ({ page }) => {
    await page.goto('./')
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // Upload two distinct CSVs.
    await uploadCsv(page, 'month1.csv', MONTH1_CSV)
    await uploadCsv(page, 'month2.csv', MONTH2_CSV)

    // The library sidebar (no longer a stub) lists both datasets.
    const sidebar = page.getByTestId('library-sidebar')
    await expect(sidebar).toBeVisible()
    const items = page.getByTestId('library-item')
    await expect(items.filter({ hasText: 'month1.csv' }).first()).toBeVisible({ timeout: 15_000 })
    await expect(items.filter({ hasText: 'month2.csv' }).first()).toBeVisible({ timeout: 15_000 })

    // Check both files and start a session scoped to both.
    await items.filter({ hasText: 'month1.csv' }).first().getByRole('checkbox').check()
    await items.filter({ hasText: 'month2.csv' }).first().getByRole('checkbox').check()
    await page.getByTestId('start-session').click()

    // Ask a question that requires BOTH dataframes.
    const questionInput = page.getByTestId('question-input')
    await expect(questionInput).toBeEnabled({ timeout: 15_000 })
    await questionInput.fill('What is the combined total revenue across both months?')
    await page.getByTestId('ask-submit').click()

    // A real answer renders (not a spinner / not an error).
    const answerPanel = page.getByTestId('answer-panel')
    await expect(answerPanel).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('ask-error')).toHaveCount(0)
    await expect(page.getByTestId('answer-summary')).toContainText(COMBINED_TOTAL_REGEX)

    // Follow-up chips render and clicking one populates the question box (no auto-submit).
    const chips = page.getByTestId('follow-up-chip')
    await expect(chips.first()).toBeVisible({ timeout: 15_000 })
    const chipText = (await chips.first().textContent())?.trim() ?? ''
    expect(chipText.length).toBeGreaterThan(0)
    await chips.first().click()
    await expect(questionInput).toHaveValue(chipText)
    // Not auto-submitted: no fresh loading state kicked off by the chip click.
    await expect(page.getByTestId('ask-loading')).toHaveCount(0)

    // Reload the page, re-select the same two files → the session resumes and the
    // persisted thread (prior user + assistant turn) renders.
    await page.reload()
    const items2 = page.getByTestId('library-item')
    await expect(items2.filter({ hasText: 'month1.csv' }).first()).toBeVisible({ timeout: 15_000 })
    await items2.filter({ hasText: 'month1.csv' }).first().getByRole('checkbox').check()
    await items2.filter({ hasText: 'month2.csv' }).first().getByRole('checkbox').check()
    await page.getByTestId('start-session').click()

    const thread = page.getByTestId('chat-thread')
    await expect(thread).toBeVisible({ timeout: 20_000 })
    await expect(thread).toContainText('combined total revenue')
    await expect(thread.getByTestId('answer-summary').first()).toContainText(COMBINED_TOTAL_REGEX)
  })

  // Regression: the backend persists rejected uploads (e.g. a non-CSV) with
  // status "error" and null row/column counts. The library must render such a
  // dataset as a visible failed state and NOT crash the whole page by calling
  // .toLocaleString() on null. See LibrarySidebar guard.
  test('library renders an errored dataset (null counts) without crashing the page', async ({ page }) => {
    // Force the library GET to include a failed upload with null counts.
    await page.route('**/datasets', async (route, request) => {
      if (request.method() !== 'GET') return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            datasets: [
              {
                dataset_id: 'failed-1',
                filename: 'report.xlsx',
                row_count: null,
                column_count: null,
                status: 'error',
                created_at: '2026-07-03T00:00:00Z',
              },
              {
                dataset_id: 'ok-1',
                filename: 'good.csv',
                row_count: 1234,
                column_count: 5,
                status: 'ready',
                created_at: '2026-07-03T00:00:00Z',
              },
            ],
          },
          error: null,
        }),
      })
    })

    await page.goto('./')

    // The page did NOT crash into React's client-side exception fallback.
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()
    await expect(page.locator('text=Application error')).toHaveCount(0)

    const sidebar = page.getByTestId('library-sidebar')
    await expect(sidebar).toBeVisible()

    // The errored dataset is listed with a clear failed marker and no counts.
    const failedItem = page.getByTestId('library-item').filter({ hasText: 'report.xlsx' })
    await expect(failedItem).toBeVisible()
    await expect(failedItem.getByTestId('library-item-failed')).toBeVisible()
    // ...and it is NOT selectable (no checkbox to add it to a session).
    await expect(failedItem.getByTestId('library-item-checkbox')).toHaveCount(0)

    // The healthy dataset still renders its numeric counts and a checkbox.
    const okItem = page.getByTestId('library-item').filter({ hasText: 'good.csv' })
    await expect(okItem).toContainText('1,234 rows')
    await expect(okItem.getByTestId('library-item-checkbox')).toBeVisible()
  })
})
