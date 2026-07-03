'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartSpec } from '@/lib/types'

// A small qualitative palette for pie slices / bar fills.
const PALETTE = ['#2563eb', '#16a34a', '#f59e0b', '#db2777', '#7c3aed', '#0891b2', '#dc2626', '#65a30d']

export default function ChartPanel({ chartSpec }: { chartSpec: ChartSpec | null | undefined }) {
  // When the answer produced no chart (scalar result or no chart intent), show a
  // small caption rather than the old "coming soon" placeholder — never a bug.
  if (!chartSpec || !chartSpec.series || chartSpec.series.length === 0) {
    return (
      <div
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        data-testid="chart-panel"
      >
        <h3 className="mb-1 text-sm font-semibold text-gray-900">Chart</h3>
        <p className="text-xs italic text-gray-400" data-testid="chart-empty">
          No chart for this answer
        </p>
      </div>
    )
  }

  // recharts renders from an array of objects keyed by the axis labels.
  const data = chartSpec.series.map(point => ({ x: point.x, y: point.y }))

  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-testid="chart-panel"
    >
      <h3 className="mb-2 text-sm font-semibold text-gray-900" data-testid="chart-title">
        {chartSpec.title}
      </h3>
      <div className="h-64 w-full" data-testid="chart-container" data-chart-type={chartSpec.type}>
        <ResponsiveContainer width="100%" height="100%">
          {renderChart(chartSpec, data)}
        </ResponsiveContainer>
      </div>
      {chartSpec.truncated && (
        <p className="mt-1 text-xs text-gray-400" data-testid="chart-truncated">
          Showing the first {chartSpec.series.length} points of a larger series.
        </p>
      )}
    </div>
  )
}

function renderChart(
  chartSpec: ChartSpec,
  data: Array<{ x: string | number; y: number }>,
) {
  if (chartSpec.type === 'line') {
    return (
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="x" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Line type="monotone" dataKey="y" name={chartSpec.y_label} stroke="#2563eb" dot={false} />
      </LineChart>
    )
  }

  if (chartSpec.type === 'pie') {
    return (
      <PieChart>
        <Tooltip />
        <Legend />
        <Pie data={data} dataKey="y" nameKey="x" outerRadius="80%" label>
          {data.map((_, idx) => (
            <Cell key={idx} fill={PALETTE[idx % PALETTE.length]} />
          ))}
        </Pie>
      </PieChart>
    )
  }

  // Default: bar chart.
  return (
    <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
      <XAxis dataKey="x" tick={{ fontSize: 11 }} />
      <YAxis tick={{ fontSize: 11 }} />
      <Tooltip />
      <Bar dataKey="y" name={chartSpec.y_label} fill="#2563eb" />
    </BarChart>
  )
}
