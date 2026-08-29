"""Reclassify mock Microsoft Teams delivery evidence.

Revision ID: 20260729_0072
Revises: 20260729_0071
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0072"
down_revision: str | None = "20260729_0071"
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

    if "teams_deliveries" in tables:
        constraints = {
            str(item.get("name"))
            for item in inspector.get_check_constraints("teams_deliveries")
        }
        if "ck_teams_deliveries_status" in constraints:
            with op.batch_alter_table("teams_deliveries") as batch_op:
                batch_op.drop_constraint(
                    "ck_teams_deliveries_status",
                    type_="check",
                )
                batch_op.create_check_constraint(
                    "ck_teams_deliveries_status",
                    (
                        "status IN ("
                        "'QUEUED','RETRY','SIMULATED','SENT','FAILED',"
                        "'DEAD_LETTER','CANCELLED'"
                        ")"
                    ),
                )

    if (
        "teams_deliveries" in tables
        and "teams_connectors" in tables
    ):
        delivery_columns = _columns(inspector, "teams_deliveries")
        connector_columns = _columns(inspector, "teams_connectors")
        required_delivery = {
            "connector_id",
            "status",
            "attempts",
            "last_attempt_at",
            "sent_at",
            "provider_status_code",
            "provider_reference",
            "last_error",
        }
        if (
            required_delivery.issubset(delivery_columns)
            and {"id", "provider_type"}.issubset(connector_columns)
        ):
            op.execute(
                sa.text(
                    """
                    UPDATE teams_deliveries
                    SET status = 'SIMULATED',
                        attempts = 0,
                        last_attempt_at = NULL,
                        sent_at = NULL,
                        provider_status_code = NULL,
                        provider_reference = NULL,
                        last_error =
                            'Simulation only; no Microsoft Teams webhook was called'
                    WHERE status = 'SENT'
                      AND EXISTS (
                          SELECT 1
                          FROM teams_connectors
                          WHERE teams_connectors.id =
                                teams_deliveries.connector_id
                            AND teams_connectors.provider_type = 'MOCK'
                      )
                    """
                )
            )

    if "teams_connectors" in tables:
        columns = _columns(inspector, "teams_connectors")
        required = {
            "provider_type",
            "success_count",
            "last_success_at",
            "last_error",
        }
        if required.issubset(columns):
            op.execute(
                sa.text(
                    """
                    UPDATE teams_connectors
                    SET success_count = 0,
                        last_success_at = NULL,
                        last_error =
                            'Simulation-only connector; no Teams webhook is configured'
                    WHERE provider_type = 'MOCK'
                    """
                )
            )


def downgrade() -> None:
    # Invalidated Teams delivery evidence must not be restored as sent.
    return
