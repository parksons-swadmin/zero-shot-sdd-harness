'use client'

import type { StepEvent } from '@/lib/types'

// Replaces the Phase-1 "Step tracking — coming soon" static stub. During a
// streamed ask it renders the live "Step N of ~M: {label}" from incoming SSE
// `step` events — an honest step-wise/indeterminate indicator, never a fabricated
// percentage bar (per harness/patterns/ui-ux.md "never fake progress"). Keeps the
// last step visible after the run so the finished stage is legible; resets when a
// new ask begins (the parent clears `step`). The old `stub-step-progress` id is
// retired in favour of `data-testid="step-progress"`.
export default function StepProgress({
  step,
  active,
}: {
  step: StepEvent | null
  active: boolean
}) {
  // Idle: nothing has streamed yet. Show a neutral, honest placeholder — not a
  // fake progress bar and not "coming soon".
  if (!step) {
    return (
      <div
        className="rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-500 shadow-sm"
        data-testid="step-progress"
      >
        <p className="font-medium text-gray-700">Live progress</p>
        <p className="mt-1">Step-by-step progress appears here while a question runs.</p>
      </div>
    )
  }

  return (
    <div
      className={`rounded-lg border p-3 text-sm shadow-sm ${
        active ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-white'
      }`}
      data-testid="step-progress"
    >
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2 w-2 shrink-0 rounded-full ${
            active ? 'animate-pulse bg-blue-500' : 'bg-gray-400'
          }`}
          aria-hidden="true"
        />
        <span className="font-medium text-blue-900" data-testid="step-progress-label">
          Step {step.index} of ~{step.total_estimate}: {step.label}
        </span>
      </div>
    </div>
  )
}
