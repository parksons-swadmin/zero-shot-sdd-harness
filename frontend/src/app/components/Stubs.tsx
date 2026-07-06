'use client'

// Clearly-labelled, non-functional previews of features arriving in Phase 3.
// These are honest placeholders — visibly tagged, visibly disabled, never mistakable
// for a bug or for a real (broken) feature. See spec/ui.md "LABELLED NON-FUNCTIONAL STUBS".
// (The Phase-2 stubs — employee summary, aging breakdown, risk/data-quality — are now
//  real features rendered above this section.)

function PhasePill({ phase }: { phase: 3 }) {
  return (
    <span className="inline-flex items-center rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
      Coming in Phase {phase}
    </span>
  )
}

function StubCard({
  phase,
  title,
  children,
}: {
  phase: 3
  title: string
  children: React.ReactNode
}) {
  return (
    <div
      aria-disabled="true"
      className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-slate-700">{title}</h4>
        <PhasePill phase={phase} />
      </div>
      <div className="text-sm text-slate-500">{children}</div>
    </div>
  )
}

export default function Stubs() {
  return (
    <section aria-labelledby="stubs-heading" className="space-y-4">
      <div>
        <h3 id="stubs-heading" className="text-lg font-semibold text-slate-900">
          More insights on the way
        </h3>
        <p className="text-sm text-slate-500">
          These sections are previews of what unlocks in Phase 3 — they are not active yet.
        </p>
      </div>

      <StubCard phase={3} title="Export & print">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled
            aria-disabled="true"
            className="cursor-not-allowed rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-400"
          >
            Export Excel
          </button>
          <button
            type="button"
            disabled
            aria-disabled="true"
            className="cursor-not-allowed rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-400"
          >
            Print / Save as PDF
          </button>
          <span className="text-xs text-slate-400">
            Download a multi-sheet workbook or a print-ready PDF of this dashboard.
          </span>
        </div>
      </StubCard>

      <StubCard phase={3} title="Large-file progress">
        <p className="mb-2">
          A live progress bar while very large exports (tens of thousands of rows) are computed.
        </p>
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
          role="presentation"
          aria-hidden="true"
        >
          <div className="h-full w-1/3 rounded-full bg-slate-300" />
        </div>
      </StubCard>
    </section>
  )
}
