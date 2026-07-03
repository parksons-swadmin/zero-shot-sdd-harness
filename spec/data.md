# Data Model

---

## Storage Technology

SQLite (`AGENT_DATABASE_URL`, WAL mode) via SQLAlchemy 2.0, managed by Alembic migrations — see `spec/architecture.md` → Stack for the rationale. Uploaded/cleaned/exported files themselves live on the local filesystem (`spec/architecture.md` → File Storage Layout); the DB stores metadata and paths, never raw row values.

## Entities

### Entity: Dataset

One uploaded (or derived/exported) file and its identity.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| filename | text | yes | Original upload filename |
| original_path | text | yes | Path to the untouched original file |
| cleaned_path | text | no | Path to the cleaned `.parquet` copy (set once cleaning completes) |
| row_count | integer | no | Full row count, set once profiled |
| column_count | integer | no | Set once profiled |
| size_bytes | integer | yes | Original file size |
| status | text | yes | `uploading` \| `cleaning` \| `ready` \| `error` |
| derived_from_query_result_id | UUID (text) | no | Set when this dataset is an exported/derived result (Phase 3), FK → QueryResult |
| created_at | timestamp | yes | |
| updated_at | timestamp | yes | |

### Entity: DatasetProfile

The aggregate schema/summary metadata for a dataset — **the only representation of a dataset's shape ever sent to the LLM** (see `spec/architecture.md` → boundary enforcement).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| dataset_id | UUID (text) | yes | FK → Dataset, unique (one profile per dataset) |
| columns_json | JSON | yes | Per column: `{name, dtype, null_count, distinct_count, min, max, mean, median, top_values: [{value, count}]}` — all aggregates, never raw rows |
| generated_at | timestamp | yes | |

### Entity: CleaningReport

What was auto-fixed on upload.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| dataset_id | UUID (text) | yes | FK → Dataset, unique |
| issues_json | JSON | yes | List of `{column, issue_type, action_taken, affected_row_count, needs_review: bool}` |
| generated_at | timestamp | yes | |

### Entity: Session

A conversation container against one or more datasets; persists across days.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| title | text | no | Auto-derived from the first question, or filename (Phase 1) |
| created_at | timestamp | yes | |
| updated_at | timestamp | yes | Bumped on every new message |

### Entity: SessionDataset (join table)

Which dataset(s) a session is scoped to (many-to-many — enables cross-file sessions in Phase 2).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| session_id | UUID (text) | yes | FK → Session |
| dataset_id | UUID (text) | yes | FK → Dataset |

### Entity: Message

One turn in a session's conversation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| session_id | UUID (text) | yes | FK → Session |
| role | text | yes | `user` \| `assistant` |
| content | text | yes | Plain-language text only — never a serialized dataframe |
| created_at | timestamp | yes | |

### Entity: QueryResult

The structured artifact produced by an assistant `Message`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| message_id | UUID (text) | yes | FK → Message (the assistant message this belongs to) |
| session_id | UUID (text) | yes | FK → Session (denormalized for query convenience) |
| reasoning_mode | text | yes | `simple` \| `iterative` \| `planned` |
| summary_text | text | yes | The plain-language answer |
| key_numbers_json | JSON | no | `[{label, value}]` highlighted inline |
| table_json | JSON | no | Ranked/summary table (Phase 3) |
| chart_spec_json | JSON | no | Chart definition (Phase 3) |
| export_dataset_id | UUID (text) | no | FK → Dataset, set if an export was produced (Phase 3) |
| generated_code | text | yes | The exact pandas code that ran, shown in the collapsible panel |
| follow_up_questions_json | JSON | no | Suggested next questions, 2-3 per answer (Phase 2) |
| anomaly_flags_json | JSON | no | Data-quality flags noticed while answering (Phase 3) |
| step_count | integer | yes | How many graph nodes/iterations this run took |
| status | text | yes | `completed` \| `failed` \| `partial` |
| created_at | timestamp | yes | |

### Entity: AuditLogEntry

Full, timestamped audit trail — written from Phase 1 onward regardless of whether a UI shows it yet.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| session_id | UUID (text) | no | FK → Session, if applicable |
| dataset_id | UUID (text) | no | FK → Dataset, if applicable |
| query_result_id | UUID (text) | no | FK → QueryResult, if applicable |
| event_type | text | yes | `upload` \| `clean` \| `profile` \| `ask` \| `code_exec` \| `answer` \| `error` |
| detail_json | JSON | yes | Event-specific structured detail (never raw row data) |
| created_at | timestamp | yes | |

### Entity: CostRecord

