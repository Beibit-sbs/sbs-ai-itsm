"""Add enterprise identity provisioning and joiner/mover/leaver controls.

Revision ID: 20260729_0046
Revises: 20260729_0045
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0046"
down_revision: str | None = "20260729_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("users")
    }
    if "identity_source" in columns:
        return
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("manager_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("employee_number", sa.String(120), nullable=True))
        batch.add_column(
            sa.Column(
                "identity_source",
                sa.String(32),
                server_default="LOCAL",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "provisioning_state",
                sa.String(24),
                server_default="LOCAL",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_foreign_key(
            "fk_users_manager_id_users",
            "users",
            ["manager_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_users_identity_source",
            "identity_source IN ('LOCAL','OIDC','SCIM','ENTRA')",
        )
        batch.create_check_constraint(
            "ck_users_provisioning_state",
            "provisioning_state IN ('LOCAL','ACTIVE','SUSPENDED','DEPROVISIONED')",
        )
        batch.create_index(
            "ix_users_tenant_identity_state",
            ["tenant_id", "identity_source", "provisioning_state"],
        )
        batch.create_index("ix_users_manager_id", ["manager_id"])

    op.create_table(
        "identity_provisioning_connectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(16), nullable=False),
        sa.Column("external_tenant_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_hint", sa.String(16), nullable=False),
        sa.Column("token_rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("default_role_id", sa.String(36), nullable=False),
        sa.Column("fallback_owner_id", sa.String(36), nullable=False),
        sa.Column("attribute_mapping_json", sa.JSON(), nullable=False),
        sa.Column("allowed_ip_cidrs_json", sa.JSON(), nullable=False),
        sa.Column("retry_max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "provider_type IN ('SCIM','ENTRA')",
            name="ck_identity_connectors_provider_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_identity_connectors_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["default_role_id"], ["roles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["fallback_owner_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_identity_connectors_tenant_name",
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_identity_connectors_token_hash",
        ),
        sa.UniqueConstraint(
            "external_tenant_id",
            name="uq_identity_connectors_external_tenant",
        ),
    )
    op.create_index(
        "ix_identity_connectors_tenant_status",
        "identity_provisioning_connectors",
        ["tenant_id", "status"],
    )

    op.create_table(
        "provisioned_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=False),
        sa.Column("lifecycle_state", sa.String(20), nullable=False),
        sa.Column("manager_external_id", sa.String(255), nullable=True),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("scim_version", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deprovisioned_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','SUSPENDED','DEPROVISIONED')",
            name="ck_provisioned_identities_lifecycle",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["identity_provisioning_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "connector_id",
            "external_id",
            name="uq_provisioned_identities_external",
        ),
        sa.UniqueConstraint(
            "connector_id",
            "user_id",
            name="uq_provisioned_identities_user",
        ),
    )
    op.create_index(
        "ix_provisioned_identities_tenant_state",
        "provisioned_identities",
        ["tenant_id", "lifecycle_state"],
    )

    op.create_table(
        "provisioned_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("mapped_role_id", sa.String(36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("scim_version", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["identity_provisioning_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mapped_role_id"], ["roles.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "connector_id",
            "external_id",
            name="uq_provisioned_groups_external",
        ),
        sa.UniqueConstraint(
            "connector_id",
            "display_name",
            name="uq_provisioned_groups_display",
        ),
    )
    op.create_index(
        "ix_provisioned_groups_tenant_active",
        "provisioned_groups",
        ["tenant_id", "is_active"],
    )

    op.create_table(
        "provisioned_group_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("identity_id", sa.String(36), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["provisioned_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["provisioned_identities.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "group_id",
            "identity_id",
            name="uq_provisioned_group_members_pair",
        ),
    )
    op.create_index(
        "ix_provisioned_group_members_identity",
        "provisioned_group_members",
        ["identity_id"],
    )

    op.create_table(
        "identity_provisioning_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_user_id", sa.String(36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "resource_type IN ('User','Group')",
            name="ck_identity_provisioning_events_resource",
        ),
        sa.CheckConstraint(
            "operation IN ('CREATE','REPLACE','PATCH','DELETE','RETRY')",
            name="ck_identity_provisioning_events_operation",
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED','APPLIED','FAILED','RETRY_SCHEDULED','DEAD_LETTER')",
            name="ck_identity_provisioning_events_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["identity_provisioning_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["applied_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "connector_id",
            "external_event_id",
            name="uq_identity_provisioning_events_external",
        ),
    )
    op.create_index(
        "ix_identity_provisioning_events_retry",
        "identity_provisioning_events",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_identity_provisioning_events_tenant_created",
        "identity_provisioning_events",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "identity_ownership_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("from_user_id", sa.String(36), nullable=False),
        sa.Column("to_user_id", sa.String(36), nullable=False),
        sa.Column("provisioning_event_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transferred_counts_json", sa.JSON(), nullable=False),
        sa.Column("sessions_revoked", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("initiated_by_id", sa.String(36), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('COMPLETED','FAILED')",
            name="ck_identity_ownership_transfers_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["from_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["provisioning_event_id"],
            ["identity_provisioning_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_identity_ownership_transfers_source",
        "identity_ownership_transfers",
        ["tenant_id", "from_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_identity_ownership_transfers_source",
        table_name="identity_ownership_transfers",
    )
    op.drop_table("identity_ownership_transfers")
    op.drop_index(
        "ix_identity_provisioning_events_tenant_created",
        table_name="identity_provisioning_events",
    )
    op.drop_index(
        "ix_identity_provisioning_events_retry",
        table_name="identity_provisioning_events",
    )
    op.drop_table("identity_provisioning_events")
    op.drop_index(
        "ix_provisioned_group_members_identity",
        table_name="provisioned_group_members",
    )
    op.drop_table("provisioned_group_members")
    op.drop_index(
        "ix_provisioned_groups_tenant_active",
        table_name="provisioned_groups",
    )
    op.drop_table("provisioned_groups")
    op.drop_index(
        "ix_provisioned_identities_tenant_state",
        table_name="provisioned_identities",
    )
    op.drop_table("provisioned_identities")
    op.drop_index(
        "ix_identity_connectors_tenant_status",
        table_name="identity_provisioning_connectors",
    )
    op.drop_table("identity_provisioning_connectors")

    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_manager_id")
        batch.drop_index("ix_users_tenant_identity_state")
        batch.drop_constraint("ck_users_provisioning_state", type_="check")
        batch.drop_constraint("ck_users_identity_source", type_="check")
        batch.drop_constraint("fk_users_manager_id_users", type_="foreignkey")
        batch.drop_column("deactivated_at")
        batch.drop_column("provisioning_state")
        batch.drop_column("identity_source")
        batch.drop_column("employee_number")
        batch.drop_column("manager_id")
