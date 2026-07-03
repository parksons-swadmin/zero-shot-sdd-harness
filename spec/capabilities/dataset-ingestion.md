# Capability: Dataset Ingestion

## What It Does

Accepts an uploaded CSV/spreadsheet, auto-cleans malformed data with a report of what was fixed, auto-profiles it (columns, types, row counts), and stores it as a browsable library entry.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| File upload | CSV/TSV/XLSX, up to 100MB | User, via `POST /datasets` | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Dataset` row | DB record | `data.md` → Dataset |
| `DatasetProfile` (columns, types, row/column counts, aggregate stats) | DB record | `data.md` → DatasetProfile |
| `CleaningReport` (issues found + action taken + review flags) | DB record | `data.md` → CleaningReport |
| Cleaned file copy | `.parquet` on disk | `AGENT_DATA_DIR/uploads/<dataset_id>/cleaned.parquet` |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Stream upload to disk, write cleaned parquet | 413 if over size cap before write completes; 500 + logged if disk write fails after |
| Local pandas (in-process, trusted code — not the LLM sandbox) | Parse, clean, profile the **full** file | 400 if unparseable as tabular data; malformed-beyond-recovery fails with 500 and a specific message |

## Business Rules

- Profiling and cleaning always run against the **entire** file — never a truncated sample (see `spec/architecture.md` boundary enforcement and the Phase-1 gate test in `spec/roadmap.md`).
- The original uploaded file is never mutated; cleaning writes a separate `cleaned.parquet`.
- Ambiguous cleaning decisions (e.g. an inconsistent date/phone/country-code format that could be fixed multiple valid ways) are not silently guessed: the default action taken is recorded with `needs_review: true` in the `CleaningReport` rather than blocking the upload.
  > **Assumed:** a blocking, conversational "which fix do you want?" flow is deferred (see `spec/agent.md` → Human-in-the-Loop Checkpoints); v1 flags for review non-blockingly.
- Files over `AGENT_MAX_UPLOAD_BYTES` (default 100MB) are rejected before the write completes.
- **Phase 3a:** exported/derived results (`Dataset.derived_from_query_result_id` set) become ordinary library entries, created via the same profiling machinery (`build_profile` + a trivial empty `CleaningReport`), reusable in future questions like any uploaded file. See `spec/data.md` → "Derived-dataset creation".
- **Phase 2+:** the library (`GET /datasets`) lists every dataset — uploaded and, from Phase 3a, derived — for cross-file selection.

## Success Criteria

- [ ] Uploading a CSV with known dirty values (e.g. mixed date formats, one ambiguous phone format) returns a `CleaningReport` whose `issues` list names the affected column, the action taken, and marks the ambiguous case `needs_review: true`.
- [ ] The returned `DatasetProfile.columns` row/column counts and per-column null/distinct counts exactly match values independently computed over the full source file (not a sample) for a 10,000+ row fixture.
- [ ] A file over `AGENT_MAX_UPLOAD_BYTES` is rejected with HTTP 413 and no partial file is left in `AGENT_DATA_DIR`.
- [ ] (Phase 3a) After an "export …" question, `GET /datasets` lists the resulting derived dataset alongside the originally-uploaded ones, and it can be selected into a session and queried like an upload.
