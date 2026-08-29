"""Reclassify legacy integration simulations as non-production evidence.

Revision ID: 20260729_0069
Revises: 20260729_0068
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0069"
down_revision: str | None = "20260729_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    external_columns: set[str] = set()
    if "external_systems" in tables:
        external_columns = _columns(inspector, "external_systems")
        if {
            "is_mock",
            "status",
            "health_status",
            "last_health_status",
            "last_success_at",
        }.issubset(external_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE external_systems
                    SET status = CASE
                            WHEN status IN ('active', 'healthy', 'connected')
                                THEN 'mock'
                            ELSE status
                        END,
                        health_status = 'simulated',
                        last_health_status = 'simulated',
                        last_success_at = NULL
                    WHERE is_mock IS TRUE
                    """
                )
            )

    if "integration_event_logs" in tables:
        event_columns = _columns(inspector, "integration_event_logs")
        if {"status", "event_type"}.issubset(event_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE integration_event_logs
                    SET status = 'simulated'
                    WHERE status = 'success'
                      AND event_type LIKE 'mock_%'
                    """
                )
            )
        if (
            {"status", "external_system_id"}.issubset(event_columns)
            and {"id", "is_mock"}.issubset(external_columns)
        ):
            op.execute(
                sa.text(
                    """
                    UPDATE integration_event_logs
                    SET status = 'simulated'
                    WHERE status = 'success'
                      AND external_system_id IN (
                          SELECT id
                          FROM external_systems
                          WHERE is_mock IS TRUE
                      )
                    """
                )
            )

    if (
        "import_jobs" in tables
        and {"id", "is_mock"}.issubset(external_columns)
    ):
        import_columns = _columns(inspector, "import_jobs")
        required_import_columns = {
            "external_system_id",
            "status",
            "success_rows",
            "records_success",
            "dry_run",
        }
        if required_import_columns.issubset(import_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE import_jobs
                    SET status = CASE
                            WHEN status = 'completed_with_errors'
                                THEN 'simulated_with_errors'
                            ELSE 'simulated'
                        END,
                        success_rows = 0,
                        records_success = 0,
                        dry_run = TRUE
                    WHERE status IN ('completed', 'completed_with_errors')
                      AND external_system_id IN (
                          SELECT id
                          FROM external_systems
                          WHERE is_mock IS TRUE
                      )
                    """
                )
            )

    if "webhook_endpoints" in tables:
        webhook_columns = _columns(inspector, "webhook_endpoints")
        if {"success_count", "last_received_at"}.issubset(webhook_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE webhook_endpoints
                    SET success_count = 0,
                        last_received_at = NULL
                    """
                )
            )


def downgrade() -> None:
    # Invalidated success evidence cannot be safely reconstructed.
    return
