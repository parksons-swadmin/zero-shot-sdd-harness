export interface TopValue {
  value: string
  count: number
}

export interface ProfileColumn {
  name: string
  dtype: string
  null_count: number
  distinct_count: number
  min: number | null
  max: number | null
  mean: number | null
  median: number | null
  top_values: TopValue[] | null
}

export interface Profile {
  columns: ProfileColumn[]
}

export interface CleaningIssue {
  column: string
  issue_type: string
  action_taken: string
  affected_row_count: number
  needs_review: boolean
}

export interface CleaningReport {
  issues: CleaningIssue[]
}

export interface DatasetResponse {
  dataset_id: string
  filename: string
  row_count: number | null
  column_count: number | null
  status: string
  profile: Profile
  cleaning_report: CleaningReport
}

export interface SessionResponse {
  session_id: string
  dataset_ids: string[]
}

export interface KeyNumber {
  label: string
  value: string
}

// A single aggregated/binned point in a chart series (never a raw row).
export interface ChartPoint {
  x: string | number
  y: number
}

// A chart definition built locally from the capped result. See spec/api.md.
export interface ChartSpec {
  type: 'bar' | 'line' | 'pie'
  title: string
  x_label: string
  y_label: string
  series: ChartPoint[]
  truncated: boolean
}

// A ranked/summary table built locally from the capped result. See spec/api.md.
export interface TableData {
  title: string
  columns: string[]
  rows: Array<Array<string | number | null>>
  total_rows: number
  truncated: boolean
}

export interface QueryResult {
  id: string
  reasoning_mode: string
  summary_text: string
  key_numbers: KeyNumber[] | null
  table: TableData | null
  chart_spec: ChartSpec | null
  export_dataset_id: string | null
  generated_code: string
  follow_up_questions: string[] | null
  anomaly_flags: unknown[] | null
  step_count: number
  status: string
}

export interface MessageResponse {
  message_id: string
  query_result: QueryResult
}

export interface DatasetListItem {
  dataset_id: string
  filename: string
  row_count: number | null
  column_count: number | null
  status: string
  created_at: string
}

export interface DatasetListResponse {
  datasets: DatasetListItem[]
}

export interface MessageOut {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  query_result: QueryResult | null
}

export interface SessionHistoryResponse {
  session_id: string
  dataset_ids: string[]
  messages: MessageOut[]
}

export interface ApiEnvelope<T> {
  data: T | null
  error: { code?: string; message: string } | null
}
