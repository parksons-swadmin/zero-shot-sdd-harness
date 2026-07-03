"""API contract tests — no LLM key required, graph is not invoked (run_agent mocked)."""
from unittest.mock import patch

from sqlalchemy.orm import Session

from db.models import Dataset, DatasetProfile, SessionRow


def _make_dataset(db_engine, dataset_id: str = "ds-1") -> None:
    with Session(db_engine) as s:
        s.add(Dataset(
            id=dataset_id, filename="f.csv", original_path="/tmp/f.csv",
            size_bytes=10, status="ready", row_count=1, column_count=1,
        ))
        s.add(DatasetProfile(dataset_id=dataset_id, columns_json=[
            {"name": "revenue", "dtype": "float64", "null_count": 0, "distinct_count": 1,
             "min": 1.0, "max": 1.0, "mean": 1.0, "median": 1.0, "top_values": None},
        ]))
        s.commit()


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_create_session_happy_path(api_client, _isolated_db):
    _make_dataset(_isolated_db)
    r = api_client.post("/sessions", json={"dataset_ids": ["ds-1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["session_id"]
    assert body["data"]["dataset_ids"] == ["ds-1"]


def test_create_session_empty_dataset_ids_rejected(api_client, _isolated_db):
    r = api_client.post("/sessions", json={"dataset_ids": []})
    assert r.status_code == 422


def test_create_session_unknown_dataset_rejected(api_client, _isolated_db):
    r = api_client.post("/sessions", json={"dataset_ids": ["does-not-exist"]})
    assert r.status_code == 404


def test_ask_question_unknown_session_returns_404(api_client, _isolated_db):
    r = api_client.post("/sessions/does-not-exist/messages", json={"question": "What is the total?"})
    assert r.status_code == 404


def test_ask_question_empty_question_returns_422(api_client, _isolated_db):
    _make_dataset(_isolated_db)
    with Session(_isolated_db) as s:
        row = SessionRow(id="sess-1")
        s.add(row)
        s.commit()
    r = api_client.post("/sessions/sess-1/messages", json={"question": "   "})
    assert r.status_code == 422


def test_ask_question_happy_path_mocked_graph(api_client, _isolated_db):
    _make_dataset(_isolated_db)
    with Session(_isolated_db) as s:
        s.add(SessionRow(id="sess-2"))
        s.commit()

    from db.models import QueryResult, Message

    with Session(_isolated_db) as s:
        msg = Message(id="msg-1", session_id="sess-2", role="assistant", content="The total is **42**.")
        s.add(msg)
        s.commit()
        qr = QueryResult(
            id="qr-1", message_id="msg-1", session_id="sess-2", reasoning_mode="simple",
            summary_text="The total is **42**.", key_numbers_json=[{"label": "value_1", "value": "42"}],
            generated_code="result = 42", step_count=1, status="completed",
        )
        s.add(qr)
        s.commit()

    fake_final_state = {"status": "completed", "message_id": "msg-1", "query_result_id": "qr-1"}
    with patch("api.sessions.run_agent", return_value=fake_final_state):
        r = api_client.post("/sessions/sess-2/messages", json={"question": "What is the total?"})

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["query_result"]["summary_text"] == "The total is **42**."
    assert body["data"]["query_result"]["status"] == "completed"


def test_ask_question_conflict_returns_409(api_client, _isolated_db):
    _make_dataset(_isolated_db)
    with Session(_isolated_db) as s:
        s.add(SessionRow(id="sess-3"))
        s.commit()

    from graph.runner import SessionBusyError

    with patch("api.sessions.run_agent", side_effect=SessionBusyError("busy")):
        r = api_client.post("/sessions/sess-3/messages", json={"question": "What is the total?"})

    assert r.status_code == 409


def test_ask_question_graph_failure_returns_200_with_failed_status(api_client, _isolated_db):
    _make_dataset(_isolated_db)
    with Session(_isolated_db) as s:
        s.add(SessionRow(id="sess-4"))
        s.commit()

    fake_final_state = {"status": "failed", "error": "Gemini call failed", "reasoning_mode": "simple"}
    with patch("api.sessions.run_agent", return_value=fake_final_state):
        r = api_client.post("/sessions/sess-4/messages", json={"question": "What is the total?"})

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["query_result"]["status"] == "failed"
    assert "couldn't answer" in body["data"]["query_result"]["summary_text"]
