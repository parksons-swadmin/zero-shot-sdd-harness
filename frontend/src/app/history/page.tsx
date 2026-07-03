'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { getAuditLog } from '@/lib/api'
import type { AuditLogEntry } from '@/lib/types'

type LoadState = 'loading' | 'ready' | 'error'

const PAGE_SIZE = 50

const EVENT_TYPES = ['upload', 'clean', 'profile', 'ask', 'code_exec', 'answer', 'error']

// Format an ISO timestamp for display; falls back to the raw string if unparseable.
function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

// Build a short, raw-data-safe summary of an entry's `detail` metadata.
// The API guarantees `detail` holds only metadata (question text, generated code,
// step_count, status, export_dataset_id, sanitized error) — never row values.
function summarizeDetail(entry: AuditLogEntry): string {
  const detail = entry.detail
  if (!detail || typeof detail !== 'object') return '—'

  const question = detail['question']
  if (typeof question === 'string' && question.trim()) return question

  const code = detail['generated_code']
  if (typeof code === 'string' && code.trim()) {
    const snippet = code.trim().split('\n')[0]
    return snippet.length > 120 ? `${snippet.slice(0, 117)}…` : snippet
  }

  const parts: string[] = []
  const status = detail['status']
  if (typeof status === 'string') parts.push(`status: ${status}`)
  const stepCount = detail['step_count']
  if (typeof stepCount === 'number') parts.push(`steps: ${stepCount}`)
  const err = detail['error']
  if (typeof err === 'string' && err.trim()) parts.push(err)
  const exportId = detail['export_dataset_id']
  if (typeof exportId === 'string') parts.push('export produced')

  return parts.length > 0 ? parts.join(' · ') : '—'
}

function shortId(id: string | null): string {
  if (!id) return '—'
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

export default function HistoryPage() {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)

  // Filter controls.
  const [sessionId, setSessionId] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [eventType, setEventType] = useState('')

  const load = useCallback(async () => {
    setLoadState('loading')
    setErrorMsg(null)
    try {
      const data = await getAuditLog({
        session_id: sessionId.trim() || undefined,
        dataset_id: datasetId.trim() || undefined,
        event_type: eventType || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      setEntries(data.entries)
      setTotal(data.total)
      setLoadState('ready')
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to load the audit log.')
      setLoadState('error')
    }
  }, [sessionId, datasetId, eventType, offset])

  useEffect(() => {
    load()
  }, [load])

  function applyFilters(e: React.FormEvent) {
    e.preventDefault()
    setOffset(0)
    // load() re-runs via the effect when offset changes; if offset is already 0
    // the filter-state deps still re-trigger it.
    load()
  }

  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  return (
    <main className="mx-auto max-w-6xl px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Audit History</h1>
          <p className="mt-1 text-sm text-gray-500">
            Every question asked, code run, and result stored — timestamped, chronological.
          </p>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          data-testid="workspace-link"
        >
          ← Back to workspace
        </Link>
      </header>

      <form
        onSubmit={applyFilters}
        className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      >
        <label className="flex flex-col text-xs font-medium text-gray-600">
          Session ID
          <input
            type="text"
            value={sessionId}
            onChange={e => setSessionId(e.target.value)}
            placeholder="filter by session"
            className="mt-1 w-56 rounded border border-gray-300 px-2 py-1.5 text-sm"
            data-testid="filter-session"
          />
        </label>
        <label className="flex flex-col text-xs font-medium text-gray-600">
          Dataset ID
          <input
            type="text"
            value={datasetId}
            onChange={e => setDatasetId(e.target.value)}
            placeholder="filter by dataset"
            className="mt-1 w-56 rounded border border-gray-300 px-2 py-1.5 text-sm"
            data-testid="filter-dataset"
          />
        </label>
        <label className="flex flex-col text-xs font-medium text-gray-600">
          Event type
          <select
            value={eventType}
            onChange={e => setEventType(e.target.value)}
            className="mt-1 w-40 rounded border border-gray-300 px-2 py-1.5 text-sm"
            data-testid="filter-event-type"
          >
            <option value="">All events</option>
            {EVENT_TYPES.map(t => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          data-testid="apply-filters"
        >
          Apply
        </button>
      </form>

      {loadState === 'loading' && (
        <p className="text-sm text-gray-500" data-testid="audit-loading">
          Loading the audit trail…
        </p>
      )}

      {loadState === 'error' && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700" data-testid="audit-error">
          {errorMsg ?? "Couldn't load the audit log."}{' '}
          <button type="button" onClick={load} className="underline">
            Retry
          </button>
        </div>
      )}

      {loadState === 'ready' && entries.length === 0 && (
        <p className="text-sm italic text-gray-400" data-testid="audit-empty">
          No audit entries match these filters yet.
        </p>
      )}

      {loadState === 'ready' && entries.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="w-full border-collapse text-sm" data-testid="audit-table">
              <thead className="bg-gray-50">
                <tr>
                  <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">Timestamp</th>
                  <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">Event</th>
                  <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">Session</th>
                  <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">Dataset</th>
                  <th className="border-b border-gray-200 px-3 py-2 text-left font-semibold text-gray-700">Detail</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tr key={entry.id} className="odd:bg-white even:bg-gray-50" data-testid="audit-row">
                    <td className="whitespace-nowrap border-b border-gray-100 px-3 py-2 text-gray-600" data-testid="audit-timestamp">
                      {formatTimestamp(entry.created_at)}
                    </td>
                    <td className="border-b border-gray-100 px-3 py-2">
                      <span
                        className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700"
                        data-testid="audit-event-type"
                      >
                        {entry.event_type}
                      </span>
                    </td>
                    <td className="border-b border-gray-100 px-3 py-2 font-mono text-xs text-gray-500">
                      {entry.session_id ? (
                        <Link
                          href={`/?session_id=${entry.session_id}`}
                          className="text-blue-600 hover:underline"
                          data-testid="audit-session-link"
                        >
                          {shortId(entry.session_id)}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="border-b border-gray-100 px-3 py-2 font-mono text-xs text-gray-500">
                      {shortId(entry.dataset_id)}
                    </td>
                    <td className="max-w-md border-b border-gray-100 px-3 py-2 text-gray-800" data-testid="audit-detail">
                      <span className="block truncate font-mono text-xs">{summarizeDetail(entry)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-xs text-gray-500" data-testid="audit-count">
              Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
                disabled={!hasPrev}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                data-testid="page-prev"
              >
                ← Prev
              </button>
              <button
                type="button"
                onClick={() => setOffset(o => o + PAGE_SIZE)}
                disabled={!hasNext}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                data-testid="page-next"
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </main>
  )
}
