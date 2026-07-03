'use client'

import type { AnomalyFlag } from '@/lib/types'

// Severity-driven styling. `critical` -> red, `warning` -> amber, `info` -> slate.
const SEVERITY_STYLES: Record<AnomalyFlag['severity'], { box: string; dot: string; label: string }> = {
  critical: {
    box: 'border-red-200 bg-red-50 text-red-800',
    dot: 'bg-red-500',
    label: 'text-red-700',
  },
  warning: {
    box: 'border-amber-200 bg-amber-50 text-amber-800',
    dot: 'bg-amber-500',
    label: 'text-amber-700',
  },
  info: {
    box: 'border-slate-200 bg-slate-50 text-slate-700',
    dot: 'bg-slate-400',
    label: 'text-slate-600',
  },
}

function styleFor(severity: string) {
  return SEVERITY_STYLES[severity as AnomalyFlag['severity']] ?? SEVERITY_STYLES.info
}

export default function AnomalyBanner({ flags }: { flags: AnomalyFlag[] | null | undefined }) {
  // A clean answer has no banner — never a "no anomalies" placeholder.
  if (!flags || flags.length === 0) return null

  return (
    <div className="space-y-2" data-testid="anomaly-banner">
      <h3 className="text-sm font-semibold text-gray-900">Data-quality notes</h3>
      <ul className="space-y-2">
        {flags.map((flag, idx) => {
          const s = styleFor(flag.severity)
          return (
            <li
              key={`${flag.type}-${flag.column ?? 'table'}-${idx}`}
              className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${s.box}`}
              data-testid="anomaly-flag"
              data-severity={flag.severity}
            >
              <span className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${s.dot}`} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                {flag.column && (
                  <span className={`mr-1 font-semibold ${s.label}`} data-testid="anomaly-column">
                    {flag.column}:
                  </span>
                )}
                <span data-testid="anomaly-message">{flag.message}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