Per-LLM-call token usage and estimated cost.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| query_result_id | UUID (text) | no | FK → QueryResult (null for calls not yet tied to a finished result, e.g. a failed run) |
| provider | text | yes | `gemini` |
| model | text | yes | Model ID used for this call |
| prompt_tokens | integer | yes | |
| completion_tokens | integer | yes | |
| estimated_cost_usd | numeric | yes | Computed from the configured price table |
| created_at | timestamp | yes | |

### Relationships

- `Dataset` 1—1 `DatasetProfile`, 1—1 `CleaningReport`
- `Dataset` 1—N `AuditLogEntry`, `Dataset` 0—1 `derived_from_query_result_id` → `QueryResult` (an export becomes a new `Dataset`)
- `Session` M—M `Dataset` via `SessionDataset`
- `Session` 1—N `Message`, 1—N `AuditLogEntry`
- `Message` 1—0/1 `QueryResult` (only assistant messages have one)
- `QueryResult` 1—N `CostRecord`, 1—N `AuditLogEntry`, 0—1 `export_dataset_id` → `Dataset`

## Phase 3a note — no new migration; existing columns become live

**No new Alembic migration is required for Phase 3a.** Every column Phase 3a writes already exists in the head migration (see `src/db/models.py`), created for Phase 1 and unused until now:
- `Dataset.derived_from_query_result_id` (nullable FK → `query_results.id`) — set when a `Dataset` is a promoted export.
- `QueryResult.table_json`, `QueryResult.chart_spec_json`, `QueryResult.export_dataset_id` (nullable FK → `datasets.id`), `QueryResult.anomaly_flags_json` — 3a is the first writer of `table_json`/`chart_spec_json`/`export_dataset_id`; `anomaly_flags_json` stays unused until Phase 3b.

**Derived-dataset creation (Phase 3a).** When an answer's analysis code assigns an `export_df`, `finalize` promotes it into an ordinary library entry, reusing the existing ingestion machinery (no parallel structure):
1. `storage/exports.promote_export(query_result_id, temp_path)` writes `exports/<query_result_id>/export.csv` and `export.parquet` (see `spec/architecture.md` → File Storage Layout).
2. A new `Dataset` row is created with `original_path` → `export.csv`, `cleaned_path` → `export.parquet`, `row_count`/`column_count` from the derived frame, `status="ready"`, and `derived_from_query_result_id` = the producing `QueryResult.id`.
3. A `DatasetProfile` is written via `tools/profiling.build_profile` (same aggregate-only profiler used for uploads — so the derived dataset is immediately queryable), plus a trivial `CleaningReport` with `issues_json={"issues": []}` (derived data is already clean) so the dataset is a complete library citizen for `GET /datasets/{id}`.
4. The producing `QueryResult.export_dataset_id` is set to the new `Dataset.id`, and an `AuditLogEntry(event_type="answer")` records `export_dataset_id` in its `detail_json` (aggregate metadata only — never rows).

## Data Lifecycle

- **Dataset:** created `uploading` → `cleaning` → `ready` (or `error`); never auto-deleted or expired in v1 — the user's library is expected to persist indefinitely. Original files are never mutated after upload. **A derived/exported dataset (Phase 3a)** is created directly in `ready` status with `derived_from_query_result_id` set, and is otherwise indistinguishable from an upload for library listing and analysis.
- **Session/Message/QueryResult:** created on first question, updated on every subsequent turn; no TTL — conversations may resume after days, per the brief.
- **AuditLogEntry:** append-only, retained indefinitely in v1; log rotation/archival policy is explicitly deferred to Phase 4 hardening.
- **CostRecord:** append-only, one row per LLM call; summed for the running-total cost display (Phase 3).
- **SessionDataset (Phase 2):** a session's dataset scope is fixed at creation and never mutated — selecting a new/different set of files in the library always creates a new `Session` (+ its `SessionDataset` rows) over the union of selected `dataset_ids`, rather than appending to an existing session's scope. See `spec/roadmap.md` Phase 2 "Design decisions" for the rationale.

## Sensitive Data

Uploaded CRM/ops exports may contain PII (names, emails, revenue figures). Mitigations:
- Raw row values live only in `original.csv`/`cleaned.parquet` on the local filesystem — never copied into any DB text column, never included in a Gemini prompt (see `spec/architecture.md` boundary enforcement).
- `DatasetProfile.columns_json` and `AuditLogEntry.detail_json` store only aggregates/metadata (counts, dtypes, code, structured results) — reviewed at code-generation time to ensure no row-shaped payload is ever serialized into them.
- No authentication/encryption-at-rest is added in v1 (single local user, local disk) — out of scope per `spec/roadmap.md`.
