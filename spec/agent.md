# Agent — Deterministic No-LLM Aging Pipeline

> **This "agent" contains NO LLM and makes NO network calls.** It is a deterministic LangGraph `StateGraph` whose every node is a pure function of its inputs. The graph is kept (not replaced by a plain script) so the harness's agentic-stack gate still applies — the graph compiles, state flows through nodes, the pipeline is invocable — and because the boilerplate is already wired for it.

---

## Why no LLM

The core requirement is **exact, auditable arithmetic over structured data**: every rupee must tie out to the source Excel bit-for-bit. An LLM introduces non-determinism, hallucination risk, rounding drift, and would break the "every number ties out exactly" guarantee — and it would send commercially sensitive AR data off-machine, violating the "nothing leaves the machine" constraint. There is therefore **no LLM, no API key, no provider layer, no network egress**. The boilerplate's `transform_text` node, the `src/llm/` package, the Anthropic + `google-genai` dependencies, and all provider keys are **removed** (see [architecture.md](architecture.md)).

---

## Agent Architecture Pattern

**Chosen: Deterministic sequential pipeline (a linear DAG) with an error branch and a human-in-the-loop mapping checkpoint.**

From the catalogue in `harness/patterns/agentic-ai.md`, this composes:
- **#1 Prompt Chaining — structure only, no LLM.** A fixed, ordered sequence of steps, each consuming the prior step's output. Here every step is a pure deterministic function instead of an LLM call.
- **#18 Guardrails / Validation.** The `validate` node coerces and validates every field and raises data-quality flags instead of trusting input.
- **#13 Human-in-the-Loop.** The mapping-confirmation checkpoint sits between `preview` and `compute`: the user confirms/corrects the column mapping before any metric is computed. This is enforced at the API boundary (two calls), not inside the graph.
- **#12 Exception Handling & Recovery.** A `handle_error` node captures any node failure into `state.error` and terminates cleanly.
- **#19 Evaluation & Monitoring.** structlog structured events per node (see Observability). No LangSmith (no LLM).

It is explicitly **not** a ReAct loop and not multi-agent — there are no tools for a model to choose between and no reasoning to perform; the transformation is fixed and deterministic.

---

## LLM Provider & Model

**None.** No node makes an LLM call. There is no provider table, no model ID, no API key.

---

## Tools / Pure functions

Nodes call these pure helpers in `src/tools/` (no side effects, no I/O beyond reading the in-memory frame):

| Function | Module | Description | Output |
|----------|--------|-------------|--------|
| `detect_mapping(columns)` | `tools/header_detect.py` | rapidfuzz match of each source column to canonical-field synonyms | `list[FieldMatch]` |
| `read_workbook(bytes, sheet)` | `tools/ingest.py` | openpyxl/pandas read of `.xlsx` → DataFrame + sheet list | `(DataFrame, list[str])` |
| `normalize(df, mapping, as_of)` | `tools/ingest.py` | apply mapping, parse dates (`dayfirst=True`), amounts→paise, compute dpd+bucket | normalized DataFrame |
| `validate(df)` | `tools/validate.py` | raise `QualityFlag`s; never drop rows | `list[QualityFlag]` |
| `compute_metrics(df, as_of, phase)` | `tools/metrics.py` | vectorized int64 aggregation → `AgingMetrics` | `AgingMetrics` |
| `compute_risk_flags(df)` | `tools/flags.py` | rule-based riskiest accounts (Phase 2) | `list[RiskFlag]` |

`detect_mapping` and `read_workbook` are used by the `POST /api/preview` route directly (not the graph). The graph runs the compute pipeline on `POST /api/compute`.

---

## Agent State

