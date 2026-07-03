"""Phase-1 schema model tests — no LLM key required."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import (
    Base,
    Dataset,
    DatasetProfile,
    CleaningReport,
    SessionRow,
    SessionDataset,
    Message,
    QueryResult,
    AuditLogEntry,
    CostRecord,
)


def _dataset(**overrides) -> Dataset:
    defaults = dict(
        filename="leads_export.csv",
        original_path="/data/uploads/x/original.csv",
        size_bytes=1024,
        status="uploading",
    )
    defaults.update(overrides)
    return Dataset(**defaults)


def test_all_tables_create_via_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/models.db")
    Base.metadata.create_all(engine)
    table_names = set(Base.metadata.tables.keys())
    for expected in [
        "datasets",
        "dataset_profiles",
        "cleaning_reports",
        "sessions",
        "session_datasets",
        "messages",
        "query_results",
        "audit_log_entries",
        "cost_records",
    ]:
        assert expected in table_names
    engine.dispose()


def test_dataset_crud_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _dataset()
        s.add(ds)
        s.commit()
        dataset_id = ds.id

    with Session(_isolated_db) as s:
        fetched = s.get(Dataset, dataset_id)
        assert fetched is not None
        assert fetched.filename == "leads_export.csv"
        assert fetched.status == "uploading"
        assert fetched.row_count is None
        assert fetched.cleaned_path is None


def test_dataset_profile_and_cleaning_report_one_to_one(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _dataset(status="ready", row_count=12500, column_count=14)
        s.add(ds)
        s.flush()
        dataset_id = ds.id

        profile = DatasetProfile(
            dataset_id=dataset_id,
            columns_json={
                "columns": [
                    {
                        "name": "revenue",
                        "dtype": "float64",
                        "null_count": 3,
                        "distinct_count": 8210,
                        "min": 0.0,
                        "max": 98234.5,
                        "mean": 4210.2,
                        "median": 1890.0,
                        "top_values": None,
                    }
                ]
            },
        )
        report = CleaningReport(
            dataset_id=dataset_id,
            issues_json={
                "issues": [
                    {
                        "column": "signup_date",
                        "issue_type": "inconsistent_format",
                        "action_taken": "parsed to ISO-8601",
                        "affected_row_count": 340,
                        "needs_review": False,
                    }
                ]
            },
        )
        s.add_all([profile, report])
        s.commit()

    with Session(_isolated_db) as s:
        fetched_profile = s.query(DatasetProfile).filter(
            DatasetProfile.dataset_id == dataset_id
        ).one()
        assert fetched_profile.columns_json["columns"][0]["name"] == "revenue"

        fetched_report = s.query(CleaningReport).filter(
            CleaningReport.dataset_id == dataset_id
        ).one()
        assert fetched_report.issues_json["issues"][0]["needs_review"] is False


def test_session_message_query_result_chain(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _dataset(status="ready")
        s.add(ds)
        s.flush()

        sess = SessionRow(title="leads_export.csv")
        s.add(sess)
        s.flush()

        s.add(SessionDataset(session_id=sess.id, dataset_id=ds.id))

        user_msg = Message(session_id=sess.id, role="user", content="What is total revenue?")
        s.add(user_msg)
        s.flush()

        assistant_msg = Message(
            session_id=sess.id,
            role="assistant",
            content="The total revenue is $4,201,932.10.",
        )
        s.add(assistant_msg)
        s.flush()

        qr = QueryResult(
            message_id=assistant_msg.id,
            session_id=sess.id,
            reasoning_mode="simple",
            summary_text="The total revenue is $4,201,932.10.",
            key_numbers_json=[{"label": "Total revenue", "value": "4201932.10"}],
            generated_code="result = df['revenue'].sum()",
            step_count=1,
            status="completed",
        )
        s.add(qr)
        s.commit()
        session_id = sess.id
        query_result_id = qr.id

    with Session(_isolated_db) as s:
        joins = s.query(SessionDataset).filter(SessionDataset.session_id == session_id).all()
        assert len(joins) == 1

        messages = s.query(Message).filter(Message.session_id == session_id).all()
        assert len(messages) == 2

        fetched_qr = s.get(QueryResult, query_result_id)
        assert fetched_qr.status == "completed"
        assert fetched_qr.key_numbers_json[0]["label"] == "Total revenue"


def test_audit_log_entry_and_cost_record_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        entry = AuditLogEntry(event_type="upload", detail_json={"filename": "x.csv"})
        s.add(entry)

        cost = CostRecord(
            provider="gemini",
            model="gemini-3.1-pro",
            prompt_tokens=120,
            completion_tokens=45,
            estimated_cost_usd=0.0012,
        )
        s.add(cost)
        s.commit()
        entry_id = entry.id
        cost_id = cost.id

    with Session(_isolated_db) as s:
        fetched_entry = s.get(AuditLogEntry, entry_id)
        assert fetched_entry.event_type == "upload"
        assert fetched_entry.session_id is None
        assert fetched_entry.detail_json["filename"] == "x.csv"

        fetched_cost = s.get(CostRecord, cost_id)
        assert fetched_cost.provider == "gemini"
        assert fetched_cost.query_result_id is None
        assert float(fetched_cost.estimated_cost_usd) == 0.0012


def test_audit_log_entry_missing_event_type_rejected(_isolated_db):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with Session(_isolated_db) as s:
        entry = AuditLogEntry(event_type=None, detail_json={})
        s.add(entry)
        with pytest.raises(IntegrityError):
            s.commit()
