"""Operator-only PostgreSQL migration round-trip in an isolated temporary DB."""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from app.core.config import get_settings


_SAFE_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def _migrate(database_url: str, operation: str, target: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    config = Config("alembic.ini")
    getattr(command, operation)(config, target)


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def run() -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "production":
        raise RuntimeError("Migration round-trip requires APP_ENV=production")

    original_database_url = settings.database_url
    original_url = make_url(original_database_url)
    if not original_url.database or not original_url.drivername.startswith("postgresql"):
        raise RuntimeError("Migration round-trip requires PostgreSQL")

    run_id = uuid.uuid4().hex[:12]
    database_name = f"itsm_migration_gate_{run_id}"
    if not _SAFE_DATABASE_NAME.fullmatch(database_name):
        raise RuntimeError("Generated unsafe temporary database name")
    temporary_url = original_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    admin_engine = create_engine(original_url, isolation_level="AUTOCOMMIT")
    temporary_engine: Engine | None = None
    transitions: list[str] = []
    dropped = False

    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        _migrate(temporary_url, "upgrade", "20260814_0073")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tickets (
                        id, tenant_id, ticket_number, title, requester_email,
                        department, location, category, priority, status,
                        requester_name, created_at, updated_at
                    ) VALUES (
                        :id, NULL, 'SD-4321', 'Migration gate ticket',
                        'migration-gate@example.invalid', 'Platform Assurance',
                        'Isolated temporary database', 'SOFTWARE_INSTALL',
                        'LOW', 'NEW', 'Migration Gate', :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            )

        temporary_engine.dispose()
        _migrate(temporary_url, "upgrade", "20260814_0074")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.connect() as connection:
            next_value_after_upgrade = int(
                connection.scalar(
                    text(
                        "SELECT next_value FROM ticket_number_counters "
                        "WHERE scope = 'global'"
                    )
                )
                or 0
            )
        if next_value_after_upgrade != 4322:
            raise RuntimeError(
                "Counter did not initialize above the existing ticket number"
            )

        temporary_engine.dispose()
        _migrate(temporary_url, "downgrade", "20260814_0073")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.connect() as connection:
            ticket_survived_downgrade = (
                int(
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM tickets "
                            "WHERE ticket_number = 'SD-4321'"
                        )
                    )
                    or 0
                )
                == 1
            )
            counter_removed_by_downgrade = (
                "ticket_number_counters" not in inspect(connection).get_table_names()
            )
        if not ticket_survived_downgrade or not counter_removed_by_downgrade:
            raise RuntimeError("0074 downgrade integrity assertion failed")

        temporary_engine.dispose()
        _migrate(temporary_url, "upgrade", "head")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.connect() as connection:
            ticket_survived_roundtrip = (
                int(
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM tickets "
                            "WHERE ticket_number = 'SD-4321'"
                        )
                    )
                    or 0
                )
                == 1
            )
            next_value_after_roundtrip = int(
                connection.scalar(
                    text(
                        "SELECT next_value FROM ticket_number_counters "
                        "WHERE scope = 'global'"
                    )
                )
                or 0
            )
        if not ticket_survived_roundtrip or next_value_after_roundtrip != 4322:
            raise RuntimeError("0074 re-upgrade integrity assertion failed")

        with temporary_engine.connect() as connection:
            first_sequence_allocation = int(
                connection.scalar(text("SELECT nextval('ticket_number_seq')")) or 0
            )
        if first_sequence_allocation != 4322:
            raise RuntimeError("0075 sequence did not initialize above existing tickets")

        temporary_engine.dispose()
        _migrate(temporary_url, "downgrade", "20260814_0074")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.connect() as connection:
            sequence_removed_by_downgrade = (
                connection.scalar(text("SELECT to_regclass('ticket_number_seq')"))
                is None
            )
            ticket_survived_sequence_downgrade = (
                int(
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM tickets "
                            "WHERE ticket_number = 'SD-4321'"
                        )
                    )
                    or 0
                )
                == 1
            )
        if not sequence_removed_by_downgrade or not ticket_survived_sequence_downgrade:
            raise RuntimeError("0075 downgrade integrity assertion failed")

        temporary_engine.dispose()
        _migrate(temporary_url, "upgrade", "head")
        temporary_engine = create_engine(temporary_url)
        transitions.append(_revision(temporary_engine))
        with temporary_engine.connect() as connection:
            sequence_allocation_after_roundtrip = int(
                connection.scalar(text("SELECT nextval('ticket_number_seq')")) or 0
            )
        if sequence_allocation_after_roundtrip != 4322:
            raise RuntimeError("0075 re-upgrade sequence assertion failed")

        return {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "PASS",
            "scope": "isolated_temporary_postgresql_migration_roundtrip",
            "temporary_database_prefix": "itsm_migration_gate_",
            "transitions": transitions,
            "ticket_survived_downgrade": ticket_survived_downgrade,
            "ticket_survived_roundtrip": ticket_survived_roundtrip,
            "counter_removed_by_downgrade": counter_removed_by_downgrade,
            "next_value_after_upgrade": next_value_after_upgrade,
            "next_value_after_roundtrip": next_value_after_roundtrip,
            "first_sequence_allocation": first_sequence_allocation,
            "sequence_removed_by_downgrade": sequence_removed_by_downgrade,
            "ticket_survived_sequence_downgrade": (
                ticket_survived_sequence_downgrade
            ),
            "sequence_allocation_after_roundtrip": (
                sequence_allocation_after_roundtrip
            ),
            "primary_rehearsal_database_changed": False,
        }
    finally:
        if temporary_engine is not None:
            temporary_engine.dispose()
        os.environ["DATABASE_URL"] = original_database_url
        get_settings.cache_clear()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
            dropped = True
        admin_engine.dispose()
        if not dropped:
            raise RuntimeError("Temporary migration database cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-rehearsal", action="store_true")
    args = parser.parse_args()
    enabled = os.environ.get("REHEARSAL_MIGRATION_EXERCISE_ENABLED", "").lower()
    if not args.confirm_rehearsal or enabled != "true":
        print(
            "Migration round-trip is disabled; require env opt-in and "
            "--confirm-rehearsal"
        )
        return 2
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001 - operator CLI must emit bounded failure
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
