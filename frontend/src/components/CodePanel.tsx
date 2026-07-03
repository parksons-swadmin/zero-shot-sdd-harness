'use client'

import { useState } from 'react'

export default function CodePanel({ code }: { code: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium text-gray-800 hover:bg-gray-50"
        data-testid="view-code-toggle"
      >
        <span>View code</span>
        <span className="text-gray-400">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <pre
          className="overflow-x-auto rounded-b-lg bg-gray-900 p-4 text-xs text-gray-100"
          data-testid="generated-code"
        >
          <code>{code}</code>
        </pre>
      )}
    </div>
  )
}
