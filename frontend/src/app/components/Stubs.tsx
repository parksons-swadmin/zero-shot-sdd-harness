'use client'

// Clearly-labelled, non-functional previews of features arriving in later phases.
// These are honest placeholders — visibly tagged, visibly disabled, never mistakable
// for a bug or for a real (broken) feature. See spec/ui.md "LABELLED NON-FUNCTIONAL STUBS".

function PhasePill({ phase }: { phase: 2 | 3 }) {
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
  phase: 2 | 3
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
          These sections are previews of what unlocks in the next phases — they are not active yet.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <StubCard phase={2} title="Employee-wise summary">
          A ranked table of each salesperson’s outstanding and overdue totals, so you know who to
          chase.
        </StubCard>

        <StubCard phase={2} title="Aging breakdown & avg. days overdue">
          Per-bucket totals (current / 0–30 / 31–60 / 61–90 / 90+) plus the weighted-average days
          overdue per customer and employee.
        </StubCard>

        <StubCard phase={2} title="Risk flags & data-quality audit">
          Proactive flags for the riskiest accounts, plus the full list of flagged and unparseable
          rows by row number.
        </StubCard>
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
