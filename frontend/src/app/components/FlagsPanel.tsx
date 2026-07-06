'use client'

// Proactive risk flags + data-quality audit — Phase 2.
// (1) Riskiest accounts: the backend-ranked risk_flags list (Beacon & Co first for
//     the demo file — deepest 90+ overdue). ALWAYS visible inline.
// (2) Data-quality panel (inline): the small "N summary/total rows detected & excluded"
//     note stays visible because it explains the headline totals. The full per-row
//     DATA-QUALITY AUDIT (the flagged/unparseable rows list + the per-reason breakdown)
//     is an admin/spot-check view moved behind a "Data-quality audit" button that opens
//     an accessible modal — it is rarely needed and dominated the layout otherwise.

import { useState } from 'react'
import Modal from './Modal'
import { inr, intFmt, bucketLabel } from '@/lib/format'
import type { DataQuality, RiskFlag } from '@/lib/types'

interface FlagsPanelProps {
  riskFlags: RiskFlag[]
  dataQuality: DataQuality
}

// The data-quality audit list renders one <tr> per flagged/unparseable row. On a
// real export the audit list runs to ~2,900 rows (~15k DOM nodes) and committing
// them in one synchronous pass freezes the main thread for seconds. Capping to the
// first N keeps the render fast; a "Show all" control still exposes every row on
// demand. Mirrors the per-customer table cap in AgingBreakdown.tsx.
const DEFAULT_VISIBLE = 50

const FIELD_WORDS: Record<string, string> = {
  customer: 'customer',
  invoice_no: 'invoice number',
  invoice_date: 'invoice date',
  due_date: 'due date',
  amount: 'amount',
  employee: 'employee',
}

