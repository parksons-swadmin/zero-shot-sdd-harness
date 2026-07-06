'use client'

// Aging breakdown — Phase 2.
// (1) An overall segmented/stacked bar of the five buckets (current + four overdue),
//     older buckets in the red family, with a legend and ₹ tooltips.
// (2) A per-customer breakdown table: the five bucket amounts, % overdue, and the
//     amount-weighted average days-overdue ("—" when the customer has no overdue).

import { useState } from 'react'
import { Bar, BarChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { inr, pct, dpd, intFmt } from '@/lib/format'
import type { BucketTotals, GroupBreakdown } from '@/lib/types'

interface AgingBreakdownProps {
  bucketTotals: BucketTotals
  customerBreakdown: GroupBreakdown[]
}

// The per-customer table renders the TOP customers by outstanding (the backend
// already ranks customer_breakdown outstanding-desc). Rendering all rows at once
// on a real export (1000+ customers) commits tens of thousands of DOM nodes in one
// synchronous pass — that freezes the page for seconds and can leave the Recharts
// chart above it measuring a stale/zero size (perceived as a blank chart). Capping
// the table to the top N keeps the page fast; a "Show all" control still exposes
// every row on demand.
const DEFAULT_VISIBLE = 25

// The five bucket segments, in aging order. Older = deeper red; current = cool.
const SEGMENTS: { key: keyof BucketTotals; label: string; color: string }[] = [
  { key: 'current', label: 'Current', color: '#0ea5e9' },
  { key: 'b_0_30', label: '0–30 days', color: '#fca5a5' },
  { key: 'b_31_60', label: '31–60 days', color: '#f87171' },
  { key: 'b_61_90', label: '61–90 days', color: '#ef4444' },
  { key: 'b_90_plus', label: '90+ days', color: '#b91c1c' },
]

/** Compact ₹ tick (exact amounts live in the tooltip / table). */
function compactInr(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(1)}Cr`
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(1)}L`
  if (a >= 1e3) return `₹${(v / 1e3).toFixed(0)}K`
  return `₹${v}`
}

interface TipProps {
  active?: boolean
  payload?: { name: string; value: number; color: string }[]
}

function ChartTooltip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-md">
      {payload.map((p) => (
        <p key={p.name} className="tabular-nums" style={{ color: p.color }}>
          {p.name}: {inr(p.value)}
        </p>
      ))}
    </div>
  )
}

export default function AgingBreakdown({ bucketTotals, customerBreakdown }: AgingBreakdownProps) {
  const [showAll, setShowAll] = useState(false)
  const total = customerBreakdown.length
  const isCapped = total > DEFAULT_VISIBLE
  const visibleRows = showAll ? customerBreakdown : customerBreakdown.slice(0, DEFAULT_VISIBLE)

  const chartData = [
    {
      name: 'All accounts',
      current: bucketTotals.current,
      b_0_30: bucketTotals.b_0_30,
      b_31_60: bucketTotals.b_31_60,
      b_61_90: bucketTotals.b_61_90,
      b_90_plus: bucketTotals.b_90_plus,
    },
  ]

  return (
    <section
      aria-labelledby="aging-breakdown-heading"
      data-testid="aging-breakdown"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h3 id="aging-breakdown-heading" className="mb-1 text-lg font-semibold text-slate-900">
        Aging breakdown
      </h3>
      <p className="mb-4 text-sm text-slate-500">
        How the total outstanding splits across the aging buckets, and each customer&apos;s
        weighted-average days overdue.
      </p>

      {/* Overall segmented bar */}
      <div data-testid="aging-breakdown-chart" style={{ width: '100%', height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={chartData}
            margin={{ top: 8, right: 28, bottom: 8, left: 8 }}
          >
            <XAxis type="number" tickFormatter={compactInr} tick={{ fontSize: 11, fill: '#64748b' }} />
            <YAxis
              type="category"
              dataKey="name"
              width={90}
              tick={{ fontSize: 12, fill: '#334155' }}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: '#f1f5f9' }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {SEGMENTS.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                stackId="aging"
                name={s.label}
                fill={s.color}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Per-customer breakdown table */}
      <div className="mt-6">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="text-sm font-semibold text-slate-700">Per-customer breakdown</h4>
          {isCapped && (
            <span className="text-xs text-slate-500" data-testid="customer-breakdown-count">
              Showing top {intFmt(visibleRows.length)} of {intFmt(total)} customers by outstanding
            </span>
          )}
        </div>
        {customerBreakdown.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">
            No customer balances to break down.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table
              data-testid="customer-breakdown-table"
              className="min-w-full text-left text-sm"
            >
              <caption className="sr-only">Per-customer aging bucket amounts</caption>
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Customer
                  </th>
                  {SEGMENTS.map((s) => (
                    <th key={s.key} scope="col" className="px-4 py-3 text-right font-semibold">
                      {s.label}
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    % overdue
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    Avg days overdue
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleRows.map((c) => {
                  const isBlank = c.key === '(blank)'
                  return (
                    <tr key={c.key}>
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-800">
                        {isBlank ? <span className="italic text-slate-500">(blank)</span> : c.key}
                      </td>
                      {SEGMENTS.map((s) => (
                        <td
                          key={s.key}
                          className="px-4 py-3 text-right tabular-nums text-slate-700"
                        >
                          {inr(c.bucket_totals[s.key])}
                        </td>
                      ))}
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {pct(c.pct_overdue)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {dpd(c.weighted_avg_days_overdue)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {isCapped && (
          <div className="mt-3 flex items-center justify-center">
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              data-testid="customer-breakdown-toggle"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              {showAll ? `Show top ${DEFAULT_VISIBLE}` : `Show all ${intFmt(total)} customers`}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
