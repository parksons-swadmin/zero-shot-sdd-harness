'use client'

import { useMemo } from 'react'
import {
  CANONICAL_FIELDS,
  FIELD_LABELS,
  type CanonicalField,
  type MatchStatus,
  type Mapping,
  type PreviewData,
} from '@/lib/types'
import { summarizeFlags } from '@/lib/flags'

interface MappingConfirmProps {
  preview: PreviewData
  sheetName: string
  onSheetChange: (sheet: string) => void
  mapping: Mapping
  onMappingChange: (field: CanonicalField | 'hod', column: string) => void
  onConfirm: () => void
  computing: boolean
  error: string | null
  onStartOver: () => void
}

type BadgeKind = 'ok' | 'confirm' | 'missing'

function Badge({ kind }: { kind: BadgeKind }) {
  if (kind === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-950/50 dark:text-green-300">
        <span aria-hidden="true">✓</span> Matched
      </span>
    )
  }
  if (kind === 'confirm') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
        <span aria-hidden="true">!</span> Please confirm
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950/50 dark:text-red-300">
      <span aria-hidden="true">×</span> Select a column
    </span>
  )
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return String(value)
  return String(value)
}

export default function MappingConfirm({
  preview,
  sheetName,
  onSheetChange,
  mapping,
  onMappingChange,
  onConfirm,
  computing,
  error,
  onStartOver,
}: MappingConfirmProps) {
  const detectedStatus = useMemo(() => {
    const m = new Map<CanonicalField, MatchStatus>()
    for (const fm of preview.proposed_mapping) {
      // `hod` is optional and mapped separately — the six-field status map ignores it.
      if (fm.field === 'hod') continue
      m.set(fm.field, fm.status)
    }
    return m
  }, [preview.proposed_mapping])

  const duplicateColumns = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of CANONICAL_FIELDS) {
      const col = mapping[f]
      if (col) counts.set(col, (counts.get(col) ?? 0) + 1)
    }
    const dupes = new Set<string>()
    for (const [col, n] of counts) if (n > 1) dupes.add(col)
    return dupes
  }, [mapping])

  const allMapped = CANONICAL_FIELDS.every((f) => Boolean(mapping[f]))
  const hasDuplicates = duplicateColumns.size > 0
  const canConfirm = allMapped && !hasDuplicates && !computing

  function badgeFor(field: CanonicalField): BadgeKind {
    const col = mapping[field]
    if (!col) return 'missing'
    return detectedStatus.get(field) === 'high' ? 'ok' : 'confirm'
  }

  const flagLines = summarizeFlags(preview.parse_flags)
  const previewRows = preview.preview_rows.slice(0, 10)

  return (
    <section aria-labelledby="mapping-heading" className="mx-auto max-w-4xl">
      <h2
        id="mapping-heading"
        className="mb-2 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100"
      >
        Confirm the column mapping
      </h2>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        We matched your columns to the six fields we need. Review each row, fix any that need
        attention, then compute the dashboard.
      </p>

      {preview.sheets.length > 1 && (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <label
            htmlFor="sheet-select"
            className="text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            Sheet
          </label>
          <select
            id="sheet-select"
            value={sheetName}
            disabled={computing}
            onChange={(e) => onSheetChange(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          >
            {preview.sheets.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Changing the sheet re-reads the workbook.
          </span>
        </div>
      )}

      {/* Mapping rows */}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Map each required field to a column from your file</caption>
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">
                Field we need
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Status
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Your column
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {CANONICAL_FIELDS.map((field) => {
              const col = mapping[field]
              const isDupe = Boolean(col) && duplicateColumns.has(col)
              const selectId = `map-${field}`
              return (
                <tr key={field} className={isDupe ? 'bg-red-50 dark:bg-red-950/30' : undefined}>
                  <td className="px-4 py-3">
                    <label
                      htmlFor={selectId}
                      className="font-medium text-slate-800 dark:text-slate-200"
                    >
                      {FIELD_LABELS[field]}
                    </label>
                  </td>
                  <td className="px-4 py-3">
                    <Badge kind={badgeFor(field)} />
                  </td>
                  <td className="px-4 py-3">
                    <select
                      id={selectId}
                      value={col}
                      disabled={computing}
                      aria-invalid={!col || isDupe}
                      onChange={(e) => onMappingChange(field, e.target.value)}
                      className={[
                        'w-full max-w-xs rounded-lg border bg-white px-3 py-1.5 text-sm shadow-sm focus:outline-none focus-visible:ring-1 dark:bg-slate-800 dark:text-slate-100',
                        !col || isDupe
                          ? 'border-red-400 focus:border-red-500 focus-visible:ring-red-500 dark:border-red-700'
                          : 'border-slate-300 focus:border-blue-500 focus-visible:ring-blue-500 dark:border-slate-600',
                        'disabled:opacity-50',
                      ].join(' ')}
                    >
                      <option value="">— Select a column —</option>
                      {preview.columns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    {isDupe && (
                      <p className="mt-1 text-xs text-red-700 dark:text-red-400">
                        Already mapped to another field.
                      </p>
                    )}
                  </td>
                </tr>
              )
            })}

            {/* OPTIONAL HoD (Head of Department) — never gates Confirm & Compute. */}
            <tr data-testid="hod-mapping-row">
              <td className="px-4 py-3">
                <label htmlFor="map-hod" className="font-medium text-slate-800 dark:text-slate-200">
                  HoD Name{' '}
                  <span className="font-normal text-slate-400 dark:text-slate-500">(optional)</span>
                </label>
              </td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  Optional
                </span>
              </td>
              <td className="px-4 py-3">
                <select
                  id="map-hod"
                  value={mapping.hod ?? ''}
                  disabled={computing}
                  onChange={(e) => onMappingChange('hod', e.target.value)}
                  className="w-full max-w-xs rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">— none —</option>
                  {preview.columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Adds a Head-of-Department column to the employee summary. Leave as “none” to skip.
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Parse-time data-quality warnings */}
      {flagLines.length > 0 && (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/40">
          <p className="mb-2 text-sm font-medium text-amber-900 dark:text-amber-200">
            Heads up — some rows have data-quality issues (they are kept, never dropped):
          </p>
          <ul className="list-inside list-disc space-y-1 text-sm text-amber-800 dark:text-amber-300">
            {flagLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Raw preview table */}
      <div className="mt-6">
        <h3 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
          Preview — first {previewRows.length} rows
        </h3>
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <table className="min-w-full text-left text-xs">
            <caption className="sr-only">A sample of the rows from your file</caption>
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                {preview.columns.map((c) => (
                  <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 font-semibold">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {previewRows.map((row, i) => (
                <tr key={i}>
                  {preview.columns.map((c) => (
                    <td
                      key={c}
                      className="whitespace-nowrap px-3 py-2 text-slate-700 dark:text-slate-300"
                    >
                      {cellText(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Compute error card */}
      {error && (
        <div
          role="alert"
          className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
        >
          <p className="mb-2 font-medium">We couldn’t compute the dashboard</p>
          <p className="mb-4">{error}</p>
          <button
            type="button"
            onClick={onStartOver}
            className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 dark:border-red-800 dark:bg-slate-900 dark:text-red-300 dark:hover:bg-red-950"
          >
            Start over
          </button>
        </div>
      )}

      {/* Actions */}
      <div className="mt-8 flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={onConfirm}
          disabled={!canConfirm}
          className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {computing ? 'Computing metrics…' : 'Confirm & Compute'}
        </button>
        <button
          type="button"
          onClick={onStartOver}
          disabled={computing}
          className="text-sm font-medium text-slate-600 underline-offset-2 hover:text-slate-900 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          Start over
        </button>
        {!canConfirm && !computing && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {!allMapped
              ? 'Map all six fields to continue.'
              : 'Each source column can map to only one field — fix the highlighted duplicates.'}
          </p>
        )}
      </div>

      {computing && (
        <div className="mt-4 flex items-center gap-2" role="status" aria-live="polite">
          <span
            className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600 dark:border-slate-600 dark:border-t-blue-400"
            aria-hidden="true"
          />
          <span className="text-sm text-slate-600 dark:text-slate-400">Computing metrics…</span>
        </div>
      )}
    </section>
  )
}
