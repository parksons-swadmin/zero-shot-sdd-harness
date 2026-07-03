'use client'

import type { TableData } from '@/lib/types'

function renderCell(value: string | number | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return value
}

export default function ResultTable({ table }: { table: TableData | null | undefined }) {
  // Hidden entirely when the answer produced no table (e.g. a scalar result).
  if (!table || !table.columns || table.columns.length === 0) {
    return null
  }

  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-testid="result-table"
    >
      {table.title && (
        <h3 className="mb-2 text-sm font-semibold text-gray-900" data-testid="result-table-title">
          {table.title}
        </h3>
      )}
      <div className="max-h-72 overflow-auto rounded border border-gray-100">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-gray-50">
            <tr>
              {table.columns.map((col, idx) => (
                <th
                  key={`${col}-${idx}`}
                  className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rIdx) => (
              <tr key={rIdx} className="odd:bg-white even:bg-gray-50" data-testid="result-table-row">
                {row.map((cell, cIdx) => (
                  <td
                    key={cIdx}
                    className="border-b border-gray-100 px-3 py-1.5 text-gray-800"
                  >
                    {renderCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.truncated && (
        <p className="mt-1 text-xs text-gray-400" data-testid="result-table-caption">
          Showing {table.rows.length} of {table.total_rows.toLocaleString()} rows
        </p>
      )}
    </div>
  )
}
