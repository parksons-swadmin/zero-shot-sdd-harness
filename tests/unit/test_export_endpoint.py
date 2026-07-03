"""Unit tests for the Phase 3a export-download endpoint.

No network/LLM calls. Rows (a derived Dataset + its QueryResult) are seeded
directly through the DB session against the real SQLite file DB, with an
on-disk export.csv fixture, so GET /query-results/{id}/export can be exercised
without running the agent graph or the artifacts-graph slice.
"""

from pathlib import Path


_CSV_CONTENT = b"name,region,revenue\nAlice,West,1000.50\nBob,West,2500.00\n"


def _seed_export(export_csv_path: str | None, filename: str = "leads_export.csv") -> str:
    """Create a QueryResult + a derived Dataset pointing at export_csv_path.

    When export_csv_path is None, the QueryResult has no export_dataset_id.
    Returns the query_result_id.
    """
    from db.session import create_db_session
    from db.models import Dataset, Message, QueryResult, SessionRow

    with create_db_session() as s:
        sess = SessionRow()
        s.add(sess)
        s.flush()

        msg = Message(session_id=sess.id, role="assistant", content="Here is your export.")
        s.add(msg)
        s.flush()

        export_dataset_id = None
        if export_csv_path is not None:
            derived = Dataset(
                filename=filename,
                original_path=export_csv_path,
                size_bytes=len(_CSV_CONTENT),
                status="ready",
            )
            s.add(derived)
            s.flush()
            export_dataset_id = derived.id

        qr = QueryResult(
            message_id=msg.id,
            session_id=sess.id,
            reasoning_mode="simple",
            summary_text="Here is your export.",
            generated_code="export_df = df[df['region'] == 'West']",
            export_dataset_id=export_dataset_id,
            step_count=1,
            status="completed",
        )
        s.add(qr)
        s.flush()
        return qr.id


def _write_export_csv(tmp_path) -> str:
    export_dir = tmp_path / "exports" / "qr"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "export.csv"
    path.write_bytes(_CSV_CONTENT)
    return str(path)


# --- happy path ----------------------------------------------------------


def test_export_streams_file_with_attachment_header(api_client, tmp_path):
    csv_path = _write_export_csv(tmp_path)
    qr_id = _seed_export(csv_path, filename="leads_export.csv")

    resp = api_client.get(f"/query-results/{qr_id}/export")

    assert resp.status_code == 200, resp.text
    # exact byte content of the derived export file
    assert resp.content == _CSV_CONTENT
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert 'filename="leads_export_derived.csv"' in disposition


# --- error path: no export produced --------------------------------------


def test_export_404_when_no_export_dataset(api_client, tmp_path):
    qr_id = _seed_export(None)

    resp = api_client.get(f"/query-results/{qr_id}/export")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


# --- edge case: unknown query result -------------------------------------


def test_export_404_when_query_result_unknown(api_client):
    resp = api_client.get("/query-results/does-not-exist/export")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


# --- error path: file missing on disk ------------------------------------


def test_export_404_when_file_missing_on_disk(api_client, tmp_path):
    missing_path = str(tmp_path / "exports" / "gone" / "export.csv")
    assert not Path(missing_path).exists()
    qr_id = _seed_export(missing_path)

    resp = api_client.get(f"/query-results/{qr_id}/export")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
