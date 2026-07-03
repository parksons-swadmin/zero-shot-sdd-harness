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
  row_count: number
  column_count: number
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

export interface QueryResult {
  id: string
  reasoning_mode: string
  summary_text: string
  key_numbers: KeyNumber[] | null
  table: unknown
  chart_spec: unknown
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

export interface ApiEnvelope<T> {
  data: T | null
  error: { code?: string; message: string } | null
}
