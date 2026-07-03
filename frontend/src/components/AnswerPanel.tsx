import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { QueryResult } from '@/lib/types'
import CodePanel from './CodePanel'

export default function AnswerPanel({ result }: { result: QueryResult }) {
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm" data-testid="answer-panel">
      <div className="prose prose-sm max-w-none text-gray-800" data-testid="answer-summary">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.summary_text}</ReactMarkdown>
      </div>

      {result.key_numbers && result.key_numbers.length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="key-numbers">
          {result.key_numbers.map((kn, idx) => (
            <div
              key={`${kn.label}-${idx}`}
              className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm"
            >
              <span className="text-blue-700">{kn.label}: </span>
              <span className="font-semibold text-blue-900">{kn.value}</span>
            </div>
          ))}
        </div>
      )}

      <CodePanel code={result.generated_code} />
    </div>
  )
}
