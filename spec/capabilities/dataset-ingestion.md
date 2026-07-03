# Capability: Dataset Ingestion

## What It Does

Accepts an uploaded tabular file (delimited text, Excel workbook, or — best-effort — a text-based PDF), auto-cleans malformed data with a report of what was fixed, auto-profiles it (columns, types, row counts), and stores it as a browsable library entry. All parsing is fully local (no cloud extraction) so the raw-data-never-leaves-the-machine boundary holds even for PDF.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| File upload | Delimited text (`.csv`, `.tsv`, `.txt`), Excel (`.xlsx`, `.xls`), or text-based PDF (`.pdf`, best-effort — Phase 3d), up to 100MB | User, via `POST /datasets` | yes |

## Accepted Formats & Parsing Rules

Format is inferred from the filename suffix at ingest (no `source_format` DB column — see `spec/data.md` → "Phase 3d note"). Regardless of source format, ingestion produces a **single** pandas DataFrame, which is then cleaned and written to `cleaned.parquet`; everything downstream (profiling, analysis, answers) is format-agnostic.

| Format | Parser | Notes |
|--------|--------|-------|
| `.csv` | `pd.read_csv` | Default. |
| `.tsv` | `pd.read_csv(sep="\t")` | |
| `.txt` | `pd.read_csv` | Treated as delimited text. |
| `.xlsx` | `pd.read_excel` (openpyxl) | Multi-sheet rule below. |
| `.xls` | `pd.read_excel` (xlrd engine) | **Requires the `xlrd` dependency** (added to `pyproject.toml`, Phase 3d) — legacy Excel support per the user's request. |
| `.pdf` | `pdfplumber` → `page.extract_tables()` (Phase 3d) | Best-effort table extraction; rules below. |

### Excel multi-sheet rule (Phase 3d)
> **Assumed:** v1 loads the **first sheet only**. When a workbook has more than one sheet, ingestion records a `CleaningReport` issue `{"column": "*", "issue_type": "excel_extra_sheets_skipped", "action_taken": "loaded first sheet '<name>'; skipped: <other names>", "affected_row_count": 0, "needs_review": true}` so the user knows other sheets were dropped rather than silently losing them. Per-sheet selection / multi-sheet merge is deferred.

### PDF best-effort extraction rule (Phase 3d)
> **Assumed:** PDF ingestion uses **`pdfplumber`** — pure-Python, fully local, no Ghostscript/Java/OCR — chosen so PDF parsing never sends data off-machine (honors `spec/architecture.md` boundary). Tables are extracted per page via `page.extract_tables()` and combined by this rule:
- **First extracted row is the header** for each table.
- **Tables that share a consistent structure** (same column count AND same header row) across pages are **concatenated into one DataFrame** — the typical multi-page report table.
- If **multiple structurally-different tables** exist, the **largest** (by cell count; the first on a tie) is used and the others are recorded as skipped: a `CleaningReport` issue `{"column": "*", "issue_type": "pdf_tables_skipped", "action_taken": "used largest table; skipped N other table(s)", "affected_row_count": 0, "needs_review": true}`.
- **Every** PDF ingest also adds a best-effort caveat issue `{"column": "*", "issue_type": "pdf_best_effort", "action_taken": "extracted table(s) from PDF — this may be inaccurate (merged cells, multi-column layouts, repeated headers); please verify against the source", "affected_row_count": <row_count>, "needs_review": true}`, so the profile screen always shows a visible "verify this" caveat.
- **Scanned / image-only PDFs (no extractable text tables):** extraction yields zero tables → ingestion **fails gracefully** with `422 PDF_NO_TABLES` and the message "This PDF has no extractable tables — it may be scanned/image-based; export to CSV instead." — never a crash or a silently-empty dataset. The partial upload is removed (`remove_dataset_files`). OCR is out of scope (see `spec/roadmap.md` Non-Goals).

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
| Local pdfplumber (in-process, trusted code — fully local, no network) | Extract table(s) from a `.pdf` (Phase 3d) | `422 PDF_NO_TABLES` with a human message when no extractable tables are found (scanned/image PDF) |

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
- [ ] (Phase 3d) Uploading a **multi-page** text-based PDF whose table spans pages produces a `Dataset` whose `row_count` equals the full concatenated row count (all pages, not just page 1), and whose `CleaningReport.issues` contains a `pdf_best_effort` entry with `needs_review: true`.
- [ ] (Phase 3d) Uploading a scanned/image-only PDF (no extractable tables) returns `422` with code `PDF_NO_TABLES` and a human-readable "export to CSV instead" message, and leaves no partial file in `AGENT_DATA_DIR` — never a crash or an empty dataset.
- [ ] (Phase 3d) A legacy `.xls` workbook parses to `status: "ready"`; a multi-sheet `.xlsx`/`.xls` parses to `ready` with an `excel_extra_sheets_skipped` `CleaningReport` issue naming the skipped sheet(s).
- [ ] (Phase 3d) No PDF/Excel parse makes any network call — parsing is fully local (pdfplumber/pandas), preserving the raw-data boundary.
