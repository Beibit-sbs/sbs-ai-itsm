"""Reclassify mock email delivery evidence.

Revision ID: 20260729_0071
Revises: 20260729_0070
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0071"
down_revision: str | None = "20260729_0070"
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

    if "email_delivery_events" in tables:
        constraints = {
            str(item.get("name"))
            for item in inspector.get_check_constraints(
                "email_delivery_events"
            )
        }
        if "ck_email_delivery_event_type" in constraints:
            with op.batch_alter_table("email_delivery_events") as batch_op:
                batch_op.drop_constraint(
                    "ck_email_delivery_event_type",
                    type_="check",
                )
                batch_op.create_check_constraint(
                    "ck_email_delivery_event_type",
                    (
                        "event_type IN ("
                        "'QUEUED','SIMULATED','ACCEPTED','DELIVERED',"
                        "'DELAYED','BOUNCED','COMPLAINT','FAILED'"
                        ")"
                    ),
                )

    if "email_message_logs" in tables:
        columns = _columns(inspector, "email_message_logs")
        required = {
            "provider",
            "status",
            "provider_message_id",
            "accepted_at",
            "sent_at",
            "delivered_at",
            "attempt_count",
            "next_retry_at",
            "error_message",
        }
        if required.issubset(columns):
            op.execute(
                sa.text(
                    """
                    UPDATE email_message_logs
                    SET status = 'SIMULATED',
                        provider_message_id = NULL,
                        accepted_at = NULL,
                        sent_at = NULL,
                        delivered_at = NULL,
                        attempt_count = 0,
                        next_retry_at = NULL,
                        error_message =
                            'Simulation only; no external email was sent'
                    WHERE LOWER(provider) LIKE 'mock%'
                      AND status IN (
                          'ACCEPTED',
                          'DELIVERED',
                          'SENT',
                          'accepted',
                          'delivered',
                          'sent'
                      )
                    """
                )
            )

    if (
        "email_delivery_events" in tables
        and "email_message_logs" in tables
    ):
        event_columns = _columns(inspector, "email_delivery_events")
        log_columns = _columns(inspector, "email_message_logs")
        if (
            {"email_log_id", "event_type", "reason"}.issubset(event_columns)
            and {"id", "provider"}.issubset(log_columns)
        ):
            op.execute(
                sa.text(
                    """
                    UPDATE email_delivery_events
                    SET event_type = 'SIMULATED',
                        reason =
                            'Simulation only; no external email was sent'
                    WHERE event_type IN (
                        'ACCEPTED',
                        'DELIVERED'
                    )
                      AND EXISTS (
                          SELECT 1
                          FROM email_message_logs
                          WHERE email_message_logs.id =
                                email_delivery_events.email_log_id
                            AND LOWER(email_message_logs.provider)
                                LIKE 'mock%'
                      )
                    """
                )
            )

    if "email_channels" in tables:
        columns = _columns(inspector, "email_channels")
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
                    UPDATE email_channels
                    SET success_count = 0,
                        last_success_at = NULL,
                        last_error =
                            'Simulation-only channel; no external transport is configured'
                    WHERE provider_type = 'MOCK'
                    """
                )
            )


def downgrade() -> None:
    # Invalidated delivery evidence must never be recreated as confirmed success.
    return
