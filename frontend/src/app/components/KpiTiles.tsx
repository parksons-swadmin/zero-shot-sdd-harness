'use client'

import { inr, pct, intFmt } from '@/lib/format'
import type { Bucket, DashboardResult } from '@/lib/types'

const BUCKET_LABELS: Record<Bucket, string> = {
  '0-30': '0–30 days',
  '31-60': '31–60 days',
  '61-90': '61–90 days',
  '90+': '90+ days',
  none: 'None',
}

interface Tile {
  testid: string
  label: string
  value: string
  hint: string
  tone?: 'default' | 'danger'
}

function Card({ tile }: { tile: Tile }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{tile.label}</p>
      <p
        data-testid={tile.testid}
        className={[
          'mt-2 text-2xl font-semibold tracking-tight tabular-nums',
          tile.tone === 'danger' ? 'text-red-700' : 'text-slate-900',
        ].join(' ')}
      >
        {tile.value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{tile.hint}</p>
    </div>
  )
}

export default function KpiTiles({ result }: { result: DashboardResult }) {
  const tiles: Tile[] = [
    {
      testid: 'kpi-total-outstanding',
      label: 'Total outstanding',
      value: inr(result.total_outstanding),
      hint: 'All open balances',
    },
    {
      testid: 'kpi-total-overdue',
      label: 'Total overdue',
      value: inr(result.total_overdue),
      hint: 'Past the due date',
      tone: 'danger',
    },
    {
      testid: 'kpi-pct-overdue',
      label: '% overdue',
      value: pct(result.pct_overdue),
      hint: 'Overdue ÷ outstanding',
    },
    {
      testid: 'kpi-customer-count',
      label: 'Customers',
      value: intFmt(result.customer_count),
      hint: 'With an open balance',
    },
    {
      testid: 'kpi-worst-bucket',
      label: 'Worst aging bucket',
      value: BUCKET_LABELS[result.worst_bucket],
      hint: 'Deepest overdue band',
    },
  ]

  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
      aria-label="Headline KPIs"
    >
      {tiles.map((t) => (
        <Card key={t.testid} tile={t} />
      ))}
    </div>
  )
}
