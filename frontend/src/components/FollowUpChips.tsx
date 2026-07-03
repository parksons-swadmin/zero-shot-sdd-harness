'use client'

export default function FollowUpChips({
  questions,
  onPick,
}: {
  questions: string[]
  onPick: (question: string) => void
}) {
  if (!questions || questions.length === 0) return null

  return (
    <div className="mt-4" data-testid="follow-ups">
      <h3 className="mb-2 text-sm font-semibold text-gray-900">Suggested follow-ups</h3>
      <div className="flex flex-wrap gap-2">
        {questions.map((q, idx) => (
          <button
            key={`${idx}-${q}`}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
            data-testid="follow-up-chip"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
