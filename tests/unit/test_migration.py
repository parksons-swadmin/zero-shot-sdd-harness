"""Verify the Alembic migration chain applies cleanly to a scratch SQLite file
and produces the same schema as Base.metadata.create_all."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "runs",
    "datasets",
    "dataset_profiles",
    "cleaning_reports",
    "sessions",
    "session_datasets",
    "messages",
    "query_results",
    "audit_log_entries",
    "cost_records",
}


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_alembic_upgrade_head_creates_all_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "migration_scratch.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("AGENT_DATABASE_URL", db_url)

    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(table_names)
    engine.dispose()


def test_alembic_current_reports_head_revision(tmp_path, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "migration_scratch2.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("AGENT_DATABASE_URL", db_url)

    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    script = ScriptDirectory.from_config(cfg)
    head_revision = script.get_current_head()
    assert head_revision == "0002"

    engine = create_engine(db_url)
    with engine.connect() as conn:
        current_revision = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()

    assert current_revision == head_revision
