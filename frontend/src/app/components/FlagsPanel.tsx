'use client'

// Proactive risk flags + data-quality audit — Phase 2.
// (1) Riskiest accounts: the backend-ranked risk_flags list (Beacon & Co first for
//     the demo file — deepest 90+ overdue).
// (2) Data-quality audit: per-reason counts + the full audit list of flagged/unparseable
//     rows (nothing is dropped silently). An explicit empty state when there are none.
//     User-feedback item: when by_reason["summary_row_excluded"] > 0, show a visible note.

import { useState } from 'react'
import { inr, intFmt, bucketLabel } from '@/lib/format'
import type { DataQuality, RiskFlag } from '@/lib/types'

interface FlagsPanelProps {
  riskFlags: RiskFlag[]
  dataQuality: DataQuality
}

// The data-quality audit list renders one <tr> per flagged/unparseable row. On a
// real export the audit list runs to ~2,900 rows (~15k DOM nodes) and committing
// them in one synchronous pass freezes the main thread for seconds — which also
// leaves the Recharts charts above measuring a stale/zero size (perceived as blank
// charts painting late). Capping to the first N keeps the render fast; a "Show all"
// control still exposes every row on demand. Mirrors the per-customer table cap in
// AgingBreakdown.tsx.
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
    dataQuality.flagged_row_count === 0 && dataQuality.unparseable_row_count === 0

  return (
    <section
      aria-labelledby="flags-panel-heading"
      data-testid="flags-panel"
      className="grid grid-cols-1 gap-6 lg:grid-cols-2"
    >
      <h3 id="flags-panel-heading" className="sr-only">
        Risk flags and data-quality audit
      </h3>

      {/* Riskiest accounts */}
      <div
        data-testid="risk-flags"
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h4 className="mb-1 text-lg font-semibold text-slate-900">Riskiest accounts</h4>
        <p className="mb-4 text-sm text-slate-500">
          Customers with the largest 90+ day overdue balances — chase these first.
        </p>

        {riskFlags.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">
            No accounts are deep in the 90+ bucket. Nothing to flag.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {riskFlags.map((f, i) => (
              <li
                key={`${f.customer}-${i}`}
                className="flex items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-800">{f.customer}</p>
                  <p className="text-xs text-slate-500">
                    {f.reason}
                    {f.bucket ? ` · ${bucketLabel(f.bucket)}` : ''}
                  </p>
                </div>
                <span className="shrink-0 tabular-nums font-semibold text-red-700">
                  {inr(f.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Data-quality audit */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h4 className="mb-1 text-lg font-semibold text-slate-900">Data-quality audit</h4>
        <p className="mb-4 text-sm text-slate-500">
          Every flagged or unparseable row is listed here by its source row number — nothing is
          dropped from the totals.
        </p>

        {/* User-feedback item: summary/total rows excluded from aggregation. */}
        {summaryExcluded > 0 && (
          <p
            data-testid="summary-row-note"
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"
          >
            {intFmt(summaryExcluded)} summary/total row{summaryExcluded === 1 ? '' : 's'} detected
            &amp; excluded
          </p>
        )}

        {/* Per-reason counts */}
        {reasonCounts.length > 0 && (
          <ul className="mb-4 flex flex-wrap gap-2">
            {reasonCounts.map(([reason, count]) => (
              <li
                key={reason}
                className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800"
              >
                {humanize(reason)}
                <span className="tabular-nums font-semibold">{intFmt(count)}</span>
              </li>
            ))}
          </ul>
        )}

        {noIssues && rows.length === 0 ? (
          <p className="rounded-lg bg-green-50 p-6 text-center text-sm text-green-800">
            No data-quality issues found — every row parsed cleanly.
          </p>
        ) : (
          <>
            {rowsCapped && (
              <p
                className="mb-2 text-xs text-slate-500"
                data-testid="data-quality-count"
              >
                Showing first {intFmt(visibleRows.length)} of {intFmt(rowsTotal)} rows
              </p>
            )}
            <div
              data-testid="data-quality-list"
              className="overflow-x-auto rounded-xl border border-slate-200"
            >
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Audit list of flagged and unparseable rows</caption>
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
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
                <tbody className="divide-y divide-slate-100">
                  {visibleRows.map((r, i) => (
                    <tr key={`${r.row_index}-${r.field}-${i}`}>
                      <td className="px-4 py-3 tabular-nums text-slate-700">{r.row_index}</td>
                      <td className="px-4 py-3 text-slate-700">{fieldWord(r.field)}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                          {humanize(r.reason)}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
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
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                >
                  {showAllRows ? `Show first ${DEFAULT_VISIBLE}` : `Show all ${intFmt(rowsTotal)} rows`}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
