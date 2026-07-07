'use client'

// Invoice drill-down — an INLINE dashboard section (not a modal). Lets the user
// scope the underlying invoice list to an exact customer and/or employee (ANDed),
// sort it, and read a filtered subtotal + count that ties out to the dashboard.
//
// Data comes from POST /api/invoices (re-posts the file + confirmed mapping). A
// filtered request returns ALL matching rows (truncated=false); an unfiltered one
// is capped server-side (truncated=true) while total_count / subtotal_amount still
// cover the full set. We additionally cap the RENDERED rows for perf (mirroring
// AgingBreakdown) with a "Show all" toggle — but the subtotal/count line always
// comes from the response, never the rendered slice.
//
// The whole section is `no-print` (exploratory — keep exported PDFs clean).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { postInvoices } from '@/lib/api'
import { inr, dpd, bucketLabel, intFmt } from '@/lib/format'
import type { DashboardResult, InvoiceListData, Mapping } from '@/lib/types'

interface DrilldownProps {
  result: DashboardResult
  file: File
  mapping: Mapping
  sheetName: string
  /** Employee to pre-select as the filter when opened from an employee row ('' = none). */
  presetEmployee: string
  /**
   * Bumped by the parent every time it wants to (re)apply `presetEmployee` — e.g.
   * an employee row click, or the plain "Drill down" toggle re-opening unfiltered.
   * Watching the nonce (not the value) lets the same employee be re-applied.
   */
  presetNonce: number
}

type SortKey = 'customer' | 'invoice_no' | 'amount' | 'due_date' | 'days_overdue' | 'bucket'
type SortDir = 'asc' | 'desc'

// Cap the RENDERED rows so a large capped/filtered response never commits tens of
// thousands of DOM nodes in one synchronous pass. The subtotal/count line is always
// driven by the response totals, so it stays correct regardless of what is rendered.
const RENDER_CAP = 200

// Suggestions shown in the customer picker at once (the real option list is ~1000+).
const MAX_SUGGESTIONS = 50

const COLUMNS: { key: SortKey; label: string; align: 'left' | 'right' }[] = [
  { key: 'customer', label: 'Customer', align: 'left' },
  { key: 'invoice_no', label: 'Invoice no.', align: 'left' },
  { key: 'amount', label: 'Amount due', align: 'right' },
  { key: 'due_date', label: 'Due date', align: 'left' },
  { key: 'days_overdue', label: 'Days overdue', align: 'right' },
  { key: 'bucket', label: 'Aging bucket', align: 'left' },
]

/** Columns whose most-useful first look is largest-first. */
const DESC_FIRST: ReadonlySet<SortKey> = new Set<SortKey>(['amount', 'days_overdue'])

function blankAware(label: string) {
  return label === '(blank)' ? (
    <span className="italic text-slate-500 dark:text-slate-400">(blank)</span>
  ) : (
    label
  )
}

