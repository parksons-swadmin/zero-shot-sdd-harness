import { test, expect } from '@playwright/test'

// Phase 3d — PDF + Excel ingestion polish (frontend slice).
//
// The accept-filter / copy assertions run against the real page (no backend
// needed). The upload-flow assertions use Playwright route interception to
// simulate the two backend Phase-3d responses deterministically:
//   (a) 200 with a `pdf_best_effort` cleaning-report caveat, and
//   (b) 422 PDF_NO_TABLES for a scanned/image-only PDF.
// This keeps the e2e independent of whether a real fixture PDF is present in
// the CI run while still exercising the exact UI code paths the spec requires.

const A_MINIMAL_PDF = Buffer.from(
  '%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n',
)

// Envelope for a successful PDF upload carrying the mandatory best-effort caveat
// (spec/capabilities/dataset-ingestion.md → "PDF best-effort extraction rule").
const PDF_OK_ENVELOPE = {
  data: {
    dataset_id: 'ds-pdf-caveat',
    filename: 'report.pdf',
    row_count: 12,
    column_count: 3,
    status: 'ready',
    profile: {
      columns: [
        { name: 'region', dtype: 'object', null_count: 0, distinct_count: 3, min: null, max: null, mean: null, median: null, top_values: null },
        { name: 'revenue', dtype: 'float64', null_count: 0, distinct_count: 12, min: 100, max: 900, mean: 500, median: 500, top_values: null },
        { name: 'quarter', dtype: 'object', null_count: 0, distinct_count: 4, min: null, max: null, mean: null, median: null, top_values: null },
      ],
    },
    cleaning_report: {
      issues: [
        {
          column: '',
          issue_type: 'pdf_best_effort',
          action_taken:
            'extracted table(s) from PDF — this may be inaccurate (merged cells, multi-column layouts, repeated headers); please verify against the source',
          affected_row_count: 12,
          needs_review: true,
        },
      ],
    },
  },
  error: null,
}

const PDF_NO_TABLES_ENVELOPE = {
  data: null,
  error: {
    code: 'PDF_NO_TABLES',
    message:
      'This PDF has no extractable tables — it may be scanned/image-based; export to CSV instead.',
  },
}

test.describe('Phase 3d — PDF + Excel upload polish', () => {
  test('the dropzone advertises Excel + PDF support in its accept filter and copy', async ({
    page,
  }) => {
    await page.goto('./')
    await expect(page.getByRole('heading', { name: 'Data Analyst Agent' })).toBeVisible()

    // The file input now accepts Excel (.xlsx/.xls) and PDF alongside delimited text.
    const accept = await page.getByTestId('file-input').getAttribute('accept')
    expect(accept).toContain('.pdf')
    expect(accept).toContain('.xlsx')
    expect(accept).toContain('.xls')
    expect(accept).toContain('.csv')

    // The visible empty-state copy mentions Excel and PDF, not just CSV.
    const dropzone = page.getByTestId('upload-dropzone')
    await expect(dropzone).toContainText('Excel')
    await expect(dropzone).toContainText('PDF')
  })

  test('a best-effort PDF upload surfaces the pdf_best_effort caveat in the cleaning report', async ({
    page,
  }) => {
    // Simulate the backend's 200 + best-effort caveat, and a session for it.
    await page.route('**/datasets', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PDF_OK_ENVELOPE) })
      } else {
        await route.continue()
      }
    })
    await page.route('**/sessions', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { session_id: 'sess-pdf', dataset_ids: ['ds-pdf-caveat'] }, error: null }),
        })
      } else {
        await route.continue()
      }
    })

    await page.goto('./')
    await page
      .getByTestId('file-input')
      .setInputFiles({ name: 'report.pdf', mimeType: 'application/pdf', buffer: A_MINIMAL_PDF })

    // Upload succeeds — no error banner.
    await expect(page.getByTestId('upload-dropzone')).toContainText('report.pdf', { timeout: 30_000 })
    await expect(page.getByTestId('upload-error')).toHaveCount(0)

    // The existing CleaningReportList renders the best-effort caveat + its "Needs review" badge.
    const cleaningList = page.getByTestId('cleaning-report-list')
    await expect(cleaningList).toBeVisible({ timeout: 15_000 })
    await expect(cleaningList).toContainText('pdf best effort')
    await expect(cleaningList).toContainText('please verify against the source')
    await expect(cleaningList.getByTestId('needs-review-badge').first()).toBeVisible()
  })

  test('a scanned / image-only PDF surfaces the 422 PDF_NO_TABLES human message', async ({ page }) => {
    await page.route('**/datasets', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify(PDF_NO_TABLES_ENVELOPE),
        })
      } else {
        await route.continue()
      }
    })

    await page.goto('./')
    await page
      .getByTestId('file-input')
      .setInputFiles({ name: 'scanned.pdf', mimeType: 'application/pdf', buffer: A_MINIMAL_PDF })

    // The 422's human message flows through the existing upload-error handler —
    // a specific caption, never a generic "Upload failed (422)".
    const uploadError = page.getByTestId('upload-error')
    await expect(uploadError).toBeVisible({ timeout: 30_000 })
    await expect(uploadError).toContainText('no extractable tables')
    await expect(uploadError).toContainText('export to CSV instead')

    // The dropzone offers a retry affordance rather than a broken state.
    await expect(page.getByTestId('upload-dropzone')).toContainText('Click to try another file')
  })
})
