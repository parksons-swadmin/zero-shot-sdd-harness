'use client'

import { useCallback, useRef, useState } from 'react'

const MAX_MB = 25 // display note; the server (AGENT_MAX_UPLOAD_MB) is the authority.

interface UploadProps {
  onFileSelected: (file: File) => void
  loading: boolean
  error: string | null
  onRetry: () => void
}

function clientReject(file: File): string | null {
  if (!/\.xlsx$/i.test(file.name)) {
    return `“${file.name}” is not a .xlsx file. Export your AR aging as an Excel .xlsx workbook and try again.`
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    return `That file is larger than the ${MAX_MB} MB limit. Try a smaller export.`
  }
  return null
}

export default function Upload({ onFileSelected, loading, error, onRetry }: UploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const handleFile = useCallback(
    (file: File | undefined | null) => {
      if (!file) return
      const reason = clientReject(file)
      if (reason) {
        setLocalError(reason)
        return
      }
      setLocalError(null)
      onFileSelected(file)
    },
    [onFileSelected],
  )

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setDragging(false)
      handleFile(e.dataTransfer.files?.[0])
    },
    [handleFile],
  )

  const shownError = localError ?? error

  return (
    <section aria-labelledby="upload-heading" className="mx-auto max-w-2xl">
      <h2 id="upload-heading" className="mb-2 text-2xl font-semibold tracking-tight text-slate-900">
        Upload your AR aging export
      </h2>
      <p className="mb-6 text-sm text-slate-600">
        Everything runs on this machine — no data leaves your computer.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!loading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={loading ? (e) => e.preventDefault() : onDrop}
        className={[
          'rounded-2xl border-2 border-dashed p-10 text-center transition-colors',
          dragging ? 'border-blue-500 bg-blue-50' : 'border-slate-300 bg-white',
          loading ? 'opacity-60' : '',
        ].join(' ')}
      >
        {loading ? (
          <div className="flex flex-col items-center gap-3" role="status" aria-live="polite">
            <span
              className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-slate-700">Reading workbook…</p>
          </div>
        ) : (
          <>
            <svg
              className="mx-auto mb-4 h-10 w-10 text-slate-400"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
              />
            </svg>
            <p className="mb-1 text-base font-medium text-slate-800">
              Drag &amp; drop your AR aging file here
            </p>
            <p className="mb-5 text-sm text-slate-500">or</p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Choose file
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              onChange={(e) => {
                handleFile(e.target.files?.[0])
                // reset so re-selecting the same file re-fires onChange
                e.target.value = ''
              }}
            />
            <p className="mt-5 text-xs text-slate-500">
              <span className="font-medium">.xlsx only</span> · up to {MAX_MB} MB
            </p>
          </>
        )}
      </div>

      {shownError && (
        <div
          role="alert"
          className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          <p className="mb-3 font-medium">Couldn’t read that file</p>
          <p className="mb-4">{shownError}</p>
          <button
            type="button"
            onClick={() => {
              setLocalError(null)
              onRetry()
              inputRef.current?.click()
            }}
            className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
          >
            Choose a different file
          </button>
        </div>
      )}
    </section>
  )
}
