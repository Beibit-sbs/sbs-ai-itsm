"""Add governed ticket participants and watcher preferences.

Revision ID: 20260814_0079
Revises: 20260814_0078
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0079"
down_revision: str | None = "20260814_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "ticket_participants" in existing:
        return
    op.create_table(
        "ticket_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_id",
            sa.String(36),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("identity_key", sa.String(280), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("participant_role", sa.String(32), nullable=False),
        sa.Column("notification_scope", sa.String(20), nullable=False, server_default="PUBLIC_ONLY"),
        sa.Column("notify_in_app", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "added_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.Column(
            "removed_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "participant_role IN ('WATCHER','COLLABORATOR','REQUESTER_REPRESENTATIVE')",
            name="ck_ticket_participants_role",
        ),
        sa.CheckConstraint(
            "notification_scope IN ('ALL','PUBLIC_ONLY','STATUS_ONLY','NONE')",
            name="ck_ticket_participants_notification_scope",
        ),
        sa.UniqueConstraint(
            "ticket_id",
            "identity_key",
            name="uq_ticket_participants_ticket_identity",
        ),
    )
    op.create_index(
        "ix_ticket_participants_tenant_ticket_active",
        "ticket_participants",
        ["tenant_id", "ticket_id", "is_active"],
    )
    op.create_index(
        "ix_ticket_participants_user_active",
        "ticket_participants",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    if "ticket_participants" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("ticket_participants")
