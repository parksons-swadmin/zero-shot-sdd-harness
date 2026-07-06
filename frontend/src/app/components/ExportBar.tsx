'use client'

// Export & print controls (Phase 3). Two real actions:
//   • "Export Excel"       -> POST /api/export/xlsx, download the multi-sheet workbook.
//   • "Print / Save as PDF"-> window.print() (the @media print stylesheet lays the page
//                             out for paper and hides interactive chrome — see print.css).
// The whole bar is `no-print` so it never appears on the printed/PDF page.

import { useState } from 'react'
import { postExportXlsx } from '@/lib/api'
import type { Mapping } from '@/lib/types'

interface ExportBarProps {
  file: File
  mapping: Mapping
  sheetName: string
}

export default function ExportBar({ file, mapping, sheetName }: ExportBarProps) {
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onExportExcel() {
    setDownloading(true)
    setError(null)
    try {
      await postExportXlsx(file, mapping, sheetName)
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Could not export the workbook. Please try again.',
      )
    } finally {
      setDownloading(false)
    }
  }

  const btn =
    'rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-950'

  return (
    <div data-testid="export-bar" className="no-print flex flex-col items-start gap-2 sm:items-end">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          data-testid="export-excel"
          onClick={onExportExcel}
          disabled={downloading}
          className={btn}
        >
          {downloading ? 'Preparing…' : 'Export Excel'}
        </button>
        <button
          type="button"
          data-testid="export-print"
          onClick={() => window.print()}
          className={btn}
        >
          Print / Save as PDF
        </button>
      </div>

      {downloading && (
        <p className="text-xs text-slate-500 dark:text-slate-400" role="status" aria-live="polite">
          Building your workbook…
        </p>
      )}
      {error && (
        <p role="alert" className="max-w-xs text-xs text-red-700 dark:text-red-400 sm:text-right">
          {error}
        </p>
      )}
    </div>
  )
}
