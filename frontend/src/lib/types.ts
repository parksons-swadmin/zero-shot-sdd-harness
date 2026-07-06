// TypeScript mirrors of the pinned API contract (spec/api.md).
// The frontend consumes these shapes exactly; it never reshapes the contract.

/** The six canonical AR fields, in canonical display order. */
export const CANONICAL_FIELDS = [
  'customer',
  'invoice_no',
  'invoice_date',
  'due_date',
  'amount',
  'employee',
] as const

export type CanonicalField = (typeof CANONICAL_FIELDS)[number]

export const FIELD_LABELS: Record<CanonicalField, string> = {
  customer: 'Customer',
  invoice_no: 'Invoice number',
  invoice_date: 'Invoice date',
  due_date: 'Due date',
  amount: 'Amount (outstanding)',
  employee: 'Employee',
}

export type MatchStatus = 'high' | 'low' | 'unmatched'

/**
 * A proposed mapping entry. `field` is normally one of the six canonical fields,
 * but the backend MAY also return an entry for the OPTIONAL `hod` (Head of
 * Department) column — it is never one of the required six and never gates Confirm.
 */
export interface FieldMatch {
  field: CanonicalField | 'hod'
  matched_column: string | null
  confidence: number
  status: MatchStatus
}

export interface ParseFlag {
  row_index: number
  field: string
  reason: string
  raw_value: string
}

/** Response `data` from POST /api/preview. */
export interface PreviewData {
  sheets: string[]
  sheet_name: string
  columns: string[]
  proposed_mapping: FieldMatch[]
  preview_rows: Record<string, unknown>[]
  parse_flags: ParseFlag[]
  /**
   * Additive signal (Wave 1 backend): true when all six required fields resolved
   * to distinct high-confidence columns via the built-in default mapping profile —
   * i.e. a recognized standard export. When true the client MAY skip the
   * mapping-confirm screen and compute straight away; when false, behave exactly
   * as before (show the confirm screen).
   */
  auto_mapped: boolean
}

export type Bucket = '0-30' | '31-60' | '61-90' | '90+' | 'none'

export interface BucketTotals {
  current: number
  b_0_30: number
  b_31_60: number
  b_61_90: number
  b_90_plus: number
}

export interface TopCustomer {
  customer: string
  overdue_amount: number
  outstanding_amount: number
}

/** A single flagged/unparseable row in the data-quality audit list (Phase 2). */
/** Same wire shape as ParseFlag — reused verbatim per spec/data.md. */
export type QualityFlag = ParseFlag

export interface DataQuality {
  flagged_row_count: number
  unparseable_row_count: number
  /** Counts per reason. MAY include the key "summary_row_excluded" (present only when > 0). */
  by_reason: Record<string, number>
  /** Full audit list of flagged/unparseable rows (Phase 2; omitted in Phase 1). */
  rows?: QualityFlag[]
}

/** Per-employee summary (Phase 2). Ranked desc by total_outstanding by the backend. */
export interface EmployeeSummary {
  employee: string
  total_outstanding: number
  total_overdue: number
  pct_overdue: number
  worst_bucket: Bucket
  invoice_count: number
  /** Head of Department for the employee — present only when `hod` was mapped; null/absent otherwise. */
  hod?: string | null
}

/** Per-group (customer or employee) aging breakdown + weighted-avg days overdue (Phase 2). */
export interface GroupBreakdown {
  key: string
  bucket_totals: BucketTotals
  /** Amount-weighted mean days-past-due over the group's overdue invoices; null when no overdue. */
  weighted_avg_days_overdue: number | null
  pct_overdue: number
  total_outstanding: number
}

/** A proactive risk flag on an account (Phase 2). */
export interface RiskFlag {
  customer: string
  reason: string
  amount: number
  bucket: string
}

/** Response `data` from POST /api/compute (Phase-1 fields + Phase-2 extensions). */
export interface DashboardResult {
  source_filename: string
  sheet_name: string
  as_of: string
  row_count: number
  total_outstanding: number
  total_overdue: number
  pct_overdue: number
  customer_count: number
  worst_bucket: Bucket
  bucket_totals: BucketTotals
  top_customers_by_overdue: TopCustomer[]
  data_quality: DataQuality
  // Phase-2 fields — omitted or null in Phase-1 responses.
  employees?: EmployeeSummary[]
  customer_breakdown?: GroupBreakdown[]
  employee_breakdown?: GroupBreakdown[]
  risk_flags?: RiskFlag[]
}

/**
 * Live progress emitted by POST /api/compute/stream while a (large) file is parsed
 * and aggregated. `rows_total` is the true row count; `rows_done` climbs toward it.
 */
export interface ComputeProgress {
  phase: string
  rows_done: number
  rows_total: number
}

/**
 * The mapping payload sent to /api/compute (canonical field -> source column).
 * The six canonical fields are always required strings; `hod` is an OPTIONAL
 * seventh field (Head of Department) that never gates Confirm & Compute and is
 * sent only when the user picks a column.
 */
export type Mapping = Record<CanonicalField, string> & { hod?: string | null }