```python
from datetime import date
from typing import TypedDict
import pandas as pd
from domain.aging import AgingMetrics
from domain.mapping import ColumnMapping
from domain.quality import QualityFlag, RiskFlag

class AnalysisState(TypedDict, total=False):
    # Identity
    run_id: str                       # uuid, set at initialisation (audit/log correlation only)

    # Input (set by the runner from the request)
    file_bytes: bytes                 # uploaded .xlsx bytes
    sheet_name: str | None            # chosen sheet (None → first)
    mapping: ColumnMapping            # confirmed column mapping
    as_of: date                       # injected reference date (date.today() in prod, fixed in tests)
    phase: int                        # which metric fields to populate (1 or 2)

    # Pipeline data (populated progressively by nodes)
    df: pd.DataFrame                  # ingest → normalized rows (canonical cols + amount_paise + dpd + bucket)
    quality_flags: list[QualityFlag]  # validate
    risk_flags: list[RiskFlag]        # flag (Phase 2)

    # Output
    metrics: AgingMetrics             # assemble → returned to the API

    # Control
    error: str | None                 # set by any node on fatal failure
```

State holds a `pandas.DataFrame` by reference (LangGraph merges shallow dict updates — no deep copy), so 60k+ rows flow through the graph with no per-node copy cost.

---

## Nodes / Steps

### `node_ingest`
- **Reads:** `file_bytes`, `sheet_name`, `mapping`, `as_of`
- **Writes:** `df`
- **LLM call:** no
- **External calls:** openpyxl `.xlsx` read (fatal on failure → `error`)
- **Behaviour:** Reads the chosen sheet, applies the confirmed `ColumnMapping` to produce the six canonical columns, parses dates (`dayfirst=True`, Excel-native, serial, ISO), converts `amount` → `amount_paise` (int), computes `dpd` and `bucket` per row. Blank customer/employee → `"(blank)"`. Never drops rows.

### `node_validate`
- **Reads:** `df`
- **Writes:** `quality_flags`
- **LLM call:** no
- **External calls:** none
- **Behaviour:** Guardrail step. Emits a `QualityFlag` for each missing/unparseable date, non-numeric/negative/zero amount, blank employee/customer — keyed by original `row_index`. Rows are **retained**, never dropped.

### `node_compute`
- **Reads:** `df`, `as_of`, `phase`
- **Writes:** `metrics`
- **LLM call:** no
- **External calls:** none
- **Behaviour:** Vectorized int64 aggregation → `AgingMetrics`: outstanding, overdue, %overdue, customer count, bucket totals, worst bucket, Top-20 by overdue (Phase 1); plus employees, per-group breakdowns, weighted-avg-DPD (Phase 2). No sampling — full frame. Exact tie-out via integer paise.

### `node_flag` (Phase 2)
- **Reads:** `df`, `quality_flags`
- **Writes:** `risk_flags`
- **LLM call:** no
- **External calls:** none
- **Behaviour:** Rule-based riskiest accounts (largest 90+ overdue). Advisory only — does not alter totals. In Phase 1 this node is a pass-through stub (`risk_flags = []`).

### `node_assemble`
- **Reads:** `metrics`, `quality_flags`, `risk_flags`
- **Writes:** `metrics` (finalized with flags attached)
- **Behaviour:** Attaches the data-quality report and risk flags to `AgingMetrics`, producing the final `DashboardResult` payload. Sets terminal success.

### `node_handle_error`
- **Reads:** `error`, `run_id`
- **Behaviour:** Logs the error with `run_id` context (no row data), leaves `error` set, terminates. The API route renders the error to the user (never re-raises as a bare HTTPException — see `harness/patterns/code.md`).

---

## Graph / Flow Topology

