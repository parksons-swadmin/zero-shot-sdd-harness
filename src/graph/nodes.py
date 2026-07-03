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

from db.models import AuditLogEntry, CostRecord, Dataset, DatasetProfile, Message, QueryResult
from db.session import create_db_session
from config.settings import get_settings
from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger

logger = get_logger("graph")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_GENERATE_CODE_PROMPT_PATH = _PROMPTS_DIR / "generate_code.md"
_COMPOSE_ANSWER_PROMPT_PATH = _PROMPTS_DIR / "compose_answer.md"

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


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

def classify_query(state: AgentState) -> AgentState:
    # Phase 1: hardcoded to "simple" per spec/agent.md's documented phasing.
    # Phase 2+ replaces this body with a real gemini-2.5-flash routing call
    # producing {"mode": "simple"|"iterative"|"planned"}; the function
    # signature/state contract is already shaped for that swap.
    _log_node("classify_query", run_id=state.get("run_id"), duration_ms=0, status="ok", reasoning_mode="simple")
    return {**state, "reasoning_mode": "simple"}


# --------------------------------------------------------------------------- #
# plan_steps (Phase 2+ stub — unreachable in Phase 1)
# --------------------------------------------------------------------------- #

def plan_steps(state: AgentState) -> AgentState:
    """Phase 2+ — unreachable in Phase 1 since classify_query never returns "planned"."""
    return state


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

        accumulated = list(state.get("accumulated_summaries") or [])
        accumulated.append(result)
        _log_node("execute_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok", step_count=step_count)
        return {**state, "execution_result": result, "accumulated_summaries": accumulated, "step_count": step_count}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_node("execute_code", run_id=state.get("run_id"), duration_ms=duration_ms, status="error",
                  step_count=step_count, error=str(exc))
        return {**state, "error": str(exc), "step_count": step_count}


# --------------------------------------------------------------------------- #
# check_result / advance_plan (Phase 2+ stubs — unreachable in Phase 1)
# --------------------------------------------------------------------------- #

def check_result(state: AgentState) -> AgentState:
    """Phase 2+ — unreachable in Phase 1 (the simple path skips check_result entirely)."""
    return {**state, "check_decision": "accept"}


def advance_plan(state: AgentState) -> AgentState:
    """Phase 2+ — unreachable in Phase 1."""
    return state


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

        answer_text = text.strip()
        key_numbers = _extract_key_numbers(answer_text)

        duration_ms = int((time.monotonic() - start) * 1000)
        _log_llm_call("compose_answer", model=model, prompt_chars=len(prompt), duration_ms=duration_ms, status="ok",
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
        _log_node("compose_answer", run_id=state.get("run_id"), duration_ms=duration_ms, status="ok")
        return {**state, "answer_text": answer_text, "key_numbers": key_numbers, "cost_records": cost_records}
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


def finalize(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    question = state.get("question", "")
    answer_text = state.get("answer_text", "")
    reasoning_mode = state.get("reasoning_mode") or "simple"
    generated_code = state.get("generated_code", "")
    key_numbers = state.get("key_numbers") or []
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
            table_json=None,
            chart_spec_json=None,
            export_dataset_id=None,
            generated_code=generated_code,
            follow_up_questions_json=None,
            anomaly_flags_json=None,
            step_count=step_count,
            status=status,
        )
        session.add(query_result)
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
                                   detail_json={"status": status}))

        message_id = assistant_message.id
        query_result_id = query_result.id

    _log_node("finalize", run_id=state.get("run_id"), duration_ms=0, status=status, step_count=step_count)
    return {**state, "status": status, "message_id": message_id, "query_result_id": query_result_id}
