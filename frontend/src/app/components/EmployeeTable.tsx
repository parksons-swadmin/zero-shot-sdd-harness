'use client'

// Employee-wise (salesperson) summary — Phase 2.
// Rendered in the order the backend returns it (ranked DESC by total_outstanding;
// ties → total_overdue desc → employee asc). The "(blank)" employee is a REAL row.
// The weighted-average days-overdue column is looked up from employee_breakdown by
// key === employee; it renders "—" when the employee has no overdue balance.

import { useMemo } from 'react'
import { inr, pct, intFmt, dpd, bucketLabel } from '@/lib/format'
import type { EmployeeSummary, GroupBreakdown } from '@/lib/types'

interface EmployeeTableProps {
  employees: EmployeeSummary[]
  employeeBreakdown: GroupBreakdown[]
}

export default function EmployeeTable({ employees, employeeBreakdown }: EmployeeTableProps) {
  // Map employee -> weighted-avg days overdue for the "Avg days overdue" column.
  const wavgByEmployee = useMemo(() => {
    const m = new Map<string, number | null>()
    for (const b of employeeBreakdown) m.set(b.key, b.weighted_avg_days_overdue)
    return m
  }, [employeeBreakdown])

  return (
    <section
      aria-labelledby="employee-table-heading"
      data-testid="employee-table"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <h3
        id="employee-table-heading"
        className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100"
      >
        Employee-wise summary
      </h3>
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        Each salesperson ranked by total outstanding — so you know who to chase first.
      </p>

      {employees.length === 0 ? (
        <p className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          No employee balances to summarise.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">Employee-wise outstanding and overdue summary</caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Employee
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  HoD Name
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Outstanding
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Overdue
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  % overdue
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Worst bucket
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Avg days overdue
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {employees.map((e) => {
                const isBlank = e.employee === '(blank)'
                return (
                  <tr key={e.employee}>
                    <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-200">
                      {isBlank ? (
                        <span className="italic text-slate-500 dark:text-slate-400">(blank)</span>
                      ) : (
                        e.employee
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {e.hod ? e.hod : <span className="text-slate-400 dark:text-slate-500">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-900 dark:text-slate-100">
                      {inr(e.total_outstanding)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-red-700 dark:text-red-400">
                      {inr(e.total_overdue)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                      {pct(e.pct_overdue)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {bucketLabel(e.worst_bucket)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                      {dpd(wavgByEmployee.get(e.employee) ?? null)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot className="border-t border-slate-200 bg-slate-50 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <td colSpan={7} className="px-4 py-2">
                  {intFmt(employees.length)} employee{employees.length === 1 ? '' : 's'} · ranked by
                  outstanding
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  )
}