```
START
  │
  ▼
node_ingest ──(error)──► node_handle_error ──► END
  │
  ▼
node_validate ──(error)──► node_handle_error
  │
  ▼
node_compute ──(error)──► node_handle_error
  │
  ▼
node_flag ──(error)──► node_handle_error
  │
  ▼
node_assemble ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| node_ingest | `state.get("error")` | node_handle_error |
| node_ingest | else | node_validate |
| node_validate | `state.get("error")` | node_handle_error |
| node_validate | else | node_compute |
| node_compute | `state.get("error")` | node_handle_error |
| node_compute | else | node_flag |
| node_flag | `state.get("error")` | node_handle_error |
| node_flag | else | node_assemble |
| node_assemble | (always) | END |
| node_handle_error | (always) | END |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state (`AnalysisState`) | The DataFrame + intermediate results |
| **Across runs** | none | Stateless — nothing persists between uploads |
| **Conversation** | none | Not a chat interface |

No conversation memory is needed: the surface is a file-upload dashboard, not a chat. Each upload is fully independent. (The chat-memory checklist item does not apply — this is not a chat UI.)

---

## Human-in-the-Loop Checkpoints

| Checkpoint | What is shown | Expected user action | Default |
|------------|---------------|----------------------|---------|
| Column mapping | Six canonical fields with auto-detected columns + confidence tiers | Confirm or correct the mapping | None — compute is blocked until all six are mapped |

Enforced at the API boundary (`preview` → user confirms → `compute`), not inside the graph.

---

## Error Handling & Recovery

**Node-level:** each node wraps its body in try/except; on a fatal error it returns `{**state, "error": str(exc)}` and routing sends it to `node_handle_error`.

**Graph-level (`node_handle_error`):** logs the error with `run_id` (no row data), leaves `error` set, terminates the graph. The FastAPI route inspects `state["error"]` and returns a clean API error / renders an error state — it never re-raises a raw exception to the client.

**Resume / retry:** none — runs are cheap and stateless; the user simply re-uploads. No checkpointer.

**Partial failure:** data-quality problems are **not** failures — they are flagged and the run completes. Only structural failures (unreadable workbook, unmapped required field, oversized file) set `error` and abort.

---

## Observability

structlog structured events (already wired in `src/observability/events.py`) — the sole observability surface (no LangSmith, since there is no LLM):

| Signal | What | Where |
|--------|------|-------|
| Request | `preview`/`compute` received: filename, size, row count, sheet | stdout (JSON) |
| Per node | node name, `run_id`, row count, duration_ms | stdout (JSON) |
| Compute | totals-computed, bucket counts, flagged-row count, duration_ms | stdout (JSON) |
| Errors | node name, `run_id`, error message (no row data) | stdout (JSON) |

Logs **never** contain customer names, balances, or file contents — counts and timings only.

---

## Concurrency Model

- **Run isolation:** every request builds its own `AnalysisState`; nodes are pure functions with no shared mutable state → naturally safe under concurrent requests.
- **Parallel nodes within a run:** none — the pipeline is linear.
- **Checkpointing:** none (stateless, no DB, no resume).

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AnalysisState
from graph.nodes import (
    node_ingest, node_validate, node_compute,
    node_flag, node_assemble, node_handle_error,
)
from graph.edges import route_after

def _build_graph():
    g = StateGraph(AnalysisState)
    g.add_node("ingest", node_ingest)
    g.add_node("validate", node_validate)
    g.add_node("compute", node_compute)
    g.add_node("flag", node_flag)
    g.add_node("assemble", node_assemble)
    g.add_node("handle_error", node_handle_error)

    g.set_entry_point("ingest")
    g.add_conditional_edges("ingest",   route_after("validate"), {"validate": "validate", "handle_error": "handle_error"})
    g.add_conditional_edges("validate", route_after("compute"),  {"compute": "compute",   "handle_error": "handle_error"})
    g.add_conditional_edges("compute",  route_after("flag"),     {"flag": "flag",         "handle_error": "handle_error"})
    g.add_conditional_edges("flag",     route_after("assemble"), {"assemble": "assemble", "handle_error": "handle_error"})
    g.add_edge("assemble", END)
    g.add_edge("handle_error", END)
    return g.compile()

agentic_ai = _build_graph()
```

`route_after(next_node)` returns `"handle_error"` if `state.get("error")` else `next_node`. The runner (`src/graph/runner.py`) builds the initial `AnalysisState` from the request (no DB write — stateless), invokes `agentic_ai`, and returns `final["metrics"]` or raises the `error` for the route to render.
