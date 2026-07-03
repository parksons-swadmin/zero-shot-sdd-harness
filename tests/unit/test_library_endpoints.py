"""Unit tests for the Phase 2 library endpoints.

No network/LLM calls: datasets are uploaded via POST /datasets (pure pandas
cleaning/profiling, no LLM) and chat history is seeded directly through the DB
session so GET /sessions/{id} can be exercised without running the agent graph.
"""


def _csv_bytes(rows: int, region: str) -> bytes:
    lines = ["name,signup_date,revenue,region"]
    for i in range(rows):
        lines.append(f"User {i}, 01/0{(i % 9) + 1}/2024, ${1000 + i}.50, {region}")
    return ("\n".join(lines)).encode("utf-8")


def _upload(api_client, tmp_path, monkeypatch, filename: str, rows: int, region: str) -> str:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    files = {"file": (filename, _csv_bytes(rows, region), "text/csv")}
    resp = api_client.post("/datasets", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


# --- GET /datasets --------------------------------------------------------


def test_list_datasets_empty_returns_empty_list(api_client):
    resp = api_client.get("/datasets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["datasets"] == []


def test_list_datasets_returns_all_newest_first(api_client, tmp_path, monkeypatch):
    first_id = _upload(api_client, tmp_path, monkeypatch, "month1.csv", 10, "West")
    second_id = _upload(api_client, tmp_path, monkeypatch, "month2.csv", 12, "East")

    # Ensure a strictly-later created_at for the second dataset so ordering is
    # deterministic even when uploads land in the same clock tick.
    from datetime import datetime, timedelta, timezone
    from db.session import create_db_session
    from db.models import Dataset

    with create_db_session() as s:
        d1 = s.get(Dataset, first_id)
        d2 = s.get(Dataset, second_id)
        base = datetime.now(timezone.utc)
        d1.created_at = base - timedelta(minutes=1)
        d2.created_at = base

    resp = api_client.get("/datasets")
    assert resp.status_code == 200
    datasets = resp.json()["data"]["datasets"]
    assert len(datasets) == 2
    assert datasets[0]["dataset_id"] == second_id  # newest first
    assert datasets[1]["dataset_id"] == first_id

    item = datasets[0]
    assert item["filename"] == "month2.csv"
    assert item["row_count"] == 12
    assert item["column_count"] == 4
    assert item["status"] == "ready"
    assert "created_at" in item


# --- GET /sessions/{session_id} ------------------------------------------


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _seed_history(session_id: str) -> None:
    from datetime import datetime, timedelta, timezone
    from db.session import create_db_session
    from db.models import Message, QueryResult

    base = datetime.now(timezone.utc)
    with create_db_session() as s:
        user_msg = Message(
            session_id=session_id,
            role="user",
            content="What is the total revenue?",
            created_at=base,
        )
        s.add(user_msg)
        s.flush()

        assistant_msg = Message(
            session_id=session_id,
            role="assistant",
            content="The total revenue is **$12,345.00**.",
            created_at=base + timedelta(seconds=3),
        )
        s.add(assistant_msg)
        s.flush()

        s.add(
            QueryResult(
                message_id=assistant_msg.id,
                session_id=session_id,
                reasoning_mode="simple",
                summary_text="The total revenue is **$12,345.00**.",
                key_numbers_json=[{"label": "Total revenue", "value": "12345.00"}],
                generated_code="result = df['revenue'].sum()",
                follow_up_questions_json=["What about by region?"],
                anomaly_flags_json=[],
                step_count=1,
                status="completed",
            )
        )


def test_get_session_unknown_returns_404(api_client):
    resp = api_client.get("/sessions/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


def test_get_session_empty_history(api_client, tmp_path, monkeypatch):
    dataset_id = _upload(api_client, tmp_path, monkeypatch, "d.csv", 5, "West")
    session_id = _create_session(api_client, [dataset_id])

    resp = api_client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == session_id
    assert data["dataset_ids"] == [dataset_id]
    assert data["messages"] == []


def test_get_session_history_ordered_with_query_result(api_client, tmp_path, monkeypatch):
    d1 = _upload(api_client, tmp_path, monkeypatch, "a.csv", 5, "West")
    d2 = _upload(api_client, tmp_path, monkeypatch, "b.csv", 6, "East")
    session_id = _create_session(api_client, [d1, d2])
    _seed_history(session_id)

    resp = api_client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == session_id
    assert set(data["dataset_ids"]) == {d1, d2}

    messages = data["messages"]
    assert len(messages) == 2
    # oldest-first ordering
    assert messages[0]["role"] == "user"
    assert messages[0]["query_result"] is None
    assert messages[1]["role"] == "assistant"

    qr = messages[1]["query_result"]
    assert qr is not None
    assert qr["summary_text"].startswith("The total revenue")
    assert qr["key_numbers"] == [{"label": "Total revenue", "value": "12345.00"}]
    assert qr["generated_code"] == "result = df['revenue'].sum()"
    assert qr["status"] == "completed"
    assert qr["step_count"] == 1
