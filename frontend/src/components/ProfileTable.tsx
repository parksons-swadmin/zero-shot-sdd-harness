import type { ProfileColumn } from '@/lib/types'

function formatNumber(n: number | null): string {
  if (n === null || n === undefined) return '—'
  return Number.isInteger(n) ? n.toString() : n.toFixed(2)
}

export default function ProfileTable({ columns }: { columns: ProfileColumn[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-gray-200 text-sm" data-testid="profile-table">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Column</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Type</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Nulls</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Distinct</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Min / Max</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Mean / Median</th>
            <th className="px-3 py-2 text-left font-semibold text-gray-700">Top values</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {columns.map(col => (
            <tr key={col.name} data-testid="profile-row">
              <td className="px-3 py-2 font-medium text-gray-900">{col.name}</td>
              <td className="px-3 py-2 text-gray-600">{col.dtype}</td>
              <td className="px-3 py-2 text-gray-600">{col.null_count}</td>
              <td className="px-3 py-2 text-gray-600">{col.distinct_count}</td>
              <td className="px-3 py-2 text-gray-600">
                {col.min !== null || col.max !== null
                  ? `${formatNumber(col.min)} / ${formatNumber(col.max)}`
                  : '—'}
              </td>
              <td className="px-3 py-2 text-gray-600">
                {col.mean !== null || col.median !== null
                  ? `${formatNumber(col.mean)} / ${formatNumber(col.median)}`
                  : '—'}
              </td>
              <td className="px-3 py-2 text-gray-600">
                {col.top_values && col.top_values.length > 0
                  ? col.top_values.map(tv => `${tv.value} (${tv.count})`).join(', ')
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
