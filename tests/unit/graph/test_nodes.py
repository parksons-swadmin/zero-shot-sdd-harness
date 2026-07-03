from unittest.mock import patch

from sqlalchemy.orm import Session

from db.models import AuditLogEntry, CostRecord, Dataset, DatasetProfile, Message, QueryResult, SessionRow
from graph.nodes import (
    classify_query, compose_answer, execute_code, finalize, generate_code, handle_error, load_context,
)


def _seed(db_engine, dataset_id="ds-1", session_id="sess-1") -> None:
    with Session(db_engine) as s:
        s.add(SessionRow(id=session_id))
        s.add(Dataset(id=dataset_id, filename="f.csv", original_path="/tmp/f.csv", size_bytes=1, status="ready"))
        s.add(DatasetProfile(dataset_id=dataset_id, columns_json=[
            {"name": "revenue", "dtype": "float64", "null_count": 0, "distinct_count": 3,
             "min": 1.0, "max": 3.0, "mean": 2.0, "median": 2.0, "top_values": None},
        ]))
        s.commit()


def test_load_context_loads_profiles_not_raw_rows(_isolated_db):
    _seed(_isolated_db)
    state = {"run_id": "r1", "session_id": "sess-1", "dataset_ids": ["ds-1"]}
    result = load_context(state)
    assert result.get("error") is None
    assert result["profiles"][0]["dataset_id"] == "ds-1"
    assert result["profiles"][0]["columns"][0]["name"] == "revenue"
    assert result["conversation_history"] == []


def test_load_context_populates_conversation_history_from_messages(_isolated_db):
    """load_context must load prior Message rows for the session into
    conversation_history (ordered oldest->newest), shaped as {role, content}."""
    from datetime import datetime, timedelta, timezone

    _seed(_isolated_db)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(_isolated_db) as s:
        s.add(Message(session_id="sess-1", role="user", content="what is total revenue?",
                      created_at=base))
        s.add(Message(session_id="sess-1", role="assistant", content="Total revenue is 6.",
                      created_at=base + timedelta(seconds=1)))
        # A message in a DIFFERENT session must never leak in.
        s.add(SessionRow(id="sess-2"))
        s.add(Message(session_id="sess-2", role="user", content="other-session question",
                      created_at=base + timedelta(seconds=2)))
        s.commit()

    state = {"run_id": "r1", "session_id": "sess-1", "dataset_ids": ["ds-1"]}
    result = load_context(state)

    assert result.get("error") is None
    history = result["conversation_history"]
    assert history == [
        {"role": "user", "content": "what is total revenue?"},
        {"role": "assistant", "content": "Total revenue is 6."},
    ]


def test_load_context_history_capped_to_recent_window(_isolated_db):
    """Only the most-recent N messages are kept, to bound prompt cost."""
    import config.settings as settings_module
    from datetime import datetime, timedelta, timezone

    _seed(_isolated_db)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(_isolated_db) as s:
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            # Explicit, strictly-increasing timestamps so created_at ordering is
            # unambiguous (SQLite TIMESTAMP would otherwise tie on a tight loop).
            s.add(Message(
                session_id="sess-1", role=role, content=f"msg-{i}",
                created_at=base + timedelta(seconds=i),
            ))
        s.commit()

    settings_module._settings = None
    import os
    os.environ["AGENT_CONVERSATION_HISTORY_MAX_MESSAGES"] = "5"
    try:
        settings_module._settings = None
        result = load_context({"run_id": "r1", "session_id": "sess-1", "dataset_ids": ["ds-1"]})
    finally:
        del os.environ["AGENT_CONVERSATION_HISTORY_MAX_MESSAGES"]
        settings_module._settings = None

    history = result["conversation_history"]
    assert len(history) == 5
    assert [m["content"] for m in history] == [f"msg-{i}" for i in range(15, 20)]


def test_load_context_missing_dataset_sets_error(_isolated_db):
    state = {"run_id": "r1", "session_id": "sess-1", "dataset_ids": ["nope"]}
    result = load_context(state)
    assert result.get("error")


