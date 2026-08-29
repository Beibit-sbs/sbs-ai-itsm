from __future__ import annotations

import importlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_change_migration_upgrades_existing_0025_schema(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "change-migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config_module = importlib.import_module("app.core.config")
    config_module.get_settings.cache_clear()

    change_tables = {
        "change_requests",
        "change_approvals",
        "change_history",
        "change_asset_links",
        "change_ticket_links",
    }
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    command.upgrade(config, "20260720_0025")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert change_tables.issubset(set(inspector.get_table_names()))
    assert {item["name"] for item in inspector.get_columns("change_requests")} >= {
        "change_number",
        "risk_score",
        "approval_status",
        "version",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260829_0081"
    assert {
        "detected_content_type",
        "security_findings_json",
        "sanitization_applied",
        "download_count",
    }.issubset(
        {item["name"] for item in inspector.get_columns("email_attachments")}
    )
    assert {
        "data_retention_policies",
        "data_legal_holds",
        "data_deletion_requests",
        "data_deletion_evidence",
    }.issubset(set(inspector.get_table_names()))

    engine.dispose()
    importlib.import_module("app.core.config").get_settings.cache_clear()
