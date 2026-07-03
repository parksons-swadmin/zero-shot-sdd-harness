# Capability: Audit & Cost Tracking

## What It Does

Persistently logs every question asked, every piece of code run, and every result stored, with timestamps — and records the token usage/estimated cost of every LLM call — so the tool is auditable and its running cost is visible.

> **Phase 1 scope note:** the underlying log/cost writes are real from Phase 1 (a production-readiness hard constraint, not deferred), but the history and cost **UI** are Phase-1 stubs and go live in Phase 3.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Every graph node transition and API call outcome | event | `graph/*`, `api/*` | yes (implicit — no user input) |
| Gemini `usage_metadata` from every LLM response | token counts | `llm/client.py` | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `AuditLogEntry` rows | DB record | `data.md` → AuditLogEntry |
| `CostRecord` rows | DB record | `data.md` → CostRecord |
| Audit history listing (Phase 3) | JSON | `GET /audit-log` |
| Cost summary (Phase 3) | JSON | `GET /cost-summary` |
| Structured stdout logs | JSON log line | stdout, per `spec/architecture.md` → Observability |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| DB | Write `AuditLogEntry`/`CostRecord` on every relevant event | Logged to stdout; a failure to write an audit/cost row is itself logged as an error but never blocks the user-facing response (non-critical, degrades gracefully per `harness/rules/ai-agents.md` rule 7) |
| Gemini API | Read `usage_metadata` off each response | If usage metadata is absent from a response, the `CostRecord` is written with `prompt_tokens=0, completion_tokens=0` and a logged warning — never fabricated numbers |

## Business Rules

- Every one of `upload`, `clean`, `profile`, `ask`, `code_exec`, `answer`, `error` writes exactly one `AuditLogEntry`, timestamped, from Phase 1 onward.
- Audit log entries never contain raw row-level data — only event metadata, code, and structured results (same boundary as `conversational-analysis`).
- Every LLM call writes exactly one `CostRecord` before the enclosing node returns, so cost data is never lost even if a later step in the same run fails.
- No log rotation/retention limit in v1 (explicit deferral to Phase 4 hardening) — the audit trail is append-only and complete.

## Success Criteria

- [ ] After a successful upload + ask, querying the DB directly shows `AuditLogEntry` rows for `upload`, `clean`, `profile`, `ask`, `code_exec`, `answer` with correct `created_at` ordering, even before any audit UI exists (Phase 1).
- [ ] After a run that includes N Gemini calls, exactly N `CostRecord` rows exist with non-zero `prompt_tokens`/`completion_tokens` when the provider returns usage metadata.
- [ ] (Phase 3) `GET /audit-log?session_id=...` returns the entries for a known session in chronological order.
- [ ] (Phase 3) `GET /cost-summary` returns a running total equal to the sum of all `CostRecord.estimated_cost_usd` for the current data, verified against an independently computed sum in the test.
- [ ] A failed run (e.g. Gemini timeout) still produces an `AuditLogEntry` with `event_type="error"` and any `CostRecord`s for calls that completed before the failure.
