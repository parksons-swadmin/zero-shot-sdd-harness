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

export interface FieldMatch {
  field: CanonicalField
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

export interface DataQuality {
  flagged_row_count: number
  unparseable_row_count: number
  by_reason: Record<string, number>
}

/** Response `data` from POST /api/compute (Phase-1 fields). */
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
}

/** The mapping payload sent to /api/compute (canonical field -> source column). */
export type Mapping = Record<CanonicalField, string>
