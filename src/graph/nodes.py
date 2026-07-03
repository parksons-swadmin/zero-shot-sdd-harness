"""Phase-1 graph nodes for the conversational-analysis capability.

Raw-data-boundary discipline (see spec/architecture.md): every value fed into
`LLMClient.call_model_with_usage` here is built exclusively from `profiles`
(DatasetProfile aggregates, loaded by `load_context`) and
`accumulated_summaries` (capped ExecutionResult objects produced by
`execution/sandbox.py`) — never from a live pandas DataFrame or raw file
content. There is no code path in this module that reads a CSV/parquet file
into a string destined for a prompt.
"""
import json
import re
import time
from pathlib import Path

import pandas as pd

from db.models import (
    AuditLogEntry, CleaningReport, CostRecord, Dataset, DatasetProfile, Message, QueryResult,
)
from db.session import create_db_session
from config.settings import get_settings
from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_GENERATE_CODE_PROMPT_PATH = _PROMPTS_DIR / "generate_code.md"
_COMPOSE_ANSWER_PROMPT_PATH = _PROMPTS_DIR / "compose_answer.md"
_CLASSIFY_QUERY_PROMPT_PATH = _PROMPTS_DIR / "classify_query.md"
_PLAN_STEPS_PROMPT_PATH = _PROMPTS_DIR / "plan_steps.md"
_CHECK_RESULT_PROMPT_PATH = _PROMPTS_DIR / "check_result.md"

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")

_FOLLOW_UPS_MARKER = "---FOLLOW-UPS---"
_ARTIFACTS_MARKER = "---ARTIFACTS---"
_ANOMALIES_MARKER = "---ANOMALIES---"
_VALID_MODES = ("simple", "iterative", "planned")
_VALID_CHART_TYPES = ("bar", "line", "pie")
_VALID_SEVERITIES = ("info", "warning", "critical")


def _parse_json_object(text: str) -> dict | list:
    """Parse a JSON object/array from an LLM response, tolerating code fences
    and surrounding prose. Raises ValueError if nothing parseable is found."""
    cleaned = text.strip()
    fence = _CODE_BLOCK_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} or [...] span in the text.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
    raise ValueError("No JSON payload found in LLM response")


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _log_node(name: str, *, run_id: str | None, duration_ms: int, status: str, **extra) -> None:
    logger.info("node_transition", node=name, run_id=run_id, duration_ms=duration_ms, status=status, **extra)


def _log_llm_call(node: str, *, model: str, prompt_chars: int, duration_ms: int, status: str, **extra) -> None:
    logger.info("llm_call", node=node, model=model, prompt_chars=prompt_chars, duration_ms=duration_ms, status=status, **extra)


def _extract_code(text: str) -> str:
    match = _CODE_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_key_numbers(text: str) -> list[dict]:
    matches = _BOLD_RE.findall(text)
    return [{"label": f"value_{i + 1}", "value": m} for i, m in enumerate(matches[:10])]


def _dataframe_var_name(index: int) -> str:
    return "df" if index == 0 else f"df{index + 1}"


def _load_dataframe(dataset: Dataset) -> pd.DataFrame:
    path = dataset.cleaned_path or dataset.original_path
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    return pd.read_csv(path)


# --------------------------------------------------------------------------- #
# load_context
# --------------------------------------------------------------------------- #

