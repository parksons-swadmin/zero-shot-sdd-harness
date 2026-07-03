import type { CleaningIssue } from '@/lib/types'

export default function CleaningReportList({ issues }: { issues: CleaningIssue[] }) {
  if (issues.length === 0) {
    return (
      <p className="text-sm text-gray-500" data-testid="cleaning-report-empty">
        No cleaning was needed — this file was already tidy.
      </p>
    )
  }

  return (
    <ul className="space-y-2" data-testid="cleaning-report-list">
      {issues.map((issue, idx) => (
        <li
          key={`${issue.column}-${issue.issue_type}-${idx}`}
          className="flex items-start justify-between gap-3 rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-sm"
          data-testid="cleaning-report-item"
        >
          <div>
            <span className="font-medium text-gray-900">{issue.column}</span>
            <span className="text-gray-500"> — {issue.issue_type.replace(/_/g, ' ')}</span>
            <p className="text-gray-600">
              {issue.action_taken} ({issue.affected_row_count} row
              {issue.affected_row_count === 1 ? '' : 's'} affected)
            </p>
          </div>
          {issue.needs_review && (
            <span
              className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800"
              data-testid="needs-review-badge"
            >
              Needs review
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
