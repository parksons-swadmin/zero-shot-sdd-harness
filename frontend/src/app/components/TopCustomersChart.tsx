'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { inr } from '@/lib/format'
import type { TopCustomer } from '@/lib/types'

/** Approximate compact ₹ label for axis ticks (exact values live in the tooltip). */
function compactInr(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(1)}Cr`
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(1)}L`
  if (a >= 1e3) return `₹${(v / 1e3).toFixed(0)}K`
  return `₹${v}`
}

interface TipProps {
  active?: boolean
  payload?: { payload: TopCustomer }[]
}

function CustomTooltip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-md">
      <p className="mb-1 font-semibold text-slate-900">{p.customer}</p>
      <p className="tabular-nums text-red-700">Overdue: {inr(p.overdue_amount)}</p>
      <p className="tabular-nums text-slate-600">Outstanding: {inr(p.outstanding_amount)}</p>
    </div>
  )
}

export default function TopCustomersChart({ data }: { data: TopCustomer[] }) {
  const hasData = data.length > 0 && data.some((d) => d.overdue_amount > 0)

  return (
    <section
      aria-labelledby="top-customers-heading"
      data-testid="top-customers-chart"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h3 id="top-customers-heading" className="mb-1 text-lg font-semibold text-slate-900">
        Top {Math.min(20, data.length) || 20} customers by overdue
      </h3>
      <p className="mb-4 text-sm text-slate-500">
        Longest bar first — hover a bar for the exact overdue and outstanding amounts.
      </p>

      {hasData ? (
        <div style={{ width: '100%', height: Math.max(280, data.length * 32 + 40) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={data}
              margin={{ top: 8, right: 28, bottom: 8, left: 8 }}
            >
              <CartesianGrid horizontal={false} stroke="#e2e8f0" />
              <XAxis
                type="number"
                tickFormatter={compactInr}
                tick={{ fontSize: 11, fill: '#64748b' }}
              />
              <YAxis
                type="category"
                dataKey="customer"
                width={160}
                tick={{ fontSize: 12, fill: '#334155' }}
                interval={0}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: '#f1f5f9' }} />
              <Bar
                dataKey="overdue_amount"
                name="Overdue"
                fill="#dc2626"
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">
          No overdue balances found — every account is within its due date.
        </p>
      )}
    </section>
  )
}
