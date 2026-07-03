'use client'

export default function ExportButton({
  queryResultId,
  exportDatasetId,
}: {
  queryResultId: string | null | undefined
  exportDatasetId: string | null | undefined
}) {
  const enabled = Boolean(exportDatasetId) && Boolean(queryResultId)

  function handleDownload() {
    if (!enabled || !queryResultId) return
    // Explicit user download over localhost — navigating to the endpoint lets the
    // browser handle the Content-Disposition: attachment response as a file save.
    const url = `/query-results/${queryResultId}/export`
    const link = document.createElement('a')
    link.href = url
    link.download = ''
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-testid="export-panel"
    >
      <h3 className="mb-2 text-sm font-semibold text-gray-900">Export</h3>
      <button
        type="button"
        onClick={handleDownload}
        disabled={!enabled}
        title={enabled ? 'Download the full derived dataset as CSV' : 'No export for this answer'}
        className={`w-full rounded-lg px-4 py-2 text-sm font-medium ${
          enabled
            ? 'bg-blue-600 text-white hover:bg-blue-700'
            : 'cursor-not-allowed bg-gray-300 text-gray-500'
        }`}
        data-testid="export-button"
      >
        Export CSV
      </button>
      {!enabled && (
        <p className="mt-1 text-xs text-gray-400" data-testid="export-caption">
          No export for this answer
        </p>
      )}
    </div>
  )
}
