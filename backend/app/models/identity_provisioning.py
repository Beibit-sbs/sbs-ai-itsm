from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdentityProvisioningConnector(Base):
    __tablename__ = "identity_provisioning_connectors"
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('SCIM','ENTRA')",
            name="ck_identity_connectors_provider_type",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','REVOKED')",
            name="ck_identity_connectors_status",
        ),
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_identity_connectors_tenant_name",
        ),
        UniqueConstraint(
            "token_hash",
            name="uq_identity_connectors_token_hash",
        ),
        UniqueConstraint(
            "external_tenant_id",
            name="uq_identity_connectors_external_tenant",
        ),
        Index(
            "ix_identity_connectors_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DRAFT",
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    token_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    default_role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fallback_owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attribute_mapping_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    allowed_ip_cidrs_json: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    retry_max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProvisionedIdentity(Base):
    __tablename__ = "provisioned_identities"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','SUSPENDED','DEPROVISIONED')",
            name="ck_provisioned_identities_lifecycle",
        ),
        UniqueConstraint(
            "connector_id",
            "external_id",
            name="uq_provisioned_identities_external",
        ),
        UniqueConstraint(
            "connector_id",
            "user_id",
            name="uq_provisioned_identities_user",
        ),
        Index(
            "ix_provisioned_identities_tenant_state",
            "tenant_id",
            "lifecycle_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("identity_provisioning_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
    )
    manager_external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    attributes_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    scim_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    deprovisioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProvisionedGroup(Base):
    __tablename__ = "provisioned_groups"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "external_id",
            name="uq_provisioned_groups_external",
        ),
        UniqueConstraint(
            "connector_id",
            "display_name",
            name="uq_provisioned_groups_display",
        ),
        Index(
            "ix_provisioned_groups_tenant_active",
            "tenant_id",
            "is_active",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("identity_provisioning_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mapped_role_id: Mapped[str | None] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    scim_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProvisionedGroupMember(Base):
    __tablename__ = "provisioned_group_members"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "identity_id",
            name="uq_provisioned_group_members_pair",
        ),
        Index(
            "ix_provisioned_group_members_identity",
            "identity_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[str] = mapped_column(
        ForeignKey("provisioned_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("provisioned_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class IdentityProvisioningEvent(Base):
    __tablename__ = "identity_provisioning_events"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('User','Group')",
            name="ck_identity_provisioning_events_resource",
        ),
        CheckConstraint(
            "operation IN ('CREATE','REPLACE','PATCH','DELETE','RETRY')",
            name="ck_identity_provisioning_events_operation",
        ),
        CheckConstraint(
            "status IN ('RECEIVED','APPLIED','FAILED','RETRY_SCHEDULED','DEAD_LETTER')",
            name="ck_identity_provisioning_events_status",
        ),
        UniqueConstraint(
            "connector_id",
            "external_event_id",
            name="uq_identity_provisioning_events_external",
        ),
        Index(
            "ix_identity_provisioning_events_retry",
            "status",
            "next_retry_at",
        ),
        Index(
            "ix_identity_provisioning_events_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("identity_provisioning_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="RECEIVED",
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    response_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    applied_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdentityOwnershipTransfer(Base):
    __tablename__ = "identity_ownership_transfers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('COMPLETED','FAILED')",
            name="ck_identity_ownership_transfers_status",
        ),
        Index(
            "ix_identity_ownership_transfers_source",
            "tenant_id",
            "from_user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provisioning_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("identity_provisioning_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transferred_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    sessions_revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    initiated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
