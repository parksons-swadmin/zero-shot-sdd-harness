// Same-origin fetch helpers for the AR API (spec/api.md).
// Success bodies are `{ data, error: null }`; non-2xx bodies are `{ detail: { code, message } }`.
// These helpers unwrap `data` on success and throw a human Error otherwise.

import type {
  ComputeProgress,
  DashboardResult,
  InvoiceListData,
  Mapping,
  PreviewData,
} from './types'

const NETWORK_ERROR = 'Could not reach the server. Is it running at http://localhost:8001 ?'

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    const msg = body?.detail?.message
    if (typeof msg === 'string' && msg.trim()) return msg
  } catch {
    /* non-JSON body — fall through */
  }
  return `${fallback} (HTTP ${res.status})`
}

/**
 * Build the multipart body shared by /api/compute, /api/compute/stream, and
 * /api/export/xlsx. The six canonical fields are always sent; `hod` is optional
 * and included only when the user actually picked a column (a blank hod would
 * otherwise be sent as an empty string). Keeps the payload identical across the
 * three routes so the export/stream cannot diverge from the plain compute.
 */
function computeFormData(file: File, mapping: Mapping, sheetName?: string): FormData {
  const fd = new FormData()
  fd.append('file', file)
  if (sheetName) fd.append('sheet_name', sheetName)

  const { hod, ...required } = mapping
  const payload: Record<string, string> = { ...required }
  if (hod) payload.hod = hod
  fd.append('mapping', JSON.stringify(payload))
  return fd
}

/** POST /api/preview — parse headers, propose the six-field mapping. */
export async function postPreview(file: File, sheetName?: string): Promise<PreviewData> {
  const fd = new FormData()
  fd.append('file', file)
  if (sheetName) fd.append('sheet_name', sheetName)

  let res: Response
  try {
    res = await fetch('/api/preview', { method: 'POST', body: fd })
  } catch {
    throw new Error(NETWORK_ERROR)
  }
  if (!res.ok) throw new Error(await readError(res, 'Could not read the workbook'))
  const body = await res.json()
  return body.data as PreviewData
}

/** POST /api/compute — apply the confirmed mapping and compute the dashboard. */
export async function postCompute(
  file: File,
  mapping: Mapping,
  sheetName?: string,
): Promise<DashboardResult> {
  const fd = computeFormData(file, mapping, sheetName)

  let res: Response
  try {
    res = await fetch('/api/compute', { method: 'POST', body: fd })
  } catch {
    throw new Error(NETWORK_ERROR)
  }
  if (!res.ok) throw new Error(await readError(res, 'Could not compute the metrics'))
  const body = await res.json()
  return body.data as DashboardResult
}

/**
 * POST /api/invoices — invoice-level drill-down behind the dashboard, optionally
 * filtered by an exact `customer` and/or `employee` (ANDed). Re-posts the file +
 * confirmed mapping as the SAME multipart body as /api/compute (incl. the optional
 * `hod`), plus the filter fields when set. Blank filter values are simply omitted.
 *
 * A filtered list returns ALL matching rows (`truncated=false`); an unfiltered list
 * is capped server-side (`truncated=true`) while `total_count` / `subtotal_amount`
 * still cover the full set. Unwraps `data` on success; throws a human Error otherwise.
 */
export async function postInvoices(
  file: File,
  mapping: Mapping,
  sheetName: string | undefined,
  filters: { customer?: string; employee?: string } = {},
): Promise<InvoiceListData> {
  const fd = computeFormData(file, mapping, sheetName)
  const customer = filters.customer?.trim()
  const employee = filters.employee?.trim()
  if (customer) fd.append('customer', customer)
  if (employee) fd.append('employee', employee)

  let res: Response
  try {
    res = await fetch('/api/invoices', { method: 'POST', body: fd })
  } catch {
    throw new Error(NETWORK_ERROR)
  }
  if (!res.ok) throw new Error(await readError(res, 'Could not load the invoice list'))
  const body = await res.json()
  return body.data as InvoiceListData
}

// --------------------------------------------------------------------------- //
// Phase 3 — Excel export + streamed compute progress
// --------------------------------------------------------------------------- //

