'use client'

import { useEffect, useState } from 'react'
import type { ApiEnvelope, CostSummaryResponse, QueryCost } from '@/lib/types'

// Formats a USD figure. Cost estimates are tiny (fractions of a cent), so we keep
// four decimals — enough to show the running total tick up between questions.
function fmtUsd(value: number): string {
  return `$${(value ?? 0).toFixed(4)}`
}

function fmtTokens(totals: { prompt_tokens: number; completion_tokens: number } | null): string {
  if (!totals) return '0'
  return (totals.prompt_tokens + totals.completion_tokens).toLocaleString()
}

// Replaces the Phase-1 "Cost tracking — coming soon" static badge. Fetches the
// all-time running total from GET /cost-summary on mount and whenever `refreshKey`
// bumps (after each answer), and shows the latest answer's per-query cost inline.
export default function CostBadge({
  refreshKey,
  sessionId,
  latestCost,
}: {
  refreshKey: number
  sessionId: string | null
  latestCost: QueryCost | null
}) {
  const [summary, setSummary] = useState<CostSummaryResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const url = sessionId
          ? `/cost-summary?session_id=${encodeURIComponent(sessionId)}`
          : '/cost-summary'
        const res = await fetch(url)
        const body: ApiEnvelope<CostSummaryResponse> = await res.json()
        if (!cancelled && res.ok && !body.error && body.data) {
          setSummary(body.data)
        }
      } catch {
        /* leave the last-known figure; the badge is informational, not blocking */
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [refreshKey, sessionId])

  const allTime = summary?.all_time ?? null

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200"
      data-testid="cost-badge"
      title="Total LLM cost across all questions (session totals via GET /cost-summary)"
    >
      <span className="text-emerald-500" aria-hidden="true">
        ◆
      </span>
      <span data-testid="cost-total">{fmtUsd(allTime?.estimated_cost_usd ?? 0)}</span>
      <span className="text-emerald-600">· {fmtTokens(allTime)} tokens</span>
      {latestCost && (
        <span className="text-emerald-600" data-testid="cost-latest">
          (this: {fmtUsd(latestCost.estimated_cost_usd)})
        </span>
      )}
    </span>
  )
}
