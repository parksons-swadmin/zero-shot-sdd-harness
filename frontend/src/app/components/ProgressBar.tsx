'use client'

// Real progress bar driven by streamed {phase, rows_done, rows_total} frames from
// POST /api/compute/stream (Phase 3). It reflects REAL work — rows parsed/aggregated —
// never a fake timer (honesty rule, harness/patterns/ui-ux.md). For small/instant files
// it may complete immediately; before a row total is known it shows an indeterminate bar.

import { intFmt } from '@/lib/format'
import type { ComputeProgress } from '@/lib/types'

const PHASE_LABELS: Record<string, string> = {
  starting: 'Starting…',
  parse: 'Reading rows…',
  parsing: 'Reading rows…',
  ingest: 'Reading rows…',
  compute: 'Computing metrics…',
  computing: 'Computing metrics…',
  aggregate: 'Aggregating…',
  aggregating: 'Aggregating…',
  flag: 'Checking data quality…',
  finalize: 'Finalizing…',
  finalizing: 'Finalizing…',
}

function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? 'Computing metrics…'
}

export default function ProgressBar({ progress }: { progress: ComputeProgress }) {
  const { phase, rows_done, rows_total } = progress
  const hasTotal = rows_total > 0
  const rawPct = hasTotal ? (rows_done / rows_total) * 100 : 0
  const clamped = Math.max(0, Math.min(100, rawPct))

  return (
    <section
      data-testid="progress-bar"
      aria-label="Compute progress"
      className="no-print rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-700">{phaseLabel(phase)}</p>
        <p className="text-sm tabular-nums text-slate-600" data-testid="progress-total">
          {hasTotal ? `${intFmt(rows_done)} / ${intFmt(rows_total)} rows` : 'Preparing…'}
        </p>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={hasTotal ? rows_total : undefined}
        aria-valuenow={hasTotal ? rows_done : undefined}
        aria-label="Rows processed"
        className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200"
      >
        <div
          className={[
            'h-full rounded-full bg-blue-600 transition-[width] duration-200 ease-out',
            hasTotal ? '' : 'w-1/3 animate-pulse',
          ].join(' ')}
          style={hasTotal ? { width: `${clamped}%` } : undefined}
        />
      </div>

      <p className="mt-2 text-xs text-slate-500">
        Streaming real progress — nothing leaves this machine.
      </p>
    </section>
  )
}