/** "negative_amount" -> "Negative amount"; falls back to spaced words. */
function humanize(s: string): string {
  const words = s.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function fieldWord(field: string): string {
  return FIELD_WORDS[field] ?? field.replace(/_/g, ' ')
}

export default function FlagsPanel({ riskFlags, dataQuality }: FlagsPanelProps) {
  const [showAllRows, setShowAllRows] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const rows = dataQuality.rows ?? []
  const summaryExcluded = dataQuality.by_reason?.summary_row_excluded ?? 0

  // Cap the audit list to the first N by default (keeps the real-file render fast).
  const rowsTotal = rows.length
  const rowsCapped = rowsTotal > DEFAULT_VISIBLE
  const visibleRows = showAllRows ? rows : rows.slice(0, DEFAULT_VISIBLE)

  // Per-reason counts, excluding the summary-row marker (surfaced separately as a note).
  const reasonCounts = Object.entries(dataQuality.by_reason ?? {}).filter(
    ([reason]) => reason !== 'summary_row_excluded',
  )

  const noIssues =
    dataQuality.flagged_row_count === 0 && dataQuality.unparseable_row_count === 0 && rowsTotal === 0

  const auditButtonLabel =
    rowsTotal > 0
      ? `Data-quality audit (${intFmt(rowsTotal)} flagged row${rowsTotal === 1 ? '' : 's'})`
      : 'Data-quality audit'

  return (
    <section
      aria-labelledby="flags-panel-heading"
      data-testid="flags-panel"
      className="grid grid-cols-1 gap-6 lg:grid-cols-2"
    >
      <h3 id="flags-panel-heading" className="sr-only">
        Risk flags and data-quality audit
      </h3>

      {/* Riskiest accounts — always visible inline */}
      <div
        data-testid="risk-flags"
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
      >
        <h4 className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
          Riskiest accounts
        </h4>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Customers with the largest 90+ day overdue balances — chase these first.
        </p>

        {riskFlags.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            No accounts are deep in the 90+ bucket. Nothing to flag.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {riskFlags.map((f, i) => (
              <li
                key={`${f.customer}-${i}`}
                className="flex items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-800 dark:text-slate-200">
                    {f.customer}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {f.reason}
                    {f.bucket ? ` · ${bucketLabel(f.bucket)}` : ''}
                  </p>
                </div>
                <span className="shrink-0 tabular-nums font-semibold text-red-700 dark:text-red-400">
                  {inr(f.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Data quality — compact inline card; the full audit opens in a modal */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <h4 className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
          Data quality
        </h4>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Nothing is dropped from the totals. Open the audit to spot-check every flagged or
          unparseable row by its source row number.
        </p>

        {/* KEPT INLINE — explains the headline totals (summary/total rows excluded). */}
        {summaryExcluded > 0 && (
          <p
            data-testid="summary-row-note"
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200"
          >
            {intFmt(summaryExcluded)} summary/total row{summaryExcluded === 1 ? '' : 's'} detected
            &amp; excluded
          </p>
        )}

        {noIssues ? (
          <p className="rounded-lg bg-green-50 p-6 text-center text-sm text-green-800 dark:bg-green-950/40 dark:text-green-300">
            No data-quality issues found — every row parsed cleanly.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setAuditOpen(true)}
              data-testid="data-quality-audit-button"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-900"
            >
              <svg
                className="h-4 w-4 text-slate-400 dark:text-slate-500"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.8}
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
                />
              </svg>
              {auditButtonLabel}
            </button>
            <span className="text-xs text-slate-400 dark:text-slate-500">Admin spot-check</span>
          </div>
        )}
      </div>

      {/* Data-quality audit — modal (admin/spot-check view) */}
      <Modal
        open={auditOpen}
        onClose={() => setAuditOpen(false)}
        title="Data-quality audit"
        titleId="data-quality-audit-title"
        description="Every flagged or unparseable row is listed here by its source row number — nothing is dropped from the totals."
        testId="data-quality-modal"
      >
        {/* Per-reason counts */}
        {reasonCounts.length > 0 && (
          <ul className="mb-4 flex flex-wrap gap-2" data-testid="data-quality-reasons">
            {reasonCounts.map(([reason, count]) => (
              <li
                key={reason}
                className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950/50 dark:text-amber-300"
              >
                {humanize(reason)}
                <span className="tabular-nums font-semibold">{intFmt(count)}</span>
              </li>
            ))}
          </ul>
        )}

        {rows.length === 0 ? (
          <p className="rounded-lg bg-green-50 p-6 text-center text-sm text-green-800 dark:bg-green-950/40 dark:text-green-300">
            No data-quality issues found — every row parsed cleanly.
          </p>
        ) : (
          <>
            {rowsCapped && (
              <p
                className="mb-2 text-xs text-slate-500 dark:text-slate-400"
                data-testid="data-quality-count"
              >
                Showing first {intFmt(visibleRows.length)} of {intFmt(rowsTotal)} rows
              </p>
            )}
            <div
              data-testid="data-quality-list"
              className="max-h-[60vh] overflow-auto rounded-xl border border-slate-200 dark:border-slate-700"
            >
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Audit list of flagged and unparseable rows</caption>
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-semibold">
                      Row #
                    </th>
                    <th scope="col" className="px-4 py-3 font-semibold">
                      Field
                    </th>
                    <th scope="col" className="px-4 py-3 font-semibold">
                      Reason
                    </th>
                    <th scope="col" className="px-4 py-3 font-semibold">
                      Raw value
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {visibleRows.map((r, i) => (
                    <tr key={`${r.row_index}-${r.field}-${i}`}>
                      <td className="px-4 py-3 tabular-nums text-slate-700 dark:text-slate-300">
                        {r.row_index}
                      </td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                        {fieldWord(r.field)}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
                          {humanize(r.reason)}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500 dark:text-slate-400">
                        {r.raw_value === '' || r.raw_value == null ? '—' : r.raw_value}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {rowsCapped && (
              <div className="mt-3 flex items-center justify-center">
                <button
                  type="button"
                  onClick={() => setShowAllRows((v) => !v)}
                  data-testid="data-quality-toggle"
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-900"
                >
                  {showAllRows ? `Show first ${DEFAULT_VISIBLE}` : `Show all ${intFmt(rowsTotal)} rows`}
                </button>
              </div>
            )}
          </>
        )}
      </Modal>
    </section>
  )
}
