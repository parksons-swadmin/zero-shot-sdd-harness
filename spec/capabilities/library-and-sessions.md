# Capability: Library & Sessions

## What It Does

Holds every uploaded and derived dataset as a browsable library, lets a session scope itself to one or more of those files for cross-file analysis, and persists conversation history against a dataset across days so follow-up questions work without re-uploading.

> **Phase 1 scope note:** this capability is not active in Phase 1 (its data model exists — `Session`, `SessionDataset`, `Message` — because the graph reads/writes them structurally, but every Phase-1 upload gets exactly one fresh, single-question session; there is no library browsing UI and no multi-turn memory yet). It goes live in Phase 2. See the deferral rationale in `spec/agent.md` → Memory & Context.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Set of `dataset_id`s to scope a session to | list of UUIDs | User, via `POST /sessions` (Phase 2 UI) | yes |
| Natural-language question referencing "this file" / "last month's file" etc. | text | User | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Session` + `SessionDataset` rows | DB record | `data.md` → Session, SessionDataset |
| Persisted `Message` history | DB record | `data.md` → Message |
| Library listing | JSON | `GET /datasets` response |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| DB | Create/read `Session`, `SessionDataset`, `Message` rows | 404 if `session_id` unknown; 500 + logged on write failure |
| Gemini (via `conversational-analysis`'s `generate_code`) | Infer which of the session's scoped datasets a question refers to, when more than one is in scope | Falls back to "ask across all scoped datasets" rather than silently picking one, if inference is ambiguous |

## Business Rules

- A session's dataset scope is explicit (`SessionDataset` rows) — the agent only ever infers *which of the already-scoped* files a question refers to, it never silently pulls in a dataset outside the session's scope.
- Conversation history has no expiry (`Session`/`Message` retained indefinitely in v1) — a session opened today must be resumable with full history days later.
- Reopening a session must reload its full message history correctly on the first *and* every subsequent question in that session (a stateful capability — tested with a multi-interaction test, not just a single happy-path call, per `harness/patterns/test-driven.md`).
- Derived/exported datasets (from `dataset-ingestion`) can be added to any session's scope like any other library entry.

## Success Criteria

- [ ] Creating a session with two `dataset_id`s, asking a question, then asking a second follow-up question in the same session returns an answer that reflects the first question's context (e.g. "now break that down by region" correctly reuses the prior filter).
- [ ] A session's message history, fetched via `GET /sessions/{id}` after the process restarts (simulated by re-querying with a fresh DB connection), still returns all prior messages in order.
- [ ] `GET /datasets` lists a dataset not in any session's current scope, and it can be added to a new session without re-uploading.
- [ ] A question naming one of two scoped files by description (e.g. "in the March file") is answered using only that file's data, verified against a known per-file fact.
