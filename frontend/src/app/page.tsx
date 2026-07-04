'use client'

import { useCallback, useState } from 'react'
import Upload from './components/Upload'
import MappingConfirm from './components/MappingConfirm'
import KpiTiles from './components/KpiTiles'
import TopCustomersChart from './components/TopCustomersChart'
import Stubs from './components/Stubs'
import { postCompute, postPreview } from '@/lib/api'
import { intFmt } from '@/lib/format'
import {
  CANONICAL_FIELDS,
  type CanonicalField,
  type DashboardResult,
  type Mapping,
  type PreviewData,
} from '@/lib/types'

type Step = 'upload' | 'mapping' | 'dashboard'

function buildMapping(preview: PreviewData): Mapping {
  const byField = new Map(preview.proposed_mapping.map((fm) => [fm.field, fm.matched_column]))
  const m = {} as Mapping
  for (const f of CANONICAL_FIELDS) m[f] = byField.get(f) ?? ''
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
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [computeError, setComputeError] = useState<string | null>(null)

  const runPreview = useCallback(async (f: File, sheet?: string) => {
    setPreviewing(true)
    setUploadError(null)
    setComputeError(null)
    try {
      const data = await postPreview(f, sheet)
      setPreview(data)
      setSheetName(data.sheet_name)
      setMapping(buildMapping(data))
      setStep('mapping')
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Could not read the workbook.')
      setStep('upload')
    } finally {
      setPreviewing(false)
    }
  }, [])

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

  const onMappingChange = useCallback((field: CanonicalField, column: string) => {
    setMapping((prev) => ({ ...prev, [field]: column }))
  }, [])

  const onConfirm = useCallback(async () => {
    if (!file) return
    setComputing(true)
    setComputeError(null)
    try {
      const data = await postCompute(file, mapping, sheetName)
      setResult(data)
      setStep('dashboard')
    } catch (e) {
      setComputeError(e instanceof Error ? e.message : 'Could not compute the metrics.')
    } finally {
      setComputing(false)
    }
  }, [file, mapping, sheetName])

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
                  {intFmt(result.row_count)} rows
                </p>
              </div>
              <button
                type="button"
                onClick={startOver}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
              >
                Start over
              </button>
            </div>

            <KpiTiles result={result} />

            <TopCustomersChart data={result.top_customers_by_overdue} />

            <Stubs />
          </div>
        )}
      </div>
    </main>
  )
}
