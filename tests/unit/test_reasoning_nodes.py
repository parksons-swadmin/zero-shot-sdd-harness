"""Unit tests for the Phase-2 adaptive-reasoning nodes.

The LLM is always mocked at ``LLMClient.call_model_with_usage`` — these tests
make NO network calls. The prod SQLite driver is only touched by the finalize
test (via the autouse ``_isolated_db`` fixture).
"""
from unittest.mock import patch

from sqlalchemy.orm import Session

from db.models import Dataset, DatasetProfile, QueryResult, SessionRow
from graph.nodes import (
    _split_answer_and_follow_ups,
    _extract_key_numbers,
    advance_plan,
    check_result,
    classify_query,
    finalize,
    plan_steps,
)


def _mock_llm(text, *, prompt_tokens=5, completion_tokens=3):
    def fake_call(self, prompt, *, system=None, model=None):
        return text, {"model": model or "gemini-3.1-pro",
                      "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return fake_call


# --------------------------------------------------------------------------- #
# classify_query
# --------------------------------------------------------------------------- #

def test_classify_query_parses_each_mode():
    for mode in ("simple", "iterative", "planned"):
        with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm(f'{{"mode": "{mode}"}}')):
            result = classify_query({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
        assert result["reasoning_mode"] == mode
        assert len(result["cost_records"]) == 1


def test_classify_query_falls_back_to_simple_on_bad_json():
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm("not json at all")):
        result = classify_query({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
    assert result["reasoning_mode"] == "simple"


def test_classify_query_falls_back_to_simple_on_llm_error():
    def boom(self, prompt, *, system=None, model=None):
        raise RuntimeError("router 500")

    with patch("llm.client.LLMClient.call_model_with_usage", boom):
        result = classify_query({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
    assert result["reasoning_mode"] == "simple"


def test_classify_query_ignores_invalid_mode_value():
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm('{"mode": "wizard"}')):
        result = classify_query({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
    assert result["reasoning_mode"] == "simple"


# --------------------------------------------------------------------------- #
# plan_steps
# --------------------------------------------------------------------------- #

def test_plan_steps_caps_at_max_plan_steps():
    many = '["s1", "s2", "s3", "s4", "s5", "s6", "s7"]'
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm(many)):
        result = plan_steps({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
    assert len(result["plan_steps"]) == 5  # settings.max_plan_steps default
    assert result["current_step_index"] == 0
    assert len(result["cost_records"]) == 1


def test_plan_steps_parses_ordered_list():
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm('["a", "b"]')):
        result = plan_steps({"run_id": "r1", "question": "q", "profiles": [], "cost_records": []})
    assert result["plan_steps"] == ["a", "b"]


# --------------------------------------------------------------------------- #
# check_result
# --------------------------------------------------------------------------- #

def test_check_result_parses_accept():
    with patch("llm.client.LLMClient.call_model_with_usage", _mock_llm('{"decision": "accept", "feedback": ""}')):
        result = check_result({"run_id": "r1", "execution_result": {"ok": True},
                               "iteration_count": 0, "step_count": 1, "cost_records": []})
    assert result["check_decision"] == "accept"
    assert result.get("iteration_count", 0) == 0


def test_check_result_parses_refine_and_increments_iteration():
    with patch("llm.client.LLMClient.call_model_with_usage",
               _mock_llm('{"decision": "refine", "feedback": "try grouping by month"}')):
        result = check_result({"run_id": "r1", "execution_result": {"ok": True},
                               "iteration_count": 1, "step_count": 2, "cost_records": []})
    assert result["check_decision"] == "refine"
    assert result["check_feedback"] == "try grouping by month"
    assert result["iteration_count"] == 2


def test_check_result_forces_accept_at_iteration_cap():
    # iteration_count == max_iterations (4) forces accept without any LLM call.
    def must_not_call(self, prompt, *, system=None, model=None):
        raise AssertionError("LLM should not be called when the cap is hit")

    with patch("llm.client.LLMClient.call_model_with_usage", must_not_call):
        result = check_result({"run_id": "r1", "execution_result": {"ok": True},
                               "iteration_count": 4, "step_count": 2, "cost_records": []})
    assert result["check_decision"] == "accept"


def test_check_result_forces_accept_at_total_step_cap():
    def must_not_call(self, prompt, *, system=None, model=None):
        raise AssertionError("LLM should not be called when the cap is hit")

    with patch("llm.client.LLMClient.call_model_with_usage", must_not_call):
        result = check_result({"run_id": "r1", "execution_result": {"ok": True},
                               "iteration_count": 0, "step_count": 8, "cost_records": []})
    assert result["check_decision"] == "accept"


def test_check_result_defaults_to_accept_on_error():
    def boom(self, prompt, *, system=None, model=None):
        raise RuntimeError("checker 500")

    with patch("llm.client.LLMClient.call_model_with_usage", boom):
        result = check_result({"run_id": "r1", "execution_result": {"ok": True},
                               "iteration_count": 0, "step_count": 1, "cost_records": []})
    assert result["check_decision"] == "accept"


# --------------------------------------------------------------------------- #
# advance_plan
# --------------------------------------------------------------------------- #

def test_advance_plan_increments_step_index():
    result = advance_plan({"run_id": "r1", "current_step_index": 0, "plan_steps": ["a", "b"]})
    assert result["current_step_index"] == 1
    assert result["iteration_count"] == 0


# --------------------------------------------------------------------------- #
# _split_answer_and_follow_ups
# --------------------------------------------------------------------------- #

def test_split_answer_and_follow_ups_splits_prose_and_questions():
    text = (
        "The total revenue is **$6.00**.\n"
        "---FOLLOW-UPS---\n"
        "- How does revenue break down by region?\n"
        "- Which month had the highest revenue?"
    )
    prose, follow_ups = _split_answer_and_follow_ups(text)
    assert prose == "The total revenue is **$6.00**."
    assert follow_ups == [
        "How does revenue break down by region?",
        "Which month had the highest revenue?",
    ]
    # Key numbers come from the prose only — follow-ups must not pollute them.
    assert _extract_key_numbers(prose) == [{"label": "value_1", "value": "$6.00"}]


def test_split_answer_and_follow_ups_no_marker_returns_empty():
    text = "The total revenue is **$6.00**."
    prose, follow_ups = _split_answer_and_follow_ups(text)
    assert prose == "The total revenue is **$6.00**."
    assert follow_ups == []


def test_split_does_not_let_follow_up_bold_pollute_key_numbers():
    text = (
        "The average is **42**.\n"
        "---FOLLOW-UPS---\n"
        "- What about the **median**?\n"
    )
    prose, follow_ups = _split_answer_and_follow_ups(text)
    assert _extract_key_numbers(prose) == [{"label": "value_1", "value": "42"}]
    assert follow_ups == ["What about the **median**?"]


# --------------------------------------------------------------------------- #
# finalize persists follow-up questions
# --------------------------------------------------------------------------- #

def _seed(db_engine, dataset_id="ds-1", session_id="sess-1"):
    with Session(db_engine) as s:
        s.add(SessionRow(id=session_id))
        s.add(Dataset(id=dataset_id, filename="f.csv", original_path="/tmp/f.csv", size_bytes=1, status="ready"))
        s.add(DatasetProfile(dataset_id=dataset_id, columns_json=[]))
        s.commit()


def test_finalize_persists_follow_up_questions(_isolated_db):
    _seed(_isolated_db)
    state = {
        "run_id": "r1", "session_id": "sess-1", "question": "q", "answer_text": "ans",
        "reasoning_mode": "simple", "generated_code": "result = 1", "key_numbers": [],
        "follow_up_questions": ["Next A?", "Next B?"], "step_count": 1, "cost_records": [],
    }
    result = finalize(state)
    with Session(_isolated_db) as s:
        qr = s.get(QueryResult, result["query_result_id"])
        assert qr.follow_up_questions_json == ["Next A?", "Next B?"]


def test_finalize_stores_none_when_no_follow_ups(_isolated_db):
    _seed(_isolated_db)
    state = {
        "run_id": "r1", "session_id": "sess-1", "question": "q", "answer_text": "ans",
        "reasoning_mode": "simple", "generated_code": "result = 1", "key_numbers": [],
        "follow_up_questions": [], "step_count": 1, "cost_records": [],
    }
    result = finalize(state)
    with Session(_isolated_db) as s:
        qr = s.get(QueryResult, result["query_result_id"])
        assert qr.follow_up_questions_json is None
