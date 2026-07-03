'use client'

import { useRef, useState } from 'react'
import ProfileTable from '@/components/ProfileTable'
import CleaningReportList from '@/components/CleaningReportList'
import AnswerPanel from '@/components/AnswerPanel'
import StubPanel from '@/components/StubPanel'
import type { ApiEnvelope, DatasetResponse, MessageResponse, QueryResult, SessionResponse } from '@/lib/types'

type UploadState = 'idle' | 'uploading' | 'ready' | 'error'
type AskState = 'idle' | 'asking' | 'answered' | 'error'

export default function Home() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dataset, setDataset] = useState<DatasetResponse | null>(null)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [askState, setAskState] = useState<AskState>('idle')
  const [askError, setAskError] = useState<string | null>(null)
  const [answer, setAnswer] = useState<QueryResult | null>(null)

  async function uploadFile(file: File) {
    setUploadState('uploading')
    setUploadError(null)
    setDataset(null)
    setAnswer(null)
    setSessionId(null)
    setSessionError(null)

    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/datasets', { method: 'POST', body: form })
      const body: ApiEnvelope<DatasetResponse> = await res.json()

      if (!res.ok || body.error) {
        setUploadError(body.error?.message ?? `Upload failed (${res.status})`)
        setUploadState('error')
        return
      }

      setDataset(body.data)
      setUploadState('ready')

      // Automatically create a session scoped to this dataset, transparently.
      try {
        const sessionRes = await fetch('/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dataset_ids: [body.data!.dataset_id] }),
        })
        const sessionBody: ApiEnvelope<SessionResponse> = await sessionRes.json()
        if (!sessionRes.ok || sessionBody.error) {
          setSessionError(sessionBody.error?.message ?? `Could not start a session (${sessionRes.status})`)
        } else {
          setSessionId(sessionBody.data!.session_id)
        }
      } catch {
        setSessionError('Network error while starting a session — is the server running?')
      }
    } catch {
      setUploadError('Network error — is the server running?')
      setUploadState('error')
    }
  }

  function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) uploadFile(file)
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) uploadFile(file)
  }

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim() || !sessionId) return

    setAskState('asking')
    setAskError(null)
    setAnswer(null)

    try {
      const res = await fetch(`/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const body: ApiEnvelope<MessageResponse> = await res.json()

      if (!res.ok || body.error) {
        if (res.status === 409) {
          setAskError('Still working on the previous question — try again in a moment.')
        } else {
          setAskError(body.error?.message ?? `Request failed (${res.status})`)
        }
        setAskState('error')
        return
      }

      const result = body.data!.query_result
      if (result.status === 'failed') {
        setAskError(result.summary_text || "Couldn't answer that — the analysis code failed to run. Try rephrasing.")
        setAskState('error')
        return
      }

      setAnswer(result)
      setAskState('answered')
    } catch {
      setAskError('Network error — is the server running?')
      setAskState('error')
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Data Analyst Agent</h1>
          <p className="mt-1 text-sm text-gray-500">Upload a CSV, get an instant profile, ask questions about it.</p>
        </div>
        <span
          className="rounded-full bg-gray-200 px-3 py-1 text-xs font-medium text-gray-500"
          data-testid="cost-badge"
        >
          Cost tracking — coming soon
        </span>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
        {/* Main column */}
        <div className="space-y-6">
          {/* Upload panel */}
          <section>
            <h2 className="mb-2 text-lg font-semibold text-gray-900">1. Upload a dataset</h2>
            <div
              onDragOver={e => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click()
              }}
              className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
                dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white'
              }`}
              data-testid="upload-dropzone"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.tsv,.xlsx"
                className="hidden"
                onChange={handleFileSelected}
                data-testid="file-input"
              />
              {uploadState === 'idle' && (
                <p className="text-sm text-gray-500">Upload a CSV to get started — drag &amp; drop or click to browse</p>
              )}
              {uploadState === 'uploading' && (
                <p className="text-sm font-medium text-blue-600" data-testid="upload-loading">
                  Uploading and cleaning your file…
                </p>
              )}
              {uploadState === 'ready' && dataset && (
                <p className="text-sm font-medium text-green-700">
                  {dataset.filename} — {dataset.row_count.toLocaleString()} rows, {dataset.column_count} columns
                </p>
              )}
              {uploadState === 'error' && <p className="text-sm font-medium text-red-600">Click to try another file</p>}
            </div>

            {uploadError && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" data-testid="upload-error">
                {uploadError}
              </div>
            )}
            {sessionError && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700" data-testid="session-error">
                {sessionError}
              </div>
            )}
          </section>

          {/* Profile + cleaning report */}
          {dataset && (
            <>
              <section>
                <h2 className="mb-2 text-lg font-semibold text-gray-900">Auto-profile</h2>
                <ProfileTable columns={dataset.profile.columns} />
              </section>

              <section>
                <h2 className="mb-2 text-lg font-semibold text-gray-900">Cleaning report</h2>
                <CleaningReportList issues={dataset.cleaning_report.issues} />
              </section>
            </>
          )}

          {/* Ask panel */}
          <section>
            <h2 className="mb-2 text-lg font-semibold text-gray-900">2. Ask a question</h2>
            {!dataset && (
              <p className="text-sm text-gray-500" data-testid="ask-empty-state">
                Ask a question about your data once it&apos;s uploaded.
              </p>
            )}
            {dataset && (
              <form onSubmit={handleAsk} className="space-y-3">
                <textarea
                  className="w-full rounded-lg border border-gray-300 p-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  rows={2}
                  placeholder="e.g. what is the total revenue?"
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  disabled={askState === 'asking' || !sessionId}
                  data-testid="question-input"
                />
                <button
                  type="submit"
                  disabled={askState === 'asking' || !question.trim() || !sessionId}
                  className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  data-testid="ask-submit"
                >
                  {askState === 'asking' ? 'Thinking…' : 'Ask'}
                </button>
              </form>
            )}

            {askState === 'asking' && (
              <p className="mt-3 text-sm text-gray-500" data-testid="ask-loading">
                Thinking…
              </p>
            )}

            {askError && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" data-testid="ask-error">
                {askError}
              </div>
            )}

            {answer && (
              <div className="mt-4">
                <AnswerPanel result={answer} />
              </div>
            )}
          </section>

          {/* Suggested follow-ups stub */}
          <StubPanel
            title="Suggested follow-ups"
            caption="Follow-up suggestions — coming soon"
            testId="stub-follow-ups"
          >
            <div className="mt-2 flex flex-wrap gap-2">
              {['Suggested question one', 'Suggested question two', 'Suggested question three'].map(chip => (
                <span
                  key={chip}
                  className="cursor-not-allowed rounded-full bg-gray-200 px-3 py-1 text-xs text-gray-400"
                >
                  {chip}
                </span>
              ))}
            </div>
          </StubPanel>
        </div>

        {/* Sidebar: stubs */}
        <aside className="space-y-4">
          <StubPanel
            title="Library"
            caption="Multi-file library — coming in a future phase"
            testId="stub-library"
          >
            <ul className="mt-2 text-sm text-gray-500">
              {dataset ? <li>{dataset.filename}</li> : <li className="italic text-gray-400">No file uploaded yet</li>}
            </ul>
          </StubPanel>

          <StubPanel title="Charts" caption="Charts — coming soon" testId="stub-charts">
            <div className="mt-2 flex h-24 items-center justify-center rounded border border-gray-200 bg-gray-50 text-xs text-gray-400">
              Chart preview unavailable
            </div>
          </StubPanel>

          <div
            className="rounded-lg border border-dashed border-gray-300 bg-gray-100 p-4 opacity-70"
            data-testid="stub-export"
          >
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-500">Export</h3>
            </div>
            <button
              type="button"
              disabled
              title="Export — coming soon"
              className="w-full cursor-not-allowed rounded-lg bg-gray-300 px-4 py-2 text-sm font-medium text-gray-500"
            >
              Export
            </button>
            <p className="mt-1 text-xs text-gray-400">Export — coming soon</p>
          </div>

          <StubPanel title="Step tracking" caption="Step tracking — coming soon" testId="stub-step-progress">
            <div className="mt-2 h-2 w-full rounded-full bg-gray-200">
              <div className="h-2 w-1/4 rounded-full bg-gray-300" />
            </div>
          </StubPanel>
        </aside>
      </div>
    </main>
  )
}
