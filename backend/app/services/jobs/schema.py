"""Development-only additive compatibility for the explicit startup-DDL mode."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def ensure_jobs_schema(engine: Engine) -> None:
    """Backfill lifecycle sequence for an existing local create-all database.

    Production never calls this helper because ``RUN_STARTUP_DDL`` is forbidden
    there; Alembic revision 0073 owns the production constraint. The helper is
    intentionally additive so the persistent local SQLite database remains
    usable after the model gains the sequence column.
    """

    inspector = inspect(engine)
    if "job_lifecycle_events" not in inspector.get_table_names():
        return
    columns = {str(column["name"]) for column in inspector.get_columns("job_lifecycle_events")}
    with engine.begin() as connection:
        if "sequence" not in columns:
            connection.execute(text("ALTER TABLE job_lifecycle_events ADD COLUMN sequence INTEGER"))

        rows = connection.execute(
            text(
                """
                SELECT id, job_id
                FROM job_lifecycle_events
                WHERE sequence IS NULL
                ORDER BY job_id, created_at, id
                """
            )
        ).mappings()
        next_sequence: dict[str, int] = {}
        for row in rows:
            job_id = str(row["job_id"])
            current_max = next_sequence.get(job_id)
            if current_max is None:
                current_max = int(
                    connection.execute(
                        text(
                            """
                            SELECT COALESCE(MAX(sequence), 0)
                            FROM job_lifecycle_events
                            WHERE job_id = :job_id AND sequence IS NOT NULL
                            """
                        ),
                        {"job_id": job_id},
                    ).scalar_one()
                )
            sequence = current_max + 1
            next_sequence[job_id] = sequence
            connection.execute(
                text("UPDATE job_lifecycle_events SET sequence = :sequence WHERE id = :id"),
                {"sequence": sequence, "id": str(row["id"])},
            )

        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_job_lifecycle_events_job_sequence
                ON job_lifecycle_events (job_id, sequence)
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_job_lifecycle_events_job_sequence
                ON job_lifecycle_events (job_id, sequence)
                """
            )
        )


__all__ = ["ensure_jobs_schema"]
