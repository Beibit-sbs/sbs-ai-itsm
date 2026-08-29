from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "request_number",
            name="uq_service_requests_tenant_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_service_requests_tenant_idempotency",
        ),
        Index("ix_service_requests_tenant_status", "tenant_id", "status"),
        Index(
            "ix_service_requests_tenant_cost_center",
            "tenant_id",
            "cost_center",
        ),
        Index("ix_service_requests_requester_id", "requester_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_number: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    requester_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requester_name: Mapped[str] = mapped_column(String(200), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="CATALOG")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SUBMITTED"
    )
    priority: Mapped[str] = mapped_column(
        String(24), nullable=False, default="MEDIUM"
    )
    requester_department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requester_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KZT")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RequestedItem(Base):
    __tablename__ = "requested_items"
    __table_args__ = (
        Index("ix_requested_items_request_id", "request_id"),
        Index("ix_requested_items_tenant_status", "tenant_id", "status"),
        Index(
            "ix_requested_items_tenant_sla",
            "tenant_id",
            "sla_status",
            "sla_due_at",
        ),
        Index("ix_requested_items_catalog_item_id", "catalog_item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="SET NULL"), nullable=True
    )
    catalog_form_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_form_versions.id", ondelete="SET NULL"), nullable=True
    )
    item_code: Mapped[str] = mapped_column(String(64), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SUBMITTED"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    form_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    form_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    support_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    approval_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="SEQUENTIAL"
    )
    unit_cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KZT")
    cost_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NO_CHARGE"
    )
    cost_center: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    entitlement_snapshot_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    approval_policy_snapshot_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    sla_policy_snapshot_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    sla_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NOT_STARTED"
    )
    sla_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_escalation_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    expected_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RequestApproval(Base):
    __tablename__ = "request_approvals"
    __table_args__ = (
        Index(
            "ix_request_approvals_request_status",
            "request_id",
            "status",
        ),
        Index(
            "ix_request_approvals_approver_status",
            "approver_id",
            "status",
        ),
        Index("ix_request_approvals_item_round", "requested_item_id", "round"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    requested_item_id: Mapped[str] = mapped_column(
        ForeignKey("requested_items.id", ondelete="CASCADE"), nullable=False
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="SEQUENTIAL"
    )
    approver_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    approver_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PENDING"
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class FulfillmentTask(Base):
    __tablename__ = "fulfillment_tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "task_number",
            name="uq_fulfillment_tasks_tenant_number",
        ),
        Index("ix_fulfillment_tasks_request_id", "request_id"),
        Index("ix_fulfillment_tasks_item_status", "requested_item_id", "status"),
        Index(
            "ix_fulfillment_tasks_assignee_status",
            "assignee_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    requested_item_id: Mapped[str] = mapped_column(
        ForeignKey("requested_items.id", ondelete="CASCADE"), nullable=False
    )
    task_number: Mapped[str] = mapped_column(String(48), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="OPEN"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assignee_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    support_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RequestActivity(Base):
    __tablename__ = "request_activities"
    __table_args__ = (
        Index("ix_request_activities_request_created", "request_id", "created_at"),
        Index("ix_request_activities_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    requested_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("requested_items.id", ondelete="CASCADE"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PUBLIC"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
