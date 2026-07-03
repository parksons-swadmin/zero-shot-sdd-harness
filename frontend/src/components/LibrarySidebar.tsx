'use client'

import { useCallback, useEffect, useState } from 'react'
import type { ApiEnvelope, DatasetListItem, DatasetListResponse } from '@/lib/types'

type LoadState = 'loading' | 'ready' | 'error'

export default function LibrarySidebar({
  refreshKey = 0,
  onStartSession,
  starting = false,
}: {
  /** Bump this to force a re-fetch of the dataset list (e.g. after an upload). */
  refreshKey?: number
  /** Called with the checked dataset objects when the user starts a session. */
  onStartSession: (datasets: DatasetListItem[]) => void
  /** Parent-controlled flag while a session is being created/resumed. */
  starting?: boolean
}) {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  const [checked, setChecked] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    setLoadState('loading')
    try {
      const res = await fetch('/datasets')
      const body: ApiEnvelope<DatasetListResponse> = await res.json()
      if (!res.ok || body.error || !body.data) {
        setLoadState('error')
        return
      }
      setDatasets(body.data.datasets)
      setLoadState('ready')
    } catch {
      setLoadState('error')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  function toggle(id: string) {
    setChecked(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function handleStart() {
    const selected = datasets.filter(d => checked.has(d.dataset_id))
    if (selected.length === 0) return
    onStartSession(selected)
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm" data-testid="library-sidebar">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Library</h3>
        <button
          type="button"
          onClick={load}
          className="text-xs font-medium text-blue-600 hover:text-blue-700"
        >
          Refresh
        </button>
      </div>

      {loadState === 'loading' && (
        <p className="text-sm text-gray-500" data-testid="library-loading">
          Loading your library…
        </p>
      )}

      {loadState === 'error' && (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700" data-testid="library-error">
          Couldn&apos;t load your library.{' '}
          <button type="button" onClick={load} className="underline">
            Retry
          </button>
        </div>
      )}

      {loadState === 'ready' && datasets.length === 0 && (
        <p className="text-sm italic text-gray-400" data-testid="library-empty">
          No files uploaded yet — upload a CSV to get started.
        </p>
      )}

      {loadState === 'ready' && datasets.length > 0 && (
        <>
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {datasets.map(ds => (
              <li key={ds.dataset_id} data-testid="library-item">
                <label className="flex cursor-pointer items-start gap-2 rounded p-1.5 text-sm hover:bg-gray-50">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={checked.has(ds.dataset_id)}
                    onChange={() => toggle(ds.dataset_id)}
                    data-testid="library-item-checkbox"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-gray-800">{ds.filename}</span>
                    <span className="block text-xs text-gray-500">
                      {ds.row_count.toLocaleString()} rows · {ds.column_count} cols
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>

          <button
            type="button"
            onClick={handleStart}
            disabled={checked.size === 0 || starting}
            className="mt-3 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            data-testid="start-session"
          >
            {starting ? 'Starting…' : `Start session${checked.size > 0 ? ` (${checked.size})` : ''}`}
          </button>
        </>
      )}
    </div>
  )
}
