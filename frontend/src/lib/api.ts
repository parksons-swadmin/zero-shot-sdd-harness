import type {
  ApiEnvelope,
  AuditLogListResponse,
  AuditLogParams,
} from '@/lib/types'

// Fetch a page of the audit trail from GET /audit-log.
// Returns the parsed envelope's `data` on success, or throws on a transport /
// API error so callers can surface a single error state (mirrors the inline
// `{ data, error }` handling used elsewhere in the app).
export async function getAuditLog(
  params: AuditLogParams = {},
): Promise<AuditLogListResponse> {
  const search = new URLSearchParams()
  if (params.session_id) search.set('session_id', params.session_id)
  if (params.dataset_id) search.set('dataset_id', params.dataset_id)
  if (params.event_type) search.set('event_type', params.event_type)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))

  const qs = search.toString()
  const res = await fetch(`/audit-log${qs ? `?${qs}` : ''}`)
  const body: ApiEnvelope<AuditLogListResponse> = await res.json()

  if (!res.ok || body.error || !body.data) {
    throw new Error(body.error?.message ?? `Couldn't load the audit log (${res.status})`)
  }
  return body.data
}