export default function Drilldown({
  result,
  file,
  mapping,
  sheetName,
  presetEmployee,
  presetNonce,
}: DrilldownProps) {
  // Confirmed filter values (drive the fetch). Initialised from the preset so the
  // FIRST fetch on mount already carries the employee when opened from a row.
  const [customer, setCustomer] = useState('')
  const [employee, setEmployee] = useState(presetEmployee)
  // The customer picker's free-text query (filters the suggestion list client-side).
  const [customerQuery, setCustomerQuery] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)

  const [data, setData] = useState<InvoiceListData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [sortKey, setSortKey] = useState<SortKey>('days_overdue')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [showAll, setShowAll] = useState(false)

  const customerOptions = useMemo(
    () => (result.customer_breakdown ?? []).map((c) => c.key),
    [result],
  )
  const employeeOptions = useMemo(
    () => (result.employees ?? []).map((e) => e.employee),
    [result],
  )

  const filteredCustomers = useMemo(() => {
    const q = customerQuery.trim().toLowerCase()
    const base = q ? customerOptions.filter((c) => c.toLowerCase().includes(q)) : customerOptions
    return base.slice(0, MAX_SUGGESTIONS)
  }, [customerOptions, customerQuery])

  // Re-apply the parent's requested employee filter whenever the nonce bumps
  // (employee row click, or the plain toggle re-opening unfiltered). Clears the
  // customer filter so the two never combine unexpectedly on a fresh open.
  useEffect(() => {
    setEmployee(presetEmployee)
    setCustomer('')
    setCustomerQuery('')
    setPickerOpen(false)
    setShowAll(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally keyed on the nonce only
  }, [presetNonce])

  // Fetch the (optionally filtered) invoice list. Fires on mount and whenever a
  // confirmed filter changes. A `cancelled` guard drops a stale response so a
  // fast filter change never renders an out-of-order result.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    postInvoices(file, mapping, sheetName, {
      customer: customer || undefined,
      employee: employee || undefined,
    })
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        if (!cancelled) {
          setData(null)
          setError(e instanceof Error ? e.message : 'Could not load the invoice list.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [customer, employee, file, mapping, sheetName])

  const sortedRows = useMemo(() => {
    const rows = data?.invoices ?? []
    return [...rows].sort((a, b) => {
      const va = a[sortKey]
      const vb = b[sortKey]
      // Nulls (missing invoice no / due date / days overdue) always sort LAST,
      // regardless of direction — they carry no meaningful order.
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const base =
        typeof va === 'number' && typeof vb === 'number'
          ? va - vb
          : String(va).localeCompare(String(vb))
      return sortDir === 'asc' ? base : -base
    })
  }, [data, sortKey, sortDir])

  const renderCapped = sortedRows.length > RENDER_CAP
  const renderedRows = showAll ? sortedRows : sortedRows.slice(0, RENDER_CAP)

  const onSort = useCallback(
    (key: SortKey) => {
      if (key === sortKey) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      } else {
        setSortKey(key)
        setSortDir(DESC_FIRST.has(key) ? 'desc' : 'asc')
      }
    },
    [sortKey],
  )

  const selectCustomer = useCallback((c: string) => {
    setCustomer(c)
    setCustomerQuery(c)
    setPickerOpen(false)
    setShowAll(false)
  }, [])

  const clearFilters = useCallback(() => {
    setCustomer('')
    setCustomerQuery('')
    setEmployee('')
    setPickerOpen(false)
    setShowAll(false)
  }, [])

  const hasFilter = Boolean(customer || employee)
  const scopeLabel = customer || employee || 'All'

  const inputCls =
    'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500'

  return (
    <section
      id="drilldown"
      data-testid="drilldown"
      aria-labelledby="drilldown-heading"
      className="no-print rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <h3
        id="drilldown-heading"
        className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100"
      >
        Invoice drill-down
      </h3>
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        Scope the underlying invoices to a customer and/or employee, sort any column, and read a
        subtotal that ties out to the dashboard.
      </p>

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <label
            htmlFor="drilldown-customer-input"
            className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Customer
          </label>
          <input
            id="drilldown-customer-input"
            data-testid="drilldown-customer-input"
            type="text"
            role="combobox"
            aria-expanded={pickerOpen}
            aria-controls="drilldown-customer-options"
            aria-autocomplete="list"
            autoComplete="off"
            placeholder="Search customer…"
            value={customerQuery}
            onChange={(e) => {
              setCustomerQuery(e.target.value)
              setPickerOpen(true)
            }}
            onFocus={() => setPickerOpen(true)}
            onBlur={() => window.setTimeout(() => setPickerOpen(false), 120)}
            className={inputCls}
          />
          {pickerOpen && filteredCustomers.length > 0 && (
            <ul
              id="drilldown-customer-options"
              data-testid="drilldown-customer-options"
              role="listbox"
              className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800"
            >
              {filteredCustomers.map((c) => (
                <li key={c}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={c === customer}
                    data-testid="drilldown-customer-option"
                    // Prevent the input blur from firing before the click registers.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectCustomer(c)}
                    className="block w-full px-3 py-2 text-left text-slate-700 hover:bg-slate-100 focus:bg-slate-100 focus:outline-none dark:text-slate-200 dark:hover:bg-slate-700 dark:focus:bg-slate-700"
                  >
                    {blankAware(c)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-w-0 sm:w-56">
          <label
            htmlFor="drilldown-employee-select"
            className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Employee
          </label>
          <select
            id="drilldown-employee-select"
            data-testid="drilldown-employee-select"
            value={employee}
            onChange={(e) => {
              setEmployee(e.target.value)
              setShowAll(false)
            }}
            className={inputCls}
          >
            <option value="">All employees</option>
            {employeeOptions.map((e) => (
              <option key={e} value={e}>
                {e === '(blank)' ? '(blank)' : e}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          data-testid="drilldown-clear"
          onClick={clearFilters}
          disabled={!hasFilter && !customerQuery}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-900"
        >
          Clear filters
        </button>
      </div>

      {/* Filtered subtotal + count (always from the response totals, never the slice) */}
      {!loading && !error && data && (
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <p
            data-testid="drilldown-subtotal"
            className="text-sm font-semibold text-slate-900 dark:text-slate-100"
          >
            <span className="text-slate-600 dark:text-slate-300">{scopeLabel}:</span>{' '}
            {intFmt(data.total_count)} invoice{data.total_count === 1 ? '' : 's'} ·{' '}
            <span className="tabular-nums">{inr(data.subtotal_amount)}</span>
          </p>
          {data.truncated && (
            <p
              data-testid="drilldown-truncated"
              className="text-xs text-amber-700 dark:text-amber-400"
            >
              Showing first {intFmt(data.invoices.length)} of {intFmt(data.total_count)} — filter by
              customer or employee to see all.
            </p>
          )}
        </div>
      )}

      {/* Body: error | loading | empty | table */}
      {error ? (
        <p
          role="alert"
          data-testid="drilldown-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </p>
      ) : loading ? (
        <div
          data-testid="drilldown-loading"
          role="status"
          aria-live="polite"
          className="flex items-center justify-center gap-3 p-10 text-sm text-slate-500 dark:text-slate-400"
        >
          <span
            aria-hidden="true"
            className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-blue-500 dark:border-slate-600 dark:border-t-blue-400"
          />
          Loading invoices…
        </div>
      ) : data && data.invoices.length === 0 ? (
        <p
          data-testid="drilldown-empty"
          className="rounded-lg bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400"
        >
          No invoices match {scopeLabel === 'All' ? 'the current view' : `“${scopeLabel}”`}.
        </p>
      ) : data ? (
        <>
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
            <table data-testid="drilldown-table" className="min-w-full text-left text-sm">
              <caption className="sr-only">
                Invoice-level drill-down for {scopeLabel}
              </caption>
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  {COLUMNS.map((col) => {
                    const active = sortKey === col.key
                    return (
                      <th
                        key={col.key}
                        scope="col"
                        aria-sort={
                          active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'
                        }
                        className={`px-4 py-3 font-semibold ${col.align === 'right' ? 'text-right' : ''}`}
                      >
                        <button
                          type="button"
                          data-testid={`drilldown-sort-${col.key}`}
                          onClick={() => onSort(col.key)}
                          className={`inline-flex items-center gap-1 rounded uppercase tracking-wide hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:text-slate-200 ${
                            col.align === 'right' ? 'flex-row-reverse' : ''
                          } ${active ? 'text-slate-800 dark:text-slate-200' : ''}`}
                          aria-label={`Sort by ${col.label}`}
                        >
                          {col.label}
                          <span aria-hidden="true" className="text-[0.65rem]">
                            {active ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                          </span>
                        </button>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {renderedRows.map((row, i) => (
                  <tr key={`${row.invoice_no ?? 'no-inv'}-${i}`} data-testid="drilldown-row">
                    <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-800 dark:text-slate-200">
                      {blankAware(row.customer)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {row.invoice_no ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-900 dark:text-slate-100">
                      {inr(row.amount)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums text-slate-700 dark:text-slate-300">
                      {row.due_date ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                      {dpd(row.days_overdue)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {bucketLabel(row.bucket)}
                    </td>
                  </tr>
                ))}
              </tbody>
              {/* Total row — sums the Amount Due column over the FULL filtered set
                  (data.subtotal_amount / total_count), so it stays exact even when the
                  rendered rows are capped. */}
              <tfoot className="border-t-2 border-slate-300 bg-slate-50 font-semibold dark:border-slate-600 dark:bg-slate-800">
                <tr data-testid="drilldown-total-row">
                  <td colSpan={2} className="px-4 py-3 text-slate-900 dark:text-slate-100">
                    Total · {intFmt(data.total_count)} invoice{data.total_count === 1 ? '' : 's'}
                  </td>
                  <td
                    data-testid="drilldown-total-amount"
                    className="px-4 py-3 text-right tabular-nums text-slate-900 dark:text-slate-100"
                  >
                    {inr(data.subtotal_amount)}
                  </td>
                  <td colSpan={3} className="px-4 py-3" />
                </tr>
              </tfoot>
            </table>
          </div>

          {renderCapped && (
            <div className="mt-3 flex items-center justify-center">
              <button
                type="button"
                data-testid="drilldown-showall"
                onClick={() => setShowAll((v) => !v)}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-900"
              >
                {showAll
                  ? `Show first ${RENDER_CAP}`
                  : `Show all ${intFmt(sortedRows.length)} loaded rows`}
              </button>
            </div>
          )}
        </>
      ) : null}
    </section>
  )
}
