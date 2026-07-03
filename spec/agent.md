# Agent

---

## Agent Architecture Pattern

**Chosen:** Graph (LangGraph) — a Tool-Use / ReAct loop (patterns #5 Tool Use, #17 Reasoning/ReAct from `harness/patterns/agentic-ai.md`) with **Routing** (#2, `classify_query` picks the reasoning depth), **Planning** (#6, `plan_steps` for hard questions), **Reflection** (#4, `check_result` critiques the sandbox output before accepting it), **Resource-Aware Optimization** (#16, cheap router model + per-call cost capture), **Guardrails** (#18, the AST/network sandbox guard), and **Exception Handling & Recovery** (#12, every node routes failures to `handle_error`). This is deliberately the ReAct floor plus the minimum upgrades the roadmap's adaptive-depth requirement needs — not a multi-agent system, because one agent with tools and a router is sufficient here.

**Why not less:** the task inherently needs tool use (LLM-generated code must actually run against real data — pattern #22, LLM-Generated Code Execution) and branches by difficulty, so a bare prompt chain is insufficient.
**Why not more:** roles don't genuinely differ enough to warrant multi-agent collaboration (#7) — one agent alternating between "write code" and "check/compose" covers the requirement.

**Phase 1 scope:** only the `simple` branch is exercised for real (Tool Use + Reasoning, no Routing/Planning/Reflection escalation). `classify_query` is wired but hardcoded to return `"simple"`; `plan_steps` and `check_result` are stubs that are never reached. **Phase 2** ("Agentic Stack Upgrade" per `harness/patterns/phases.md`) replaces the stub with a real Gemini-flash routing call and activates `plan_steps`/`check_result`, completing the pattern composition above. No graph-topology change is needed for this — every conditional edge listed below already exists from Phase 1; Phase 2 only swaps node *bodies*.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `classify_query` (Phase 2+) | Gemini | `gemini-2.5-flash` | Cheap/fast classification, not quality-sensitive |
| `plan_steps` | Gemini | `gemini-3.1-pro` | Planning quality matters; runs rarely (only on the `planned` path) |
| `generate_code` | Gemini | `gemini-3.1-pro` | Correctness of generated pandas code is the whole point |
| `check_result` (Phase 2+) | Gemini | `gemini-3.1-pro` | Judging whether an intermediate result answers the sub-question needs real reasoning |
| `compose_answer` | Gemini | `gemini-3.1-pro` | User-facing prose quality matters |

Both model IDs are env-configurable (`AGENT_LLM_MODEL` for the `-pro` nodes, `AGENT_LLM_ROUTER_MODEL` for the router) per `harness/patterns/tech-stack.md`.

**Per-call model override (Phase 2+):** `LLMClient`/`GeminiProvider` (Phase 1) only supported one configured model per client instance, which was sufficient while `classify_query` was hardcoded. Phase 2 adds an optional `model: str | None = None` keyword to both `LLMClient.call_model_with_usage` and `GeminiProvider.call_model_with_usage` (and the Anthropic provider, for interface parity): when passed, it overrides the provider's configured model for that single call only — `self._model`/`self._provider` are never mutated, so a `LLMClient()` instance can be reused across a router call (`gemini-2.5-flash`) and a `-pro` call (`gemini-3.1-pro`) in the same node without cross-contamination. `classify_query` is the only Phase 2 caller that passes `model=settings.llm_router_model or "gemini-2.5-flash"`; every other node omits it and gets the configured `AGENT_LLM_MODEL` default.

**Fallback behaviour:** on a Gemini 4xx/5xx/timeout, the calling node catches the exception, sets `state["error"]`, and routes to `handle_error` — no retry-with-backoff in Phase 1 (single-call, user is watching); Phase 4 hardening adds bounded retry-with-backoff (max 2 retries, exponential) for transient 5xx/timeout only, never for 4xx (bad request/prompt).

**Prompt strategy:** system/user split via `.md` templates in `src/prompts/`. `generate_code` requests a fenced Python code block only (no prose) and is parsed by extracting the fenced block; `compose_answer` requests plain-language prose with numbers **bolded inline** (markdown), which the frontend renders through a markdown renderer per `harness/patterns/ui-ux.md`.

---

## Tools & Tool Calling

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `run_analysis_code` | Executes Gemini-generated pandas code against the real, full dataframe(s) in a guarded subprocess | `code: str`, `dataframes: dict[str, DataFrame]`, `timeout_s: int` | `ExecutionResult` (capped `result`, capped `stdout`, `error`, `duration_ms`) | None outside the subprocess; no network, no disk writes outside a scratch temp dir |
| `build_profile` | Computes full-dataset aggregate stats (not a sample) | `df: DataFrame` | `DatasetProfile` | None (read-only) |
| `clean_dataset` | Detects and fixes malformed rows/columns, records what was changed | `df: DataFrame` | `(cleaned_df: DataFrame, CleaningReport)` | Writes `cleaned.parquet` to disk |

**Tool selection strategy:** not LLM-chosen — the graph topology (not the LLM) decides which tool runs at each node; the LLM's only "choice" is the routing decision at `classify_query` (Phase 2+) among the three fixed reasoning modes.

**Tool failure handling:** `run_analysis_code` failures (guard rejection, runtime exception, timeout) are fed back into `check_result`'s next iteration as `feedback` (iterative/planned paths) or straight to `handle_error` (simple path, since there is no retry loop for it in Phase 1).

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str
    session_id: str
    dataset_ids: list[str]

    # Input
    question: str
    conversation_history: list[dict]        # [{role, content}] loaded from Message rows
    profiles: list[dict]                     # DatasetProfile.model_dump() per dataset — schema/summary ONLY

    # Reasoning control
    reasoning_mode: str                      # "simple" | "iterative" | "planned" — set by classify_query
    plan_steps: list[str]                    # set by plan_steps (planned path only), len <= MAX_PLAN_STEPS
    current_step_index: int
    iteration_count: int                     # refine-loop counter, capped at MAX_ITERATIONS
    step_count: int                          # total nodes executed this run, capped at MAX_TOTAL_STEPS
    step_label: str                          # human-readable current step, for UI progress (Phase 3)

    # Pipeline data (populated progressively by nodes)
    generated_code: str
    execution_result: dict                   # ExecutionResult — capped, structured, never raw rows
    accumulated_summaries: list[dict]         # one ExecutionResult summary per completed step
    check_decision: str                      # "accept" | "refine" (iterative/planned only)
    check_feedback: str | None

    # Output
    answer_text: str
    key_numbers: list[dict]                  # [{label, value}]
    table_data: dict | None                  # Phase 3a
    chart_spec: dict | None                  # Phase 3a
    export_path: str | None                  # Phase 3a (final promoted export path)
    export_meta: dict | None                 # Phase 3a — {temp_path,row_count,column_count} from sandbox, promoted in finalize
    follow_up_questions: list[str]           # Phase 2 — set by compose_answer, no extra LLM call
    anomaly_flags: list[str]                 # Phase 3b
    cost_records: list[dict]                 # one per LLM call this run

    # Control
    error: str | None
    status: str                              # "completed" | "failed" | "partial"
```

Constants (env-configurable): `AGENT_MAX_ITERATIONS=4`, `AGENT_MAX_PLAN_STEPS=5`, `AGENT_MAX_TOTAL_STEPS=8`.

---

## Nodes / Steps

### `load_context`
**Reads from state:** `session_id`, `dataset_ids`
**Writes to state:** `profiles`, `conversation_history`
**LLM call:** no
**External calls:** DB reads (`DatasetProfile`, `Message`) — on failure, fatal (missing dataset/session → set `error`)
**Behaviour:** Loads the aggregate profile(s) for the dataset(s) in scope and prior message history for the session. Never loads raw row data.

### `classify_query`
**Reads from state:** `question`, `profiles`
**Writes to state:** `reasoning_mode`
**LLM call:** Phase 1 — no (hardcoded `"simple"`). Phase 2+ — yes, `gemini-2.5-flash`, structured output `{"mode": "simple"|"iterative"|"planned"}`.
**External calls:** none beyond the LLM call
**Behaviour:** Routes the question to the cheapest reasoning depth that can answer it correctly.

### `plan_steps` *(Phase 2+)*
**Reads from state:** `question`, `profiles`
**Writes to state:** `plan_steps` (capped at `MAX_PLAN_STEPS`)
**LLM call:** yes, `gemini-3.1-pro`
**Behaviour:** Produces an ordered list of sub-questions whose answers, combined, answer the original question.

### `generate_code`
**Reads from state:** `question` (or current plan step), `profiles`, `accumulated_summaries`, `check_feedback`
**Writes to state:** `generated_code`
**LLM call:** yes, `gemini-3.1-pro`, requests a fenced pandas code block that assigns to `result`
**Behaviour:** Writes analysis code from the schema/summary metadata and question alone — never sees raw rows.

### `execute_code`
**Reads from state:** `generated_code`, `dataset_ids`
**Writes to state:** `execution_result`, `accumulated_summaries` (append), `step_count` (+1)
**LLM call:** no
**External calls:** the sandbox (`run_analysis_code`) — on guard rejection or timeout: fatal for `simple` mode (→ `handle_error`), feeds `check_result` as a failure to react to for `iterative`/`planned`
**Behaviour:** Runs the code from `generate_code` against the full real dataframe(s) via `src/execution/sandbox.py`.

### `check_result` *(Phase 2+; skipped entirely on the `simple` path)*
**Reads from state:** `execution_result`, `question`/current step, `iteration_count`, `step_count`
**Writes to state:** `check_decision`, `check_feedback`, `iteration_count` (+1 on refine)
**LLM call:** yes, `gemini-3.1-pro`
**Behaviour:** Judges whether `execution_result` answers the current question/step. Forces `"accept"` once `iteration_count >= MAX_ITERATIONS` or `step_count >= MAX_TOTAL_STEPS` (bounded escalation — never loops unboundedly).

### `advance_plan` *(Phase 2+, `planned` mode only)*
**Reads from state:** `plan_steps`, `current_step_index`
**Writes to state:** `current_step_index` (+1) or signals plan complete
**LLM call:** no
**Behaviour:** Moves to the next plan step, or proceeds to `compose_answer` once all steps are done or `step_count` hits `MAX_TOTAL_STEPS`.

### `compose_answer`
**Reads from state:** `accumulated_summaries`, `question`, `conversation_history`
**Writes to state:** `answer_text`, `key_numbers`, `follow_up_questions` (Phase 2), `table_data` (Phase 3a), `chart_spec` (Phase 3a), `anomaly_flags` (Phase 3b)
**LLM call:** yes, `gemini-3.1-pro`
**Behaviour:** Synthesizes the final plain-language answer from the accumulated structured summaries only — never from raw rows. **Phase 2:** the same single call also produces 2-3 follow-up questions at zero extra LLM-call cost. `src/prompts/compose_answer.md` instructs the model to end its response with a literal `---FOLLOW-UPS---` line followed by 2-3 `- `-prefixed questions. A new `_split_answer_and_follow_ups(text)` helper in `src/graph/nodes.py` splits the raw response on that marker *before* `_extract_key_numbers` runs its bolded-number regex against the prose portion only, so the two parsers never collide. If the marker is absent (model didn't follow the format), `follow_up_questions` is set to `[]` rather than failing the run. **Phase 3a:** the same call additionally emits a trailing `---ARTIFACTS---` JSON block (chart/table *intent only* — type, x/y column mapping, titles — never data values), parsed by a generalised `_split_answer_sections(text) -> (prose, follow_ups, artifact_intent)`; `_build_table_data`/`_build_chart_spec` then assemble `table_data`/`chart_spec` deterministically from the capped `execution_result` alone (chart series capped to `AGENT_CHART_MAX_POINTS`) — still zero extra LLM calls. **Phase 3b:** a further `---ANOMALIES---` block populates `anomaly_flags`.

### `handle_error`
**Reads from state:** `error`, `run_id`, `session_id`
**Writes to state:** `status = "failed"`
**External calls:** writes an `AuditLogEntry` (`event_type="error"`) — never fails silently
**Behaviour:** Terminal failure path; the API renders a human-readable error, never a raw stack trace, per `harness/patterns/code.md`.

### `finalize`
**Reads from state:** everything produced above
**Writes to state:** `status = "completed"` (or `"partial"` if a step/iteration cap was hit)
**External calls:** persists `Message` (assistant), `QueryResult`, `CostRecord`(s), `AuditLogEntry` (`event_type="answer"`); **Phase 3a:** also persists `table_json`/`chart_spec_json`, and when `export_meta` is present promotes the temp export into a derived `Dataset` (+ `DatasetProfile` + empty `CleaningReport`) via `storage/exports.promote_export` and sets `QueryResult.export_dataset_id` (see `spec/data.md` → "Derived-dataset creation").
**Behaviour:** Single place where a successful run's output is committed to the DB.

---

## Graph / Flow Topology

```
START
  │
  ▼
load_context ──(error)──► handle_error ──► END
  │
  ▼
classify_query
  │
  ├─(simple)────────────────────────────────────────► generate_code
  ├─(iterative)─────────────────────────────────────► generate_code
  └─(planned)──► plan_steps ──► generate_code
                                    │
                                    ▼
                              execute_code ──(guard/timeout, simple mode)──► handle_error ──► END
                                    │
                    ┌───────────────┴────────────────┐
              (simple mode)                  (iterative/planned mode)
                    │                                 ▼
                    │                          check_result
                    │                                 │
                    │                    ┌────────────┼─────────────────┐
                    │              (refine, under caps)          (accept, planned,
                    │                    │                        steps remain)
                    │                    ▼                              ▼
                    │              generate_code                  advance_plan ──► generate_code
                    │                                                    │
                    │                                          (accept / plan exhausted /
                    │                                           caps hit)
                    ▼                                                    ▼
              compose_answer ◄─────────────────────────────────────────┘
                    │
                    ▼
                finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `load_context` | `state["error"]` is set | `handle_error` |
| `load_context` | else | `classify_query` |
| `classify_query` | `reasoning_mode == "planned"` | `plan_steps` |
| `classify_query` | `reasoning_mode in {"simple", "iterative"}` | `generate_code` |
| `plan_steps` | always | `generate_code` |
| `generate_code` | `state["error"]` is set | `handle_error` |
| `generate_code` | else | `execute_code` |
| `execute_code` | `state["error"]` set AND `reasoning_mode == "simple"` | `handle_error` |
| `execute_code` | `reasoning_mode == "simple"` (no error) | `compose_answer` |
| `execute_code` | `reasoning_mode in {"iterative", "planned"}` | `check_result` |
| `check_result` | `check_decision == "refine"` AND `iteration_count < MAX_ITERATIONS` AND `step_count < MAX_TOTAL_STEPS` | `generate_code` |
| `check_result` | `check_decision == "accept"` AND `reasoning_mode == "planned"` AND steps remain AND `step_count < MAX_TOTAL_STEPS` | `advance_plan` |
| `check_result` | otherwise (accept, or caps hit) | `compose_answer` |
| `advance_plan` | more plan steps remain | `generate_code` |
| `advance_plan` | plan exhausted | `compose_answer` |
| `compose_answer` | `state["error"]` is set | `handle_error` |
| `compose_answer` | else | `finalize` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph `AgentState` | All in-progress data for one question |
| **Across runs (same session)** | `Message` + `QueryResult` rows, loaded by `load_context` | Prior questions/answers so follow-ups like "now break that down by region" work — **Phase 2+**; Phase 1 has no multi-turn memory (see below) |
| **Across days** | Same `Session`/`Message` rows — no TTL/expiry in v1 | Full conversation history against a dataset, resumable after any gap |

> **Assumed — Phase 1 has no conversational memory, by explicit deferral, not oversight.** The intake brief's fixed Phase 1 scope is "ask **one** natural-language question" per upload — a single question/answer pass, not a running chat thread. Multi-turn memory requires the `Session`/`Message` persistence and file-inference machinery that is the core deliverable of the `library-and-sessions` capability (Phase 2). Phase 1's `AgentState.conversation_history` is wired (the field exists, `load_context` reads it) but is always empty in Phase 1 since each upload starts a fresh, single-question session. This is called out explicitly per the self-review requirement on conversational memory, and is not a silent gap.
>
> **Phase 2 update:** `load_context` now populates `conversation_history` for real — it loads prior `Message` rows for `session_id` (ordered by `created_at`) whenever a session is resumed (including across a browser reload/days later, per `library-backend`'s `GET /sessions/{session_id}`). No change to `load_context`'s Phase 1 code path for a brand-new session (still starts with empty history) — this is additive, not a rewrite.

**Context window management:** profiles and accumulated summaries are small (aggregate stats, not rows), so no summarization/truncation strategy is needed for the context sent to Gemini in v1; `conversation_history` (Phase 2+) is passed in full since a personal analysis session is not expected to run to context-window-threatening length, revisited in Phase 4 hardening if needed.

---

## Human-in-the-Loop Checkpoints

None in Phase 1–3. The brief's "the agent asks the user how to handle ambiguous data issues" is implemented as a **non-blocking** default in v1: `clean_dataset` flags ambiguous cases in the `CleaningReport` as `needs_review=true` with the action it defaulted to, rather than pausing the graph for approval.
> **Assumed:** a blocking human-in-the-loop cleaning-approval dialog is out of scope for the phases in this spec; if required later it would add a `Human-in-the-Loop` checkpoint at `clean_dataset` and is a candidate for a future phase, not this one.

---

## Error Handling & Recovery

**Node-level:** every node wraps its work in try/except; any exception sets `state["error"] = str(exc)` and the routing table above sends it to `handle_error`.

**Graph-level (`handle_error` node):**
- Reads: `state.error`, `state.run_id`, `state.session_id`
- Writes: `Message`/`QueryResult` status is not created; an `AuditLogEntry` (`event_type="error"`) is written with the error detail
- Terminates the graph (routes to `END`)

**Resume / retry strategy:** none in Phase 1–3 — a failed run is simply reported as failed; the user re-asks. Phase 4 adds bounded retry-with-backoff for transient Gemini 5xx/timeout only (see LLM Provider section above). No LangGraph checkpointer is used (see Concurrency below) since runs are short-lived and synchronous.

**Partial failure:** if the iteration/step caps are hit before `check_result` accepts, `compose_answer` still runs against whatever `accumulated_summaries` exist and the run finalizes with `status="partial"` and the answer is prefixed with a plain-language caveat — never a silent wrong answer presented as complete.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **LLM calls** | model, prompt size, latency, prompt/completion tokens, status | `structlog` JSON line to stdout, per call, from Phase 1 |
| **Node transitions** | node name, `run_id`, `step_count`, duration | `structlog` JSON line to stdout, per node, from Phase 1 |
| **Run outcome** | status, total duration, error if any | DB (`QueryResult`/`AuditLogEntry`) + structured log |
| **Audit trail** | every `upload`/`clean`/`profile`/`ask`/`code_exec`/`answer`/`error` event, timestamped | `AuditLogEntry` table, from Phase 1 (UI in Phase 3) |
| **Cost** | per-call token usage + estimated cost | `CostRecord` table, from Phase 1 (UI in Phase 3) |

## Concurrency Model

- **Run isolation:** one in-flight graph run per `session_id`, enforced by an in-process lock in `graph/runner.py`; a concurrent request for the same session gets `409 Conflict`. Different sessions run concurrently against SQLite in WAL mode.
- **Parallel nodes within a run:** none — the loop is inherently sequential (each step's input depends on the prior step's output), so no parallelization pattern is applied.
- **Checkpointing:** none. Runs are synchronous within one HTTP request/SSE stream and bounded to `MAX_TOTAL_STEPS`, so resume-from-checkpoint is not needed to meet the sub-30s (simple) / bounded-iteration (iterative/planned) latency budget.

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import (
    load_context, classify_query, plan_steps, generate_code, execute_code,
    check_result, advance_plan, compose_answer, handle_error, finalize,
)
from graph.edges import (
    after_load_context, after_classify, after_generate_code,
    after_execute_code, after_check_result, after_advance_plan, after_compose_answer,
)

def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    for name, fn in [
        ("load_context", load_context), ("classify_query", classify_query),
        ("plan_steps", plan_steps), ("generate_code", generate_code),
        ("execute_code", execute_code), ("check_result", check_result),
        ("advance_plan", advance_plan), ("compose_answer", compose_answer),
        ("handle_error", handle_error), ("finalize", finalize),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("load_context")
    g.add_conditional_edges("load_context", after_load_context,
        {"classify_query": "classify_query", "handle_error": "handle_error"})
    g.add_conditional_edges("classify_query", after_classify,
        {"plan_steps": "plan_steps", "generate_code": "generate_code"})
    g.add_edge("plan_steps", "generate_code")
    g.add_conditional_edges("generate_code", after_generate_code,
        {"execute_code": "execute_code", "handle_error": "handle_error"})
    g.add_conditional_edges("execute_code", after_execute_code,
        {"compose_answer": "compose_answer", "check_result": "check_result", "handle_error": "handle_error"})
    g.add_conditional_edges("check_result", after_check_result,
        {"generate_code": "generate_code", "advance_plan": "advance_plan", "compose_answer": "compose_answer"})
    g.add_conditional_edges("advance_plan", after_advance_plan,
        {"generate_code": "generate_code", "compose_answer": "compose_answer"})
    g.add_conditional_edges("compose_answer", after_compose_answer,
        {"finalize": "finalize", "handle_error": "handle_error"})
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()
```