def test_load_context_no_dataset_ids_sets_error(_isolated_db):
    state = {"run_id": "r1", "session_id": "sess-1", "dataset_ids": []}
    result = load_context(state)
    assert result.get("error")


def test_classify_query_routes_via_router_model(_isolated_db):
    def fake_call(self, prompt, *, system=None, model=None):
        return '{"mode": "simple"}', {"model": model or "gemini-2.5-flash", "prompt_tokens": 4, "completion_tokens": 1}

    with patch("llm.client.LLMClient.call_model_with_usage", fake_call):
        result = classify_query({"run_id": "r1", "question": "total?", "profiles": [], "cost_records": []})
    assert result["reasoning_mode"] == "simple"
    assert len(result["cost_records"]) == 1


def test_generate_code_prompt_excludes_raw_row_values(_isolated_db):
    """The only thing sent to the LLM must come from profiles/summaries, never raw rows."""
    captured_prompt = {}

    def fake_call(self, prompt, *, system=None):
        captured_prompt["prompt"] = prompt
        captured_prompt["system"] = system
        return "```python\nresult = df['revenue'].sum()\n```", {"model": "gemini-2.5-flash", "prompt_tokens": 10, "completion_tokens": 5}

    state = {
        "run_id": "r1",
        "question": "What is the total revenue?",
        "profiles": [{"dataset_id": "ds-1", "var_name": "df", "columns": [
            {"name": "revenue", "dtype": "float64", "null_count": 0, "distinct_count": 3,
             "min": 1.0, "max": 3.0, "mean": 2.0, "median": 2.0, "top_values": None},
        ]}],
        "accumulated_summaries": [],
        "check_feedback": None,
        "cost_records": [],
    }
    with patch("llm.client.LLMClient.call_model_with_usage", fake_call):
        result = generate_code(state)

    assert result.get("error") is None
    assert result["generated_code"] == "result = df['revenue'].sum()"
    # A raw row value that could only appear if a live DataFrame leaked into the prompt.
    assert "SENTINEL_RAW_ROW_VALUE_314159" not in captured_prompt["prompt"]
    assert "revenue" in captured_prompt["prompt"]
    assert len(result["cost_records"]) == 1
    assert result["cost_records"][0]["prompt_tokens"] == 10


def test_generate_code_sets_error_on_llm_failure(_isolated_db):
    def fake_call(self, prompt, *, system=None):
        raise RuntimeError("Gemini 500")

    state = {"run_id": "r1", "question": "q", "profiles": [], "accumulated_summaries": [], "cost_records": []}
    with patch("llm.client.LLMClient.call_model_with_usage", fake_call):
        result = generate_code(state)
    assert result.get("error") == "Gemini 500"


def test_execute_code_runs_guarded_sandbox_and_caps_result(_isolated_db, tmp_path):
    import pandas as pd

    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"revenue": [1.0, 2.0, 3.0]}).to_csv(csv_path, index=False)
    _seed(_isolated_db)
    with Session(_isolated_db) as s:
        dataset = s.get(Dataset, "ds-1")
        dataset.original_path = str(csv_path)
        s.commit()

    state = {"run_id": "r1", "dataset_ids": ["ds-1"], "generated_code": "result = df['revenue'].sum()",
             "step_count": 0, "accumulated_summaries": []}
    result = execute_code(state)
    assert result.get("error") is None
    assert result["step_count"] == 1
    assert result["execution_result"]["ok"] is True
    assert result["execution_result"]["result"]["value"] == 6.0


def test_execute_code_sandbox_error_sets_state_error(_isolated_db, tmp_path):
    import pandas as pd

    csv_path = tmp_path / "data.csv"
    pd.DataFrame({"revenue": [1.0]}).to_csv(csv_path, index=False)
    _seed(_isolated_db)
    with Session(_isolated_db) as s:
        dataset = s.get(Dataset, "ds-1")
        dataset.original_path = str(csv_path)
        s.commit()

    state = {"run_id": "r1", "dataset_ids": ["ds-1"], "generated_code": "import os\nresult = 1",
             "step_count": 0, "accumulated_summaries": []}
    result = execute_code(state)
    assert result.get("error")
    assert result["step_count"] == 1


