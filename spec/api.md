# API

---

## API Style

REST (FastAPI), JSON responses wrapped in the existing `ok(data)` / `api_error(code, message, status)` envelope from `src/api/_common.py`. File upload uses `multipart/form-data`.

## Endpoints / Commands

### `POST /datasets` *(Phase 1)*

**Purpose:** Upload a CSV, auto-clean and auto-profile it.

**Request:** `multipart/form-data`, field `file` (CSV, max `AGENT_MAX_UPLOAD_BYTES`, default 100MB).

**Response:**
```json
{
  "data": {
    "dataset_id": "uuid",
    "filename": "leads_export.csv",
    "row_count": 12500,
    "column_count": 14,
    "status": "ready",
    "profile": {
      "columns": [
        {"name": "revenue", "dtype": "float64", "null_count": 3, "distinct_count": 8210,
         "min": 0.0, "max": 98234.5, "mean": 4210.2, "median": 1890.0, "top_values": null},
        {"name": "region", "dtype": "object", "null_count": 0, "distinct_count": 5,
         "min": null, "max": null, "mean": null, "median": null,
         "top_values": [{"value": "West", "count": 4021}]}
      ]
    },
    "cleaning_report": {
      "issues": [
        {"column": "signup_date", "issue_type": "inconsistent_format", "action_taken": "parsed to ISO-8601", "affected_row_count": 340, "needs_review": false},
        {"column": "phone", "issue_type": "ambiguous_country_code", "action_taken": "left as-is", "affected_row_count": 12, "needs_review": true}
      ]
    }
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Not a parseable CSV/spreadsheet |
| 413 | File exceeds `AGENT_MAX_UPLOAD_BYTES` |
| 500 | Cleaning/profiling failure (disk I/O, malformed beyond recovery) |

### `GET /datasets` *(Phase 2)*

**Purpose:** List the library of every uploaded/derived dataset.

**Response:** `{"data": {"datasets": [{dataset_id, filename, row_count, status, created_at}, ...]}, "error": null}`

### `GET /datasets/{dataset_id}` *(Phase 1, detail view)*

**Purpose:** Fetch a single dataset's profile + cleaning report (same shape as the `POST /datasets` response body's `data`).

**Error cases:** `404` if `dataset_id` doesn't exist.

### `POST /sessions` *(Phase 1, called internally on first upload; exposed for Phase 2 multi-session UI)*

**Purpose:** Create a session scoped to one or more datasets.

**Request:** `{"dataset_ids": ["uuid", ...]}`

**Response:** `{"data": {"session_id": "uuid", "dataset_ids": [...]}, "error": null}`

### `POST /sessions/{session_id}/messages` *(Phase 1 — the "ask" endpoint)*

**Purpose:** Ask a natural-language question against the session's dataset(s); runs the graph in `spec/agent.md`.

**Request:** `{"question": "What is the total revenue for the West region?"}`

**Response:**
```json
{
  "data": {
    "message_id": "uuid",
    "query_result": {
      "id": "uuid",
      "reasoning_mode": "simple",
      "summary_text": "The total revenue for the West region is **$4,201,932.10** across 4,021 rows.",
      "key_numbers": [{"label": "Total revenue (West)", "value": "4201932.10"}],
      "table": null,
      "chart_spec": null,
      "export_dataset_id": null,
      "generated_code": "result = df[df['region'] == 'West']['revenue'].sum()",
      "follow_up_questions": [],
      "anomaly_flags": [],
      "step_count": 1,
      "status": "completed"
    }
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Unknown `session_id` |
| 409 | A run is already in flight for this session (see `spec/architecture.md` → Concurrency) |
| 422 | Empty/whitespace-only question |
| 500 | Rendered as a human-readable error in `query_result.status = "failed"` with a `summary_text` explaining the failure — never a raw stack trace (per `harness/patterns/code.md`) |

### `GET /sessions/{session_id}/messages/{message_id}/stream` *(Phase 3)*

**Purpose:** Server-Sent-Events stream of `step` and `answer_chunk` events for the in-flight/just-completed run, for live progress + streamed answer text.

### `GET /sessions/{session_id}` *(Phase 2)*

**Purpose:** Fetch a session's full message + `QueryResult` history for the persisted chat-thread UI.

### `GET /query-results/{query_result_id}/export` *(Phase 3)*

**Purpose:** Download the cleaned/derived export file for a `QueryResult` that produced one.

**Error cases:** `404` if the result has no export.

### `GET /audit-log` *(Phase 3)*

**Purpose:** List audit-trail entries (paginated, filterable by `session_id`/`dataset_id`) for the history UI. The underlying `AuditLogEntry` table is written from Phase 1; this endpoint is added in Phase 3.

### `GET /cost-summary` *(Phase 3)*

**Purpose:** Per-session and running-total token/cost figures aggregated from `CostRecord`. The underlying `CostRecord` table is written from Phase 1; this endpoint is added in Phase 3.

## Authentication

None — single local user, no network exposure beyond `localhost:8001`. Out of scope per `spec/roadmap.md`.
