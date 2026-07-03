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

### `GET /query-results/{query_result_id}/export` *(Phase 3a)*

**Purpose:** Download the full cleaned/derived export CSV for a `QueryResult` that produced one. This is the one path by which full derived row data leaves the process — an **explicit user download over localhost**, never a network hop to the LLM (see `spec/roadmap.md` Phase 3a design decision #3 and `spec/architecture.md` boundary section).

**Response:** `200` with `Content-Type: text/csv` and `Content-Disposition: attachment; filename="<original_stem>_derived.csv"`, streaming the derived `Dataset`'s `export.csv` (`FileResponse`). The file contains the **full** derived rows (not the 200-row capped result).

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | `query_result_id` doesn't exist, or the result's `export_dataset_id` is null (no export was produced), or the export file is missing on disk |

**Chart/table/export in the answer payload:** the `POST /sessions/{session_id}/messages` and `GET /sessions/{session_id}` responses already carry `query_result.table`, `query_result.chart_spec`, and `query_result.export_dataset_id` (fields present since Phase 1's contract; **populated for real starting Phase 3a**). Their shapes:

- **`table`** (nullable object) — a ranked/summary table built locally from the capped `ExecutionResult` (never raw rows):
  ```json
  {
    "title": "Total revenue by region (ranked)",
    "columns": ["region", "revenue"],
    "rows": [["West", 4201932.10], ["East", 3102111.50]],
    "total_rows": 5,
    "truncated": false
  }
  ```
  `truncated` is `true` (and `rows` shorter than `total_rows`) when the underlying result exceeded `RESULT_ROW_CAP`.

- **`chart_spec`** (nullable object) — a chart definition whose `series` carries **only aggregated/binned points** (≤ `AGENT_CHART_MAX_POINTS`, default 100) drawn from the same capped result, never raw rows:
  ```json
  {
    "type": "bar",
    "title": "Total revenue by region",
    "x_label": "region",
    "y_label": "revenue",
    "series": [{"x": "West", "y": 4201932.10}, {"x": "East", "y": 3102111.50}],
    "truncated": false
  }
  ```
  `type` is one of `"bar" | "line" | "pie"`. `chart_spec` is `null` when the result is a scalar or the model's artifact intent requested no chart.

- **`export_dataset_id`** (nullable UUID) — set when the run produced an `export_df`; points to the promoted derived `Dataset` (which also appears in `GET /datasets`). The download link is `GET /query-results/{id}/export`.

No new request fields are added to `POST /sessions/{session_id}/messages` in Phase 3a — chart/table/export are decided by the agent from the question, not requested by a client flag.

**`anomaly_flags` in the answer payload *(Phase 3b)*:** the `query_result.anomaly_flags` field (present since Phase 1's contract; `[]`/`null` through Phase 1/2/3a) is **populated for real starting Phase 3b**. Its shape changes from the Phase-1 placeholder `list[str]` to a **list of objects**:
```json
"anomaly_flags": [
  {"type": "constant_column", "column": "data_source", "severity": "warning", "message": "data_source has the same value in every row."},
  {"type": "null_values", "column": "region", "severity": "info", "message": "region has missing values."}
]
```
- `type` — a short machine key (e.g. `constant_column`, `null_values`, `outlier`, `duplicate`, `inconsistent_category`).
- `column` — the offending column name, or `null` for a table-wide issue.
- `severity` — one of `"info" | "warning" | "critical"`.
- `message` — a plain-language description for the banner.

Flags are produced by the existing `compose_answer` Gemini call (an `---ANOMALIES---` JSON array, mirroring `---ARTIFACTS---`) merged with a deterministic profile-based check, deduped by `(type, column)` — **zero extra LLM round-trips** (see `spec/roadmap.md` Phase 3b design decisions). Flags are derived from the aggregate `DatasetProfile` and the capped structured results only — never raw rows. `null` when no issues are found.

### `GET /audit-log` *(Phase 3b)*

**Purpose:** List audit-trail entries for the Audit History UI (`frontend/src/app/history/page.tsx`). The underlying `AuditLogEntry` table is written from Phase 1; this **read** endpoint is added in Phase 3b.

**Query params (all optional):**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | string | — | Filter to one session's trail |
| `dataset_id` | string | — | Filter to entries tied to one dataset |
| `event_type` | string | — | Filter to one event type (`upload`\|`clean`\|`profile`\|`ask`\|`code_exec`\|`answer`\|`error`) |
| `limit` | int | 50 | Page size, clamped to a max of 200 |
| `offset` | int | 0 | Page offset |

**Ordering:** `created_at` ascending, then `id` — **chronological**, so a run's `ask` → `code_exec` → `answer` entries read in the order they happened.

**Response:**
```json
{
  "data": {
    "entries": [
      {"id": "uuid-a", "session_id": "uuid-s", "dataset_id": null, "query_result_id": "uuid-qr",
       "event_type": "ask", "detail": {"question": "What is the total revenue?"}, "created_at": "2026-07-02T10:00:00Z"},
      {"id": "uuid-b", "session_id": "uuid-s", "dataset_id": null, "query_result_id": "uuid-qr",
       "event_type": "code_exec", "detail": {"generated_code": "result = df['revenue'].sum()", "step_count": 1}, "created_at": "2026-07-02T10:00:02Z"},
      {"id": "uuid-c", "session_id": "uuid-s", "dataset_id": null, "query_result_id": "uuid-qr",
       "event_type": "answer", "detail": {"status": "completed", "export_dataset_id": null}, "created_at": "2026-07-02T10:00:03Z"}
    ],
    "total": 3,
    "limit": 50,
    "offset": 0
  },
  "error": null
}
```

**Raw-data boundary:** each entry's `detail` is the stored `AuditLogEntry.detail_json` verbatim, which by construction (see `src/graph/nodes.py::finalize`/`handle_error` and the ingestion audit writes) holds only metadata — the question text, the generated code, `step_count`, `status`, `export_dataset_id`, sanitized error text — **never row-level values**. This endpoint performs no join to the underlying data files and never reads a CSV/parquet. Enforced by a raw-data spy assertion in the Phase-3b gate (`tests/integration/test_phase3b_audit_boundary.py`).

**Error cases:** none — an empty/over-filtered result returns `{"entries": [], "total": 0, ...}`.

### `GET /cost-summary` *(Phase 3)*

**Purpose:** Per-session and running-total token/cost figures aggregated from `CostRecord`. The underlying `CostRecord` table is written from Phase 1; this endpoint is added in Phase 3.

## Authentication

None — single local user, no network exposure beyond `localhost:8001`. Out of scope per `spec/roadmap.md`.
