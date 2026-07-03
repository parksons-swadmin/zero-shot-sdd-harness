# Capability: Conversational Analysis

## What It Does

Answers a natural-language question about one or more datasets by writing and locally running real analysis code, escalating from a single reasoning pass to iterative refinement or full upfront planning only as the question warrants, and returns a plain-language answer with the underlying code shown for verification.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `question` | text | User, via `POST /sessions/{id}/messages` | yes |
| `DatasetProfile`(s) for the session's dataset(s) | aggregate metadata | `data.md` → DatasetProfile | yes |
| Prior `Message` history for the session | text | `data.md` → Message | no (Phase 2+ only; Phase 1 sessions are single-question) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Message` (assistant) + `QueryResult` | DB record | `data.md` → Message, QueryResult |
| Plain-language answer with inline key numbers | text (markdown) | UI answer panel |
| Generated pandas code | text | UI collapsible code panel |
| Ranked/summary table, chart spec, export file | structured / file | UI table+chart+export (Phase 3) |
| Follow-up question suggestions | text list | UI (Phase 2) |
| Anomaly flags | `list[{type, column, severity, message}]` | UI anomaly banner (Phase 3b) |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini API | Classify reasoning depth (Phase 2+), plan steps (Phase 2+), generate code, check result (Phase 2+), compose answer | Node sets `error`, routes to `handle_error`; user sees a plain-language failure, never a stack trace |
| Local sandboxed executor | Run generated code against the real, full dataframe(s) | Guard rejection or timeout: fatal on the `simple` path; fed back to `check_result` as feedback on `iterative`/`planned` (Phase 2+) |

## Business Rules

- The LLM never receives row-level data — only `DatasetProfile` aggregate metadata and the sandbox's capped, structured `ExecutionResult` (see `spec/architecture.md` boundary enforcement). This is non-negotiable across all reasoning modes.
- Analysis code always executes against the **full** dataframe(s), never a truncated sample — the correctness of the answer must not depend on dataset size.
- Reasoning depth escalates only as needed: `simple` (one code-gen + execute pass) for straightforward lookups, `iterative` (generate → execute → check → refine, bounded) for questions needing a correction pass, `planned` (explicit multi-step plan, executed step by step) for genuinely multi-part questions. Bounded by `AGENT_MAX_ITERATIONS`, `AGENT_MAX_PLAN_STEPS`, `AGENT_MAX_TOTAL_STEPS` (see `spec/agent.md`) — never an unbounded loop.
- **Phase 1** exercises only the `simple` path; `classify_query` is hardcoded to `"simple"` (see `spec/agent.md`).
- **Phase 2+:** a question referencing multiple datasets in scope ("this month vs last month") triggers a join/compare in the generated code; the agent infers which files in the session's dataset scope the question refers to.
- **Phase 2:** the agent proactively suggests 2–3 follow-up questions on every completed answer, produced by the same `compose_answer` call at no extra LLM-call cost — never fabricated when there is nothing notable to suggest.
- **Phase 3a:** answers may carry a ranked/summary `table` and an interactive `chart_spec`, both built locally and deterministically from the capped `ExecutionResult` (never raw rows), with the chart/table *intent* (type, x/y column mapping, titles) coming from the same `compose_answer` call — zero extra LLM calls. The chart `series` is capped to `AGENT_CHART_MAX_POINTS`. When the analysis code assigns an optional full `export_df`, a downloadable derived dataset is produced (see `dataset-ingestion`).
- **Phase 3b:** the agent additionally surfaces anomalies/data-quality issues it notices while answering, as part of the same `compose_answer` output (`anomaly_flags`).
- Every LLM call's token usage is recorded as a `CostRecord`, from Phase 1 onward, regardless of whether the cost UI exists yet.

## Success Criteria

- [ ] A single-fact lookup question against a 10,000+ row fixture with a pre-computed exact answer (e.g. "what is the total of column X") returns `summary_text` containing that exact value, with `reasoning_mode == "simple"`, within 30 seconds.
- [ ] The `generated_code` field contains the actual pandas code that ran (verifiable by re-running it against the same file and getting the same `result`).
- [ ] No prompt sent to Gemini (asserted via a test double / log capture in an integration test) contains a raw row value from the uploaded fixture — only aggregate profile fields and structured execution results.
- [ ] (Phase 2) A question requiring cross-file joins against two dataset fixtures returns the correct joined value and records `dataset_ids` with both files.
- [ ] (Phase 2) A deliberately multi-part question forces `reasoning_mode == "planned"` with `step_count > 1`, and the run terminates within `AGENT_MAX_TOTAL_STEPS`.
- [ ] (Phase 3a) A question answerable with a ranked breakdown returns a non-null `table_json` whose rows match independently pre-computed aggregates; a chart-appropriate question returns a non-null `chart_spec_json` whose `series` length ≤ `AGENT_CHART_MAX_POINTS` and is drawn only from the capped result (not raw rows); an "export …" question returns a non-null `export_dataset_id` whose downloaded file has the full derived row count while table/chart remain capped.
- [ ] (Phase 3a) No prompt sent to Gemini during an artifact/export run contains a raw row value or the export file's rows (asserted via a prompt spy) — only aggregate profile fields and capped structured results.
- [ ] (Phase 3b) A dataset with a deliberately anomalous column yields a non-empty `anomaly_flags` on a completed answer.