def load_context(state: AgentState) -> AgentState:
    start = time.monotonic()
    try:
        dataset_ids = state.get("dataset_ids") or []
        if not dataset_ids:
            raise ValueError("No datasets are in scope for this session")

        profiles: list[dict] = []
        with create_db_session() as session:
            for idx, dataset_id in enumerate(dataset_ids):
                profile_row = (
                    session.query(DatasetProfile)
                    .filter(DatasetProfile.dataset_id == dataset_id)
                    .first()
                )
                if profile_row is None:
                    raise ValueError(f"No profile found for dataset {dataset_id}")
                profiles.append({
                    "dataset_id": dataset_id,
                    "var_name": _dataframe_var_name(idx),
                    "columns": profile_row.columns_json.get("columns", profile_row.columns_json)
                    if isinstance(profile_row.columns_json, dict) else profile_row.columns_json,
                })

        # Phase 1 has no multi-turn memory by explicit deferral (spec/agent.md ->
        # Memory & Context): each session is a single question, so history is
        # always empty here even though the field is wired for Phase 2+.
        conversation_history: list[dict] = []

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_node("load_context", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok", dataset_count=len(dataset_ids))
        return {**state, "profiles": profiles, "conversation_history": conversation_history}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_node("load_context", run_id=state.get("run_id"), duration_ms=duration_ms, status="error", error=str(exc))
        return {**state, "error": str(exc)}


# --------------------------------------------------------------------------- #
# classify_query
# --------------------------------------------------------------------------- #

def _classify_query_prompt(question: str, profiles: list[dict]) -> str:
    column_names: list[str] = []
    for profile in profiles or []:
        for col in profile.get("columns") or []:
            name = col.get("name")
            if name:
                column_names.append(name)
    lines = [f"## Question\n{question}"]
    lines.append(f"\n## Column names\n{', '.join(column_names) if column_names else '(none provided)'}")
    return "\n".join(lines)


def classify_query(state: AgentState) -> AgentState:
    """Route the question to a reasoning mode via the cheap/fast router model.

    On ANY LLM/parse error we fall back to "simple" — a router hiccup must
    never block the answer. The router call is logged distinctly (node=
    "classify_query", with its model) so it's visibly separate from the
    generate/compose calls in stdout logs.
    """
    start = time.monotonic()
    settings = get_settings()
    router_model = settings.llm_router_model or "gemini-2.5-flash"
    cost_records = list(state.get("cost_records") or [])
    mode = "simple"
    model = router_model
    try:
        system = _load_prompt(_CLASSIFY_QUERY_PROMPT_PATH)
        prompt = _classify_query_prompt(state.get("question", ""), state.get("profiles") or [])
        text, usage = LLMClient().call_model_with_usage(prompt, system=system, model=router_model)
        model = usage.get("model", router_model)
        parsed = _parse_json_object(text)
        candidate = (parsed.get("mode") if isinstance(parsed, dict) else None)
        if candidate in _VALID_MODES:
            mode = candidate
        cost_records.append({
            "provider": "gemini", "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
        })
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("classify_query", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("classify_query", model=model, prompt_chars=0, duration_ms=duration_ms, status="error",
                      error=str(exc))
        mode = "simple"  # router hiccup must never block the answer

    _log_node("classify_query", run_id=state.get("run_id"), duration_ms=int((time.monotonic() - start) * 1000),
              status="ok", reasoning_mode=mode, model=model)
    return {**state, "reasoning_mode": mode, "cost_records": cost_records}


# --------------------------------------------------------------------------- #
# plan_steps (Phase 2+ stub — unreachable in Phase 1)
# --------------------------------------------------------------------------- #

def _plan_steps_prompt(question: str, profiles: list[dict]) -> str:
    return _classify_query_prompt(question, profiles)


def plan_steps(state: AgentState) -> AgentState:
    """Decompose a multi-part question into an ordered list of sub-questions
    (default model). Only reached on the "planned" path. Caps to
    settings.max_plan_steps and initialises current_step_index=0."""
    start = time.monotonic()
    settings = get_settings()
    cost_records = list(state.get("cost_records") or [])
    steps: list[str] = []
    model = ""
    try:
        system = _load_prompt(_PLAN_STEPS_PROMPT_PATH)
        prompt = _plan_steps_prompt(state.get("question", ""), state.get("profiles") or [])
        text, usage = LLMClient().call_model_with_usage(prompt, system=system)
        model = usage.get("model", "")
        parsed = _parse_json_object(text)
        if isinstance(parsed, list):
            steps = [str(s) for s in parsed if str(s).strip()]
        steps = steps[:settings.max_plan_steps]
        cost_records.append({
            "provider": "gemini", "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
        })
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("plan_steps", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("plan_steps", model=model, prompt_chars=0, duration_ms=duration_ms, status="error", error=str(exc))
        # A planning hiccup degrades to answering the whole question in one step.
        steps = [state.get("question", "")] if state.get("question") else []

    _log_node("plan_steps", run_id=state.get("run_id"), duration_ms=int((time.monotonic() - start) * 1000),
              status="ok", plan_step_count=len(steps))
    return {**state, "plan_steps": steps, "current_step_index": 0, "cost_records": cost_records}


# --------------------------------------------------------------------------- #
# generate_code
# --------------------------------------------------------------------------- #

def _format_column(col: dict) -> str:
    top_values = col.get("top_values")
    top_str = f", top_values={top_values}" if top_values else ""
    return (
        f"- {col.get('name')} ({col.get('dtype')}): null_count={col.get('null_count')}, "
        f"distinct_count={col.get('distinct_count')}, min={col.get('min')}, max={col.get('max')}, "
        f"mean={col.get('mean')}, median={col.get('median')}{top_str}"
    )


def _build_generate_code_prompt(
    profiles: list[dict], question: str, accumulated_summaries: list[dict], check_feedback: str | None,
) -> str:
    lines = ["## Available dataframes (variable name -> aggregate profile; NOT raw rows)"]
    for profile in profiles:
        lines.append(f"\n### {profile['var_name']} (dataset_id={profile['dataset_id']})")
        for col in profile.get("columns") or []:
            lines.append(_format_column(col))

    if accumulated_summaries:
        lines.append("\n## Prior step results (structured summaries, not raw rows)")
        lines.append(json.dumps(accumulated_summaries, default=str))

    if check_feedback:
        lines.append(f"\n## Feedback on the previous attempt\n{check_feedback}")

    lines.append(f"\n## Question\n{question}")
    return "\n".join(lines)


def generate_code(state: AgentState) -> AgentState:
    start = time.monotonic()
    model = ""
    try:
        system = _load_prompt(_GENERATE_CODE_PROMPT_PATH)
        prompt = _build_generate_code_prompt(
            state.get("profiles") or [],
            state.get("question", ""),
            state.get("accumulated_summaries") or [],
            state.get("check_feedback"),
        )
        text, usage = LLMClient().call_model_with_usage(prompt, system=system)
        model = usage.get("model", "")
        code = _extract_code(text)

        cost_records = list(state.get("cost_records") or [])
        cost_records.append({
            "provider": "gemini", "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
        })

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("generate_code", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
        _log_node("generate_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok")
        return {**state, "generated_code": code, "cost_records": cost_records}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("generate_code", model=model, prompt_chars=0, duration_ms=duration_ms, status="error", error=str(exc))
        return {**state, "error": str(exc)}


# --------------------------------------------------------------------------- #
# execute_code
# --------------------------------------------------------------------------- #

def execute_code(state: AgentState) -> AgentState:
    from execution.sandbox import run_analysis_code

    start = time.monotonic()
    step_count = int(state.get("step_count") or 0) + 1
    try:
        dataset_ids = state.get("dataset_ids") or []
        dataframes: dict[str, pd.DataFrame] = {}
        with create_db_session() as session:
            for idx, dataset_id in enumerate(dataset_ids):
                dataset = session.get(Dataset, dataset_id)
                if dataset is None:
                    raise ValueError(f"Dataset {dataset_id} not found")
                dataframes[_dataframe_var_name(idx)] = _load_dataframe(dataset)

        settings = get_settings()
        result = run_analysis_code(state.get("generated_code", ""), dataframes, timeout_s=settings.sandbox_timeout_s)

        duration_ms = int((time.monotonic() - start) * 1000)
        if not result.get("ok"):
            _log_node("execute_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="error",
                      step_count=step_count, error=result.get("error"))
            return {**state, "error": result.get("error"), "step_count": step_count, "execution_result": result}

        # An `export` block (full-derived-DataFrame metadata written by the
        # sandbox) is pulled out of the result and captured in state for
        # finalize's promotion step. It is STRIPPED before the result is
        # appended to accumulated_summaries so the export temp path / metadata
        # can never reach a later LLM prompt (generate_code / check_result /
        # compose_answer all read accumulated_summaries).
        export_meta = result.pop("export", None) if isinstance(result, dict) else None

        accumulated = list(state.get("accumulated_summaries") or [])
        accumulated.append(result)
        _log_node("execute_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok", step_count=step_count)
        new_state = {**state, "execution_result": result, "accumulated_summaries": accumulated, "step_count": step_count}
        if export_meta is not None:
            new_state["export_meta"] = export_meta
        return new_state
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_node("execute_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="error",
                  step_count=step_count, error=str(exc))
        return {**state, "error": str(exc), "step_count": step_count}


# --------------------------------------------------------------------------- #
# check_result / advance_plan (Phase 2+ stubs — unreachable in Phase 1)
# --------------------------------------------------------------------------- #

def _current_question(state: AgentState) -> str:
    plan = state.get("plan_steps") or []
    idx = int(state.get("current_step_index") or 0)
    if plan and 0 <= idx < len(plan):
        return plan[idx]
    return state.get("question", "")


def _build_check_result_prompt(question: str, execution_result: dict | None, error: str | None) -> str:
    lines = [f"## Current question\n{question}"]
    if error:
        lines.append(f"\n## Execution error\n{error}")
    lines.append("\n## Structured result (aggregate/capped, never raw rows)")
    lines.append(json.dumps(execution_result, default=str))
    return "\n".join(lines)


def check_result(state: AgentState) -> AgentState:
    """Judge whether execution_result answers the current question. Writes
    check_decision/check_feedback and increments iteration_count on refine.

    Self-forces "accept" when iteration_count >= max_iterations OR
    step_count >= max_total_steps so the loop is always bounded (edges.py
    also enforces the caps, but the stored decision must be correct). On any
    parse/LLM error we default to "accept" so a checker hiccup ends the loop
    gracefully rather than hanging.
    """
    start = time.monotonic()
    settings = get_settings()
    iteration_count = int(state.get("iteration_count") or 0)
    step_count = int(state.get("step_count") or 0)
    cost_records = list(state.get("cost_records") or [])

    if iteration_count >= settings.max_iterations or step_count >= settings.max_total_steps:
        _log_node("check_result", run_id=state.get("run_id"), duration_ms=0, status="ok",
                  check_decision="accept", forced_by_cap=True)
        return {**state, "check_decision": "accept", "check_feedback": None, "cost_records": cost_records}

    decision = "accept"
    feedback: str | None = None
    model = ""
    try:
        system = _load_prompt(_CHECK_RESULT_PROMPT_PATH)
        prompt = _build_check_result_prompt(
            _current_question(state), state.get("execution_result"), state.get("error"),
        )
        text, usage = LLMClient().call_model_with_usage(prompt, system=system)
        model = usage.get("model", "")
        parsed = _parse_json_object(text)
        if isinstance(parsed, dict) and parsed.get("decision") in ("accept", "refine"):
            decision = parsed["decision"]
            feedback = parsed.get("feedback") or None
        cost_records.append({
            "provider": "gemini", "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
        })
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("check_result", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("check_result", model=model, prompt_chars=0, duration_ms=duration_ms, status="error",
                      error=str(exc))
        decision = "accept"  # checker hiccup ends the loop gracefully

    new_state = {**state, "check_decision": decision, "check_feedback": feedback, "cost_records": cost_records}
    if decision == "refine":
        new_state["iteration_count"] = iteration_count + 1
        # A refine on an errored execution clears the error so the retry runs.
        new_state["error"] = None

    _log_node("check_result", run_id=state.get("run_id"), duration_ms=int((time.monotonic() - start) * 1000),
              status="ok", check_decision=decision, iteration_count=int(new_state.get("iteration_count") or 0))
    return new_state


def advance_plan(state: AgentState) -> AgentState:
    """Advance to the next planned sub-question. Non-LLM; edges.py's
    after_advance_plan reads the incremented current_step_index."""
    current_step_index = int(state.get("current_step_index") or 0) + 1
    # Reset the per-step refine counter and stale check feedback for the new step.
    _log_node("advance_plan", run_id=state.get("run_id"), duration_ms=0, status="ok",
              current_step_index=current_step_index)
    return {**state, "current_step_index": current_step_index, "iteration_count": 0, "check_feedback": None}


# --------------------------------------------------------------------------- #
# compose_answer
# --------------------------------------------------------------------------- #

def _build_compose_answer_prompt(question: str, accumulated_summaries: list[dict], conversation_history: list[dict]) -> str:
    lines = [f"## Original question\n{question}"]
    lines.append("\n## Structured analysis results (aggregate/capped, never raw rows)")
    lines.append(json.dumps(accumulated_summaries, default=str))
    if conversation_history:
        lines.append("\n## Prior conversation in this session")
        for message in conversation_history:
            lines.append(f"{message.get('role')}: {message.get('content')}")
    return "\n".join(lines)


def _split_answer_and_follow_ups(text: str) -> tuple[str, list[str]]:
    """Split a compose_answer response on the literal ---FOLLOW-UPS--- marker.

    The prose BEFORE the marker is the answer; the lines after (each stripped
    of a leading "- "/"* " bullet) are the follow-up questions. If the marker
    is absent, the whole text is the answer and follow-ups is []. Robust to a
    missing marker so follow-up lines never pollute key-number extraction.
    """
    marker_index = text.find(_FOLLOW_UPS_MARKER)
    if marker_index == -1:
        return text.strip(), []
    prose = text[:marker_index].strip()
    tail = text[marker_index + len(_FOLLOW_UPS_MARKER):]
    follow_ups: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("* "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("-"):
            stripped = stripped[1:].strip()
        if stripped:
            follow_ups.append(stripped)
    return prose, follow_ups


def _split_prose_follow_ups_artifacts(text: str) -> tuple[str, list[str], dict | None]:
    """Split a compose_answer response into (prose, follow_ups, artifact_intent).

    Generalises `_split_answer_and_follow_ups` to a THIRD trailing section:
    the model emits the answer prose, then a `---FOLLOW-UPS---` block, then a
    `---ARTIFACTS---` block containing a single strict-JSON object describing
    chart/table *intent only* (never data values). Sections appear in that
    fixed order. The prose/follow-ups split is delegated to the existing helper
    (its behaviour and callers are preserved) so key-number extraction still
    runs against the prose alone.

    - If `---ARTIFACTS---` is absent, artifact_intent is None (prose/follow-ups
      unchanged — backward compatible with the Phase-2 format).
    - If the artifact JSON is unparseable, artifact_intent is None rather than
      failing the run.
    """
    artifacts_index = text.find(_ARTIFACTS_MARKER)
    if artifacts_index == -1:
        prose, follow_ups = _split_answer_and_follow_ups(text)
        return prose, follow_ups, None

    head = text[:artifacts_index]
    tail = text[artifacts_index + len(_ARTIFACTS_MARKER):].strip()
    prose, follow_ups = _split_answer_and_follow_ups(head)

    artifact_intent: dict | None = None
    if tail:
        try:
            parsed = _parse_json_object(tail)
            if isinstance(parsed, dict):
                artifact_intent = parsed
        except (ValueError, json.JSONDecodeError):
            artifact_intent = None
    return prose, follow_ups, artifact_intent


def _coerce_anomaly(entry: object) -> dict | None:
    """Coerce one LLM-emitted anomaly object to the canonical
    `{type, column, severity, message}` shape, or None if malformed.

    `type` and `message` are required non-empty strings; `column` is an
    optional string (None allowed); `severity` is normalised to one of
    info|warning|critical, defaulting to "info". Raw row values never live
    here — this only reshapes the model's structural intent.
    """
    if not isinstance(entry, dict):
        return None
    a_type = entry.get("type")
    message = entry.get("message")
    if not isinstance(a_type, str) or not a_type.strip():
        return None
    if not isinstance(message, str) or not message.strip():
        return None
    column = entry.get("column")
    if column is not None and not isinstance(column, str):
        column = str(column)
    severity = entry.get("severity")
    if not isinstance(severity, str) or severity.lower() not in _VALID_SEVERITIES:
        severity = "info"
    else:
        severity = severity.lower()
    return {"type": a_type.strip(), "column": column, "severity": severity, "message": message.strip()}


def _split_answer_sections(text: str) -> tuple[str, list[str], dict | None, list[dict]]:
    """Split a compose_answer response into
    (prose, follow_ups, artifact_intent, anomaly_flags).

    Adds a FOURTH trailing section after `---ARTIFACTS---`: a `---ANOMALIES---`
    block holding a strict-JSON *array* of `{type, column, severity, message}`
    objects describing data-quality issues the model inferred from the
    aggregate profile / structured results (never from raw rows). Because this
    marker sits strictly after all prior markers, the prose boundary is
    unchanged from Phase 3a and `_extract_key_numbers` still runs on prose only.

    - If `---ANOMALIES---` is absent, anomaly_flags is [] and the head is split
      exactly as in Phase 3a (backward compatible).
    - If the anomaly JSON is unparseable, anomaly_flags is [] rather than
      failing the run; malformed individual entries are dropped.
    """
    anomalies_index = text.find(_ANOMALIES_MARKER)
    if anomalies_index == -1:
        prose, follow_ups, artifact_intent = _split_prose_follow_ups_artifacts(text)
        return prose, follow_ups, artifact_intent, []

    head = text[:anomalies_index]
    tail = text[anomalies_index + len(_ANOMALIES_MARKER):].strip()
    prose, follow_ups, artifact_intent = _split_prose_follow_ups_artifacts(head)

    anomaly_flags: list[dict] = []
    if tail:
        try:
            parsed = _parse_json_object(tail)
        except (ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, list):
            for entry in parsed:
                coerced = _coerce_anomaly(entry)
                if coerced is not None:
                    anomaly_flags.append(coerced)
    return prose, follow_ups, artifact_intent, anomaly_flags


def _profile_anomalies(profiles: list[dict] | None) -> list[dict]:
    """Deterministically derive data-quality flags from DatasetProfile
    aggregates already in state — NO LLM call, and NO raw rows.

    Reads only the per-column aggregate fields (`distinct_count`, `null_count`)
    loaded by `load_context`. Conservative v1 rules:
      - distinct_count <= 1  -> constant_column (warning): degenerate/all-same
        or all-null column.
      - null_count > 0       -> null_values (info): the column has missing data.
    Guarantees a non-flaky signal whenever a genuinely degenerate column is in
    scope, so the anomaly output never depends on model behaviour alone.
    """
    flags: list[dict] = []
    for profile in profiles or []:
        for col in profile.get("columns") or []:
            name = col.get("name")
            if not name:
                continue
            distinct_count = col.get("distinct_count")
            null_count = col.get("null_count")
            if isinstance(distinct_count, int) and distinct_count <= 1:
                flags.append({
                    "type": "constant_column",
                    "column": name,
                    "severity": "warning",
                    "message": f"{name} has the same value in every row.",
                })
            if isinstance(null_count, int) and null_count > 0:
                flags.append({
                    "type": "null_values",
                    "column": name,
                    "severity": "info",
                    "message": f"{name} has missing values.",
                })
    return flags


def _merge_anomalies(llm_flags: list[dict], profile_flags: list[dict]) -> list[dict]:
    """Merge LLM-emitted and deterministic profile flags, deduped by
    (type, column). Deterministic (profile) entries win on conflict."""
    merged: dict[tuple, dict] = {}
    for flag in llm_flags:
        merged[(flag.get("type"), flag.get("column"))] = flag
    for flag in profile_flags:  # deterministic entries overwrite on conflict
        merged[(flag.get("type"), flag.get("column"))] = flag
    return list(merged.values())


def _result_records(execution_result: dict | None) -> tuple[list[dict], dict] | None:
    """Return (records, meta) parsed from the capped ExecutionResult's
    `result.data_json`, or None when the result is a scalar / non-tabular /
    unparseable. `records` is always a list of {column: value} dicts, built
    ONLY from the already-capped `data_json` (never a live DataFrame).

    A Series is normalised to two columns ("key"/"value") so tables and charts
    have a uniform shape. `meta` carries total_rows/rows_returned/truncated.
    """
    if not isinstance(execution_result, dict):
        return None
    result = execution_result.get("result")
    if not isinstance(result, dict):
        return None
    rtype = result.get("type")
    if rtype not in ("dataframe", "series"):
        return None

    data_json = result.get("data_json")
    if not isinstance(data_json, str) or not data_json:
        return None
    try:
        parsed = json.loads(data_json)
    except json.JSONDecodeError:
        # data_json may have been hard-truncated by the cell cap into invalid
        # JSON — degrade to no artifact rather than raising.
        return None

    meta = {
        "total_rows": result.get("total_rows"),
        "rows_returned": result.get("rows_returned"),
        "truncated": bool(result.get("truncated")),
    }

    if rtype == "series":
        if not isinstance(parsed, dict):
            return None
        records = [{"key": k, "value": v} for k, v in parsed.items()]
        return records, meta

    # dataframe
    if not isinstance(parsed, list):
        return None
    records = [r for r in parsed if isinstance(r, dict)]
    return records, meta


def _build_table_data(execution_result: dict | None) -> dict | None:
    """Assemble a table (columns + rows) deterministically from the capped
    ExecutionResult ONLY. Returns None for a scalar / non-tabular result.

    Never reads a live DataFrame — rows come solely from `result.data_json`,
    already capped by the sandbox to RESULT_ROW_CAP/RESULT_CELL_CAP.
    """
    parsed = _result_records(execution_result)
    if parsed is None:
        return None
    records, meta = parsed
    if not records:
        return None

    columns: list[str] = []
    for record in records:
        for key in record.keys():
            if key not in columns:
                columns.append(key)

    rows = [[record.get(col) for col in columns] for record in records]
    return {
        "columns": columns,
        "rows": rows,
        "truncated": meta["truncated"],
        "total_rows": meta["total_rows"],
        "rows_returned": meta["rows_returned"],
    }


def _build_chart_spec(execution_result: dict | None, chart_intent: dict | None) -> dict | None:
    """Assemble a chart spec deterministically from the capped ExecutionResult
    ONLY, honouring the LLM's chart *intent* (type + x/y column mapping +
    titles) but never its data. Series is further capped to
    `settings.chart_max_points`. Returns None for a scalar / non-tabular result
    or when the intent explicitly disables the chart.
    """
    if not isinstance(chart_intent, dict):
        return None
    if chart_intent.get("chart") is False:
        return None

    parsed = _result_records(execution_result)
    if parsed is None:
        return None
    records, _meta = parsed
    if not records:
        return None

    available = list(records[0].keys())
    x_col = chart_intent.get("x") if chart_intent.get("x") in available else None
    y_col = chart_intent.get("y") if chart_intent.get("y") in available else None
    if x_col is None:
        x_col = available[0]
    if y_col is None:
        # Prefer the first column that is not the x column.
        y_candidates = [c for c in available if c != x_col]
        y_col = y_candidates[0] if y_candidates else x_col

    chart_type = chart_intent.get("type")
    if chart_type not in _VALID_CHART_TYPES:
        chart_type = "bar"

    max_points = get_settings().chart_max_points
    series = [{"x": r.get(x_col), "y": r.get(y_col)} for r in records[:max_points]]

    return {
        "type": chart_type,
        "x_key": x_col,
        "y_key": y_col,
        "x_label": chart_intent.get("x_label") or x_col,
        "y_label": chart_intent.get("y_label") or y_col,
        "title": chart_intent.get("title"),
        "series": series,
    }


def compose_answer(state: AgentState) -> AgentState:
    start = time.monotonic()
    model = ""
    try:
        system = _load_prompt(_COMPOSE_ANSWER_PROMPT_PATH)
        prompt = _build_compose_answer_prompt(
            state.get("question", ""), state.get("accumulated_summaries") or [], state.get("conversation_history") or [],
        )
        text, usage = LLMClient().call_model_with_usage(prompt, system=system)
        model = usage.get("model", "")

        cost_records = list(state.get("cost_records") or [])
        cost_records.append({
            "provider": "gemini", "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
        })

        answer_text, follow_up_questions, artifact_intent, llm_anomalies = _split_answer_sections(text)
        # Key numbers are extracted from the answer prose ONLY, never the
        # follow-up questions (which may contain bolded text of their own).
        key_numbers = _extract_key_numbers(answer_text)

        # Merge the LLM-emitted anomalies with a deterministic profile-based
        # check (dedup by (type, column); deterministic entries win). The
        # deterministic check reads only aggregate profile fields — no raw rows,
        # no extra LLM call — so a genuinely degenerate column is always flagged.
        anomaly_flags = _merge_anomalies(llm_anomalies, _profile_anomalies(state.get("profiles")))

        # Table/chart are assembled deterministically from the already-capped
        # ExecutionResult — the LLM contributes only chart *intent*, never data.
        execution_result = state.get("execution_result")
        table_data = _build_table_data(execution_result)
        chart_intent: dict | None = None
        if isinstance(artifact_intent, dict):
            if artifact_intent.get("table") is False:
                table_data = None
            raw_chart = artifact_intent.get("chart")
            if isinstance(raw_chart, dict):
                chart_intent = raw_chart
            elif "type" in artifact_intent or "x" in artifact_intent:
                # Tolerate a flat intent object (type/x/y at top level).
                chart_intent = artifact_intent
        chart_spec = _build_chart_spec(execution_result, chart_intent)

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("compose_answer", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
        _log_node("compose_answer", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok",
                  follow_up_count=len(follow_up_questions), has_table=table_data is not None,
                  has_chart=chart_spec is not None, anomaly_count=len(anomaly_flags))
        return {**state, "answer_text": answer_text, "key_numbers": key_numbers,
                "follow_up_questions": follow_up_questions, "table_data": table_data,
                "chart_spec": chart_spec, "anomaly_flags": anomaly_flags, "cost_records": cost_records}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("compose_answer", model=model, prompt_chars=0, duration_ms=duration_ms, status="error", error=str(exc))
        return {**state, "error": str(exc)}


# --------------------------------------------------------------------------- #
# handle_error
# --------------------------------------------------------------------------- #

_RATE_LIMIT_MARKERS = ("429", "rate limit", "rate-limit", "quota", "resource_exhausted")


def _sanitize_error(raw_error: str) -> str:
    """Maps a raw provider/internal exception string to a generic, readable
    user-facing message. The raw text (which may contain a full provider
    error body, stack-trace fragment, or internal detail) must never reach
    the end user — it is only ever written to the structured `structlog`
    line and the `AuditLogEntry.detail_json` for the `error` event, both of
    which happen before this function's return value replaces `state["error"]`.
    """
    lowered = raw_error.lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return "The AI provider is temporarily rate-limited — please try again shortly."
    if "timeout" in lowered or "timed out" in lowered:
        return "The analysis took too long and was stopped. Please try a simpler question or try again."
    if "safety guard" in lowered or "unsafe" in lowered:
        return "The generated analysis code was rejected by the safety guard. Please try rephrasing your question."
    return "The analysis failed due to an unexpected error. Please try again."


def handle_error(state: AgentState) -> AgentState:
    raw_error = state.get("error") or "Unknown error"
    session_id = state.get("session_id")
    try:
        with create_db_session() as session:
            session.add(AuditLogEntry(
                session_id=session_id,
                dataset_id=None,
                query_result_id=None,
                event_type="error",
                detail_json={"error": raw_error, "run_id": state.get("run_id"), "question": state.get("question")},
            ))
    except Exception as audit_exc:  # never fail silently, but never crash the graph either
        logger.info("audit_log_write_failed", node="handle_error", error=str(audit_exc))

    # Full raw detail is logged/audited above; only the sanitized message is
    # ever surfaced past this node (see spec/architecture.md's "readable
    # error, never a raw stack trace" contract in the External Dependencies
    # table, and spec/api.md's 500 error case for POST /sessions/{id}/messages).
    sanitized_error = _sanitize_error(raw_error)
    _log_node("handle_error", run_id=state.get("run_id"), duration_ms=0, status="failed", error=raw_error)
    return {**state, "status": "failed", "error": sanitized_error}


# --------------------------------------------------------------------------- #
# finalize
# --------------------------------------------------------------------------- #

def _estimate_cost(cost_record: dict) -> float:
    settings = get_settings()
    prompt_tokens = cost_record.get("prompt_tokens", 0) or 0
    completion_tokens = cost_record.get("completion_tokens", 0) or 0
    cost = (prompt_tokens / 1000) * settings.gemini_input_price_per_1k
    cost += (completion_tokens / 1000) * settings.gemini_output_price_per_1k
    return round(cost, 6)


def _promote_derived_dataset(session, query_result_id: str, export_meta: dict | None) -> str | None:
    """Promote a sandbox export (temp parquet) into a derived Dataset library
    entry, reusing the existing ingestion machinery (Dataset + DatasetProfile +
    empty CleaningReport). Returns the new Dataset id, or None when there is no
    export. The full derived rows live only on local disk (export.csv/parquet);
    only aggregate profile fields + shape counts are computed here.
    """
    if not isinstance(export_meta, dict):
        return None
    temp_path = export_meta.get("temp_path")
    if not temp_path:
        return None

    from storage import exports  # local import: avoids import cost on the hot path
    from tools.profiling import build_profile  # read-only aggregate profiler

    promoted = exports.promote_export(query_result_id, temp_path)
    csv_path = promoted["csv_path"]
    parquet_path = promoted["parquet_path"]

    df = pd.read_parquet(parquet_path)
    columns = build_profile(df)

    try:
        size_bytes = Path(csv_path).stat().st_size
    except OSError:
        size_bytes = 0

    derived = Dataset(
        filename=f"derived_{query_result_id[:8]}.csv",
        original_path=csv_path,
        cleaned_path=parquet_path,
        row_count=promoted["row_count"],
        column_count=promoted["column_count"],
        size_bytes=size_bytes,
        status="ready",
        derived_from_query_result_id=query_result_id,
    )
    session.add(derived)
    session.flush()

    session.add(DatasetProfile(dataset_id=derived.id, columns_json=columns))
    session.add(CleaningReport(dataset_id=derived.id, issues_json={"issues": []}))
    session.flush()

    return derived.id


def finalize(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    question = state.get("question", "")
    answer_text = state.get("answer_text", "")
    reasoning_mode = state.get("reasoning_mode") or "simple"
    generated_code = state.get("generated_code", "")
    key_numbers = state.get("key_numbers") or []
    follow_up_questions = state.get("follow_up_questions") or []
    table_data = state.get("table_data")
    chart_spec = state.get("chart_spec")
    export_meta = state.get("export_meta")
    step_count = int(state.get("step_count") or 0)
    settings = get_settings()

    status = "partial" if step_count >= settings.max_total_steps else "completed"

    with create_db_session() as session:
        user_message = Message(session_id=session_id, role="user", content=question)
        session.add(user_message)
        session.flush()

        assistant_message = Message(session_id=session_id, role="assistant", content=answer_text)
        session.add(assistant_message)
        session.flush()

        query_result = QueryResult(
            message_id=assistant_message.id,
            session_id=session_id,
            reasoning_mode=reasoning_mode,
            summary_text=answer_text,
            key_numbers_json=key_numbers,
            table_json=table_data,
            chart_spec_json=chart_spec,
            export_dataset_id=None,
            generated_code=generated_code,
            follow_up_questions_json=(follow_up_questions or None),
            anomaly_flags_json=(state.get("anomaly_flags") or None),
            step_count=step_count,
            status=status,
        )
        session.add(query_result)
        session.flush()

        # Promote an export_df (if any) into a first-class derived Dataset that
        # shows up in the library and is queryable like an upload. Only
        # aggregate metadata reaches the DB/audit here — never the export rows.
        export_dataset_id = _promote_derived_dataset(session, query_result.id, export_meta)
        if export_dataset_id is not None:
            query_result.export_dataset_id = export_dataset_id
            session.flush()

        for cost_record in state.get("cost_records") or []:
            session.add(CostRecord(
                query_result_id=query_result.id,
                provider=cost_record.get("provider", "gemini"),
                model=cost_record.get("model") or "unknown",
                prompt_tokens=cost_record.get("prompt_tokens", 0),
                completion_tokens=cost_record.get("completion_tokens", 0),
                estimated_cost_usd=_estimate_cost(cost_record),
            ))

        session.add(AuditLogEntry(session_id=session_id, query_result_id=query_result.id, event_type="ask",
                                   detail_json={"question": question}))
        session.add(AuditLogEntry(session_id=session_id, query_result_id=query_result.id, event_type="code_exec",
                                   detail_json={"generated_code": generated_code, "step_count": step_count}))
        session.add(AuditLogEntry(session_id=session_id, query_result_id=query_result.id, event_type="answer",
                                   detail_json={"status": status, "export_dataset_id": export_dataset_id}))

        message_id = assistant_message.id
        query_result_id = query_result.id

    _log_node("finalize", run_id=state.get("run_id"), duration_ms=0, status=status, step_count=step_count)
    return {**state, "status": status, "message_id": message_id, "query_result_id": query_result_id}
