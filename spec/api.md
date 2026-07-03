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

**Purpose:** List the library of every uploaded/derived dataset — a flat list, newest first, no tags/search (see `spec/roadmap.md` Phase 2 design decisions). Backs the frontend's "Library" sidebar checkbox list.

**Response:**
```json
{
  "data": {
    "datasets": [
      {"dataset_id": "uuid-1", "filename": "month1.csv", "row_count": 12500, "column_count": 14, "status": "ready", "created_at": "2026-07-01T10:00:00Z"},
      {"dataset_id": "uuid-2", "filename": "month2.csv", "row_count": 11800, "column_count": 14, "status": "ready", "created_at": "2026-07-02T09:00:00Z"}
    ]
  },
  "error": null
}
```

**Error cases:** none — an empty library returns `{"datasets": []}`.

### `GET /datasets/{dataset_id}` *(Phase 1, detail view)*

**Purpose:** Fetch a single dataset's profile + cleaning report (same shape as the `POST /datasets` response body's `data`).

**Error cases:** `404` if `dataset_id` doesn't exist.

### `POST /sessions` *(Phase 1, called internally on first upload; Phase 2 — the "start a library session" endpoint, unchanged shape)*

**Purpose:** Create a session scoped to one or more datasets. **Phase 2 usage:** the `frontend-library` slice calls this with every checked `dataset_id` from the library sidebar (not just one) — this is how cross-file sessions are created. Per `spec/roadmap.md` Phase 2 design decision #2, selecting a new file set always creates a **new** session over the union of selected IDs; there is no endpoint to mutate an existing session's `SessionDataset` scope. (The frontend may choose to reuse a session client-side if it already has one open for the exact same dataset-ID set, but the server itself performs no dedup — each call creates a fresh session.)

**Request:** `{"dataset_ids": ["uuid", ...]}`

**Response:** `{"data": {"session_id": "uuid", "dataset_ids": [...]}, "error": null}`

**Error cases:** unchanged from Phase 1 — `422` if `dataset_ids` is empty, `404` if any `dataset_id` doesn't exist.

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
      "follow_up_questions": ["What is the total revenue for the East region?", "How does West compare to last month?"],
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

**Purpose:** Fetch a session's dataset scope plus its full `Message` + `QueryResult` history, ordered oldest-first, for the persisted chat-thread UI (`ChatThread.tsx`). Called on page load/resume so a session survives a browser reload or a gap of days, per the roadmap's "conversations persist across days" requirement.

**Response:**
```json
{
  "data": {
    "session_id": "uuid",
    "dataset_ids": ["uuid-1", "uuid-2"],
    "messages": [
      {
        "id": "uuid-msg-1", "role": "user", "content": "What is the combined total revenue across both months?",
        "created_at": "2026-07-02T10:00:00Z", "query_result": null
      },
      {
        "id": "uuid-msg-2", "role": "assistant", "content": "The combined total revenue is **$812,340.55**.",
        "created_at": "2026-07-02T10:00:03Z",
        "query_result": {
          "id": "uuid-qr-1", "reasoning_mode": "simple",
          "summary_text": "The combined total revenue is **$812,340.55**.",
          "key_numbers": [{"label": "value_1", "value": "$812,340.55"}],
          "table": null, "chart_spec": null, "export_dataset_id": null,
          "generated_code": "result = df['revenue'].sum() + df2['revenue'].sum()",
          "follow_up_questions": ["What was the split by month?", "Which region drove the growth?"],
          "anomaly_flags": [], "step_count": 1, "status": "completed"
        }
      }
    ]
  },
  "error": null
}
```
Only `assistant` messages carry a non-null `query_result` (mirrors the `Message` 1—0/1 `QueryResult` relationship in `spec/data.md`).

**Error cases:** `404` if `session_id` doesn't exist.

### `GET /query-results/{query_result_id}/export` *(Phase 3)*

**Purpose:** Download the cleaned/derived export file for a `QueryResult` that produced one.

**Error cases:** `404` if the result has no export.

### `GET /audit-log` *(Phase 3)*

**Purpose:** List audit-trail entries (paginated, filterable by `session_id`/`dataset_id`) for the history UI. The underlying `AuditLogEntry` table is written from Phase 1; this endpoint is added in Phase 3.

### `GET /cost-summary` *(Phase 3)*

**Purpose:** Per-session and running-total token/cost figures aggregated from `CostRecord`. The underlying `CostRecord` table is written from Phase 1; this endpoint is added in Phase 3.

## Authentication

None — single local user, no network exposure beyond `localhost:8001`. Out of scope per `spec/roadmap.md`.
