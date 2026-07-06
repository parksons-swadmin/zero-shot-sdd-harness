// Same-origin fetch helpers for the AR API (spec/api.md).
// Success bodies are `{ data, error: null }`; non-2xx bodies are `{ detail: { code, message } }`.
// These helpers unwrap `data` on success and throw a human Error otherwise.

import type { DashboardResult, Mapping, PreviewData } from './types'

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
  const fd = new FormData()
  fd.append('file', file)
  if (sheetName) fd.append('sheet_name', sheetName)

  // The six canonical fields are always sent. `hod` is optional: include it only
  // when the user actually picked a column (a blank hod would otherwise be sent as
  // an empty string). This keeps the payload clean and the field non-gating.
  const { hod, ...required } = mapping
  const payload: Record<string, string> = { ...required }
  if (hod) payload.hod = hod
  fd.append('mapping', JSON.stringify(payload))

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
