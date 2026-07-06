'use client'

import { useCallback, useState } from 'react'
import Upload from './components/Upload'
import MappingConfirm from './components/MappingConfirm'
import KpiTiles from './components/KpiTiles'
import TopCustomersChart from './components/TopCustomersChart'
import EmployeeTable from './components/EmployeeTable'
import AgingBreakdown from './components/AgingBreakdown'
import FlagsPanel from './components/FlagsPanel'
import ExportBar from './components/ExportBar'
import ProgressBar from './components/ProgressBar'
import { computeStream, postCompute, postPreview } from '@/lib/api'
import { intFmt } from '@/lib/format'
import {
  CANONICAL_FIELDS,
  type CanonicalField,
  type ComputeProgress,
  type DashboardResult,
  type Mapping,
  type PreviewData,
} from '@/lib/types'

type Step = 'upload' | 'mapping' | 'dashboard'

function buildMapping(preview: PreviewData): Mapping {
  const byField = new Map(preview.proposed_mapping.map((fm) => [fm.field, fm.matched_column]))
  const m = {} as Mapping
  for (const f of CANONICAL_FIELDS) m[f] = byField.get(f) ?? ''
  // OPTIONAL hod — pre-select the backend's proposed column when it matched one.
  m.hod = byField.get('hod') ?? ''
  return m
}

