from __future__ import annotations

import importlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_problem_migration_upgrades_existing_0026_schema(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "problem-migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config_module = importlib.import_module("app.core.config")
    config_module.get_settings.cache_clear()

    problem_tables = {
        "problems",
        "problem_history",
        "problem_ticket_links",
        "problem_asset_links",
        "problem_change_links",
    }
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    command.upgrade(config, "20260720_0026")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert problem_tables.issubset(set(inspector.get_table_names()))
    assert {item["name"] for item in inspector.get_columns("problems")} >= {
        "problem_number",
        "root_cause",
        "known_error_published_at",
        "workaround_status",
        "version",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260829_0081"

    engine.dispose()
    importlib.import_module("app.core.config").get_settings.cache_clear()