def test_compose_answer_extracts_key_numbers(_isolated_db):
    def fake_call(self, prompt, *, system=None):
        return "The total revenue is **$6.00**.", {"model": "gemini-2.5-flash", "prompt_tokens": 3, "completion_tokens": 2}

    state = {"run_id": "r1", "question": "q", "accumulated_summaries": [], "conversation_history": [], "cost_records": []}
    with patch("llm.client.LLMClient.call_model_with_usage", fake_call):
        result = compose_answer(state)

    assert result.get("error") is None
    assert result["answer_text"] == "The total revenue is **$6.00**."
    assert result["key_numbers"] == [{"label": "value_1", "value": "$6.00"}]


def test_handle_error_writes_audit_log(_isolated_db):
    _seed(_isolated_db)
    state = {"run_id": "r1", "session_id": "sess-1", "error": "boom"}
    result = handle_error(state)
    assert result["status"] == "failed"
    with Session(_isolated_db) as s:
        entries = s.query(AuditLogEntry).filter(AuditLogEntry.event_type == "error").all()
    assert len(entries) == 1
    # Full raw detail is preserved in the audit trail...
    assert entries[0].detail_json["error"] == "boom"
    # ...but never surfaced past handle_error as the user-facing error text.
    assert result["error"] == "The analysis failed due to an unexpected error. Please try again."


def test_handle_error_sanitizes_raw_provider_exception(_isolated_db):
    _seed(_isolated_db)
    raw = '{"error": {"code": 429, "message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"}}'
    state = {"run_id": "r1", "session_id": "sess-1", "error": raw}
    result = handle_error(state)

    # The raw provider body must never leak into the sanitized state field...
    assert "RESOURCE_EXHAUSTED" not in result["error"]
    assert "429" not in result["error"]
    assert result["error"] == "The AI provider is temporarily rate-limited — please try again shortly."

    # ...but the full raw body is still captured in the audit trail.
    with Session(_isolated_db) as s:
        entries = s.query(AuditLogEntry).filter(AuditLogEntry.event_type == "error").all()
    assert entries[0].detail_json["error"] == raw


def test_finalize_persists_message_query_result_and_cost_records(_isolated_db):
    _seed(_isolated_db)
    state = {
        "run_id": "r1", "session_id": "sess-1", "question": "What is the total?",
        "answer_text": "The total is **6**.", "reasoning_mode": "simple",
        "generated_code": "result = df['revenue'].sum()", "key_numbers": [{"label": "value_1", "value": "6"}],
        "step_count": 1, "cost_records": [{"provider": "gemini", "model": "gemini-2.5-flash",
                                            "prompt_tokens": 100, "completion_tokens": 20}],
    }
    result = finalize(state)
    assert result["status"] == "completed"
    assert result["message_id"]
    assert result["query_result_id"]

    with Session(_isolated_db) as s:
        assert s.query(Message).filter(Message.session_id == "sess-1").count() == 2
        qr = s.get(QueryResult, result["query_result_id"])
        assert qr.summary_text == "The total is **6**."
        assert qr.status == "completed"
        cost_rows = s.query(CostRecord).filter(CostRecord.query_result_id == qr.id).all()
        assert len(cost_rows) == 1
        assert cost_rows[0].prompt_tokens == 100
        audit_types = {a.event_type for a in s.query(AuditLogEntry).filter(AuditLogEntry.session_id == "sess-1").all()}
        assert {"ask", "code_exec", "answer"} <= audit_types


def test_finalize_marks_partial_when_step_cap_hit(_isolated_db):
    _seed(_isolated_db)
    state = {
        "run_id": "r1", "session_id": "sess-1", "question": "q", "answer_text": "partial answer",
        "reasoning_mode": "simple", "generated_code": "result = 1", "key_numbers": [],
        "step_count": 8, "cost_records": [],
    }
    result = finalize(state)
    assert result["status"] == "partial"