/** Extract a filename from a Content-Disposition header, else use `fallback`. */
function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  // RFC 5987 `filename*=UTF-8''<pct-encoded>` takes precedence over plain filename.
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^["']|["']$/g, ''))
    } catch {
      /* fall through to plain */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  if (plain?.[1]) return plain[1].trim()
  return fallback
}

/** `ar_export.xlsx` -> `ar_export_AR_aging.xlsx` (used when the server sends no filename). */
function defaultXlsxName(file: File): string {
  const base = file.name.replace(/\.xlsx$/i, '').trim() || 'export'
  return `${base}_AR_aging.xlsx`
}

/**
 * POST /api/export/xlsx — re-posts the file + confirmed mapping (stateless), receives
 * the multi-sheet workbook as a Blob, and triggers a browser download. Uses the
 * server's Content-Disposition filename when present, else a sensible default.
 * Throws a human Error on any failure so the caller can surface it.
 */
export async function postExportXlsx(
  file: File,
  mapping: Mapping,
  sheetName?: string,
): Promise<void> {
  const fd = computeFormData(file, mapping, sheetName)

  let res: Response
  try {
    res = await fetch('/api/export/xlsx', { method: 'POST', body: fd })
  } catch {
    throw new Error(NETWORK_ERROR)
  }
  if (!res.ok) throw new Error(await readError(res, 'Could not export the workbook'))

  const blob = await res.blob()
  const name = filenameFromDisposition(res.headers.get('content-disposition'), defaultXlsxName(file))

  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    // Revoke on the next tick so the download has time to start.
    setTimeout(() => URL.revokeObjectURL(url), 1_000)
  }
}

/** Shape of a single parsed SSE `data:` payload from /api/compute/stream. */
interface StreamFrame {
  event?: string
  result?: DashboardResult
  code?: string
  message?: string
  phase?: string
  rows_done?: number
  rows_total?: number
}

/**
 * POST /api/compute/stream — streams `{phase, rows_done, rows_total}` progress frames
 * then a final `{event:"result", result:{...}}`. EventSource cannot be used (it is
 * GET-only and cannot carry the uploaded file), so we POST the multipart body and read
 * the response body reader, parsing SSE `data:` lines by hand.
 *
 * Resolves to the final DashboardResult. THROWS on any failure (non-ok status, network,
 * an `{event:"error"}` frame, a missing/absent final result, or no streaming support) so
 * the caller can fall back to the non-streaming `postCompute`.
 */
export async function computeStream(
  file: File,
  mapping: Mapping,
  sheetName: string | undefined,
  onProgress?: (p: ComputeProgress) => void,
): Promise<DashboardResult> {
  const fd = computeFormData(file, mapping, sheetName)

  const res = await fetch('/api/compute/stream', { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await readError(res, 'Could not compute the metrics'))
  if (!res.body) throw new Error('Streaming is not supported in this browser.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: DashboardResult | null = null

  // Parse one complete SSE frame (already CR-stripped). A frame may hold multiple
  // lines; we join the `data:` lines and JSON-parse them.
  const handleFrame = (frame: string): void => {
    const json = frame
      .split('\n')
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trim())
      .join('\n')
    if (!json) return

    let payload: StreamFrame
    try {
      payload = JSON.parse(json) as StreamFrame
    } catch {
      return // ignore keep-alive / comment frames
    }

    if (payload.event === 'result' && payload.result) {
      result = payload.result
    } else if (payload.event === 'error') {
      throw new Error(payload.message?.trim() || 'The server failed while computing.')
    } else if (typeof payload.rows_total === 'number') {
      onProgress?.({
        phase: typeof payload.phase === 'string' ? payload.phase : 'processing',
        rows_done: Number(payload.rows_done) || 0,
        rows_total: Number(payload.rows_total) || 0,
      })
    }
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (value) buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')

      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        handleFrame(frame)
      }
      if (done) break
    }
    // Flush any trailing frame that arrived without a terminating blank line.
    buffer += decoder.decode().replace(/\r/g, '')
    if (buffer.trim()) handleFrame(buffer)
  } catch (e) {
    try {
      await reader.cancel()
    } catch {
      /* best-effort */
    }
    throw e
  }

  if (!result) throw new Error('The stream ended without a result.')
  return result
}