export default function Home() {
  const [step, setStep] = useState<Step>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [sheetName, setSheetName] = useState<string>('')
  const [mapping, setMapping] = useState<Mapping>({} as Mapping)
  const [result, setResult] = useState<DashboardResult | null>(null)

  const [previewing, setPreviewing] = useState(false)
  const [computing, setComputing] = useState(false)
  const [progress, setProgress] = useState<ComputeProgress | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [computeError, setComputeError] = useState<string | null>(null)
  // True when the mapping was auto-applied (a recognized standard export) and we
  // skipped the confirm screen — drives the dismissible dashboard banner.
  const [autoMapped, setAutoMapped] = useState(false)
  const [bannerDismissed, setBannerDismissed] = useState(false)

  // Run compute for an EXPLICIT mapping (never the closed-over state), so the
  // auto-skip path can compute the freshly-built mapping without waiting for a
  // React state flush. Returns true when the dashboard rendered, false on error
  // (computeError is set, and the caller decides where to land).
  const runCompute = useCallback(
    async (f: File, m: Mapping, sheet: string): Promise<boolean> => {
      setComputing(true)
      setComputeError(null)
      // Show the progress bar immediately; the streamed frames fill in real row counts.
      setProgress({ phase: 'starting', rows_done: 0, rows_total: 0 })
      try {
        let data: DashboardResult
        try {
          // Preferred path: SSE stream with live progress for large files.
          data = await computeStream(f, m, sheet, (p) => setProgress(p))
        } catch {
          // Stream unavailable / failed for any reason → fall back to the plain
          // non-streaming compute so the dashboard still renders (no progress bar).
          data = await postCompute(f, m, sheet)
        }
        setResult(data)
        setStep('dashboard')
        return true
      } catch (e) {
        setComputeError(e instanceof Error ? e.message : 'Could not compute the metrics.')
        return false
      } finally {
        setComputing(false)
        setProgress(null)
      }
    },
    [],
  )

  const runPreview = useCallback(
    async (f: File, sheet?: string) => {
      setPreviewing(true)
      setUploadError(null)
      setComputeError(null)
      try {
        const data = await postPreview(f, sheet)
        setPreview(data)
        setSheetName(data.sheet_name)
        // Build the mapping from proposed_mapping (INCLUDING the optional hod when
        // present) so the auto-skip compute — and the pre-filled confirm screen —
        // both carry every detected column.
        const m = buildMapping(data)
        setMapping(m)
        if (data.auto_mapped) {
          // Recognized standard export → skip the confirm screen and compute now.
          setAutoMapped(true)
          setBannerDismissed(false)
          const ok = await runCompute(f, m, data.sheet_name)
          if (!ok) {
            // Compute failed — fall back to the confirm screen (pre-filled) so the
            // user can adjust the mapping and retry; the error shows there.
            setStep('mapping')
          }
        } else {
          // Low-confidence / non-standard export → confirm screen, exactly as before.
          setAutoMapped(false)
          setStep('mapping')
        }
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : 'Could not read the workbook.')
        setStep('upload')
      } finally {
        setPreviewing(false)
      }
    },
    [runCompute],
  )

  const onFileSelected = useCallback(
    (f: File) => {
      setFile(f)
      void runPreview(f)
    },
    [runPreview],
  )

  const onSheetChange = useCallback(
    (sheet: string) => {
      if (!file) return
      setSheetName(sheet)
      void runPreview(file, sheet)
    },
    [file, runPreview],
  )

  const onMappingChange = useCallback((field: CanonicalField | 'hod', column: string) => {
    setMapping((prev) => ({ ...prev, [field]: column }))
  }, [])

  const onConfirm = useCallback(async () => {
    if (!file) return
    const ok = await runCompute(file, mapping, sheetName)
    // The user manually reviewed & confirmed the mapping — it is no longer an
    // untouched auto-map, so retire the auto-mapped banner.
    if (ok) setAutoMapped(false)
  }, [file, mapping, sheetName, runCompute])

  // Banner action: reopen the confirm screen PRE-FILLED with the current mapping.
  const onReviewMapping = useCallback(() => {
    setComputeError(null)
    setStep('mapping')
  }, [])

  const onDismissBanner = useCallback(() => setBannerDismissed(true), [])

  const startOver = useCallback(() => {
    setStep('upload')
    setFile(null)
    setPreview(null)
    setSheetName('')
    setMapping({} as Mapping)
    setResult(null)
    setUploadError(null)
    setComputeError(null)
    setPreviewing(false)
    setComputing(false)
    setProgress(null)
    setAutoMapped(false)
    setBannerDismissed(false)
  }, [])

  return (
    <main className="min-h-screen px-4 py-8 sm:px-6 lg:px-8">
      <header className="mx-auto mb-8 max-w-6xl">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">AR Aging Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload an AR aging export, confirm the columns, and see who owes what — fully local,
          nothing leaves this machine.
        </p>
      </header>

      <div className="mx-auto max-w-6xl">
        {progress && (
          <div className="mx-auto mb-8 max-w-2xl">
            <ProgressBar progress={progress} />
          </div>
        )}

        {step === 'upload' && (
          <Upload
            onFileSelected={onFileSelected}
            loading={previewing}
            error={uploadError}
            onRetry={() => setUploadError(null)}
          />
        )}

        {step === 'mapping' && preview && (
          <MappingConfirm
            preview={preview}
            sheetName={sheetName}
            onSheetChange={onSheetChange}
            mapping={mapping}
            onMappingChange={onMappingChange}
            onConfirm={onConfirm}
            computing={computing || previewing}
            error={computeError}
            onStartOver={startOver}
          />
        )}

        {step === 'dashboard' && result && (
          <div className="space-y-8">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
              <div>
                <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                  {result.source_filename}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Sheet <span className="font-medium text-slate-700">{result.sheet_name}</span> · as
                  of <span className="font-medium text-slate-700">{result.as_of}</span> ·{' '}
                  <span data-testid="dashboard-rowcount" className="font-medium text-slate-700">
                    {intFmt(result.row_count)} rows
                  </span>
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <ExportBar file={file!} mapping={mapping} sheetName={sheetName} />
                <button
                  type="button"
                  onClick={startOver}
                  className="no-print rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                >
                  Start over
                </button>
              </div>
            </div>

            {autoMapped && !bannerDismissed && (
              <div
                data-testid="auto-mapped-banner"
                role="status"
                className="no-print flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800"
              >
                <span className="flex items-center gap-2">
                  <span aria-hidden="true">ℹ</span>
                  Columns auto-mapped from your standard format.
                </span>
                <span className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={onReviewMapping}
                    data-testid="review-mapping"
                    className="font-medium underline underline-offset-2 hover:text-blue-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                  >
                    Review / change mapping
                  </button>
                  <button
                    type="button"
                    onClick={onDismissBanner}
                    aria-label="Dismiss auto-mapped notice"
                    className="rounded p-1 leading-none text-blue-500 hover:bg-blue-100 hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </span>
              </div>
            )}

            <KpiTiles result={result} />

            <TopCustomersChart data={result.top_customers_by_overdue} />

            <EmployeeTable
              employees={result.employees ?? []}
              employeeBreakdown={result.employee_breakdown ?? []}
            />

            <AgingBreakdown
              bucketTotals={result.bucket_totals}
              customerBreakdown={result.customer_breakdown ?? []}
            />

            <FlagsPanel riskFlags={result.risk_flags ?? []} dataQuality={result.data_quality} />
          </div>
        )}
      </div>
    </main>
  )
}
