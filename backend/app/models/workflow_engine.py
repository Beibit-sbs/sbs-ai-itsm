from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_workflow_definitions_tenant_code",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','ARCHIVED')",
            name="ck_workflow_definitions_status",
        ),
        CheckConstraint(
            "concurrency_policy IN ('ALLOW','SERIALIZE')",
            name="ck_workflow_definitions_concurrency",
        ),
        CheckConstraint(
            "max_active_executions >= 1 AND max_active_executions <= 1000",
            name="ck_workflow_definitions_max_active",
        ),
        Index(
            "ix_workflow_definitions_tenant_trigger_status",
            "tenant_id",
            "trigger_type",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PAUSED",
    )
    trigger_type: Mapped[str] = mapped_column(String(120), nullable=False)
    concurrency_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ALLOW",
    )
    max_active_executions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )
    publish_approval_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    latest_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    draft_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    published_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_executions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    failed_executions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_execution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
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


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_versions_number",
        ),
        CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','RETIRED')",
            name="ck_workflow_versions_status",
        ),
        CheckConstraint(
            "validation_status IN ('UNKNOWN','VALID','INVALID')",
            name="ck_workflow_versions_validation",
        ),
        CheckConstraint(
            "review_status IN ('NOT_REQUIRED','PENDING','APPROVED','REJECTED')",
            name="ck_workflow_versions_review",
        ),
        Index(
            "ix_workflow_versions_workflow_status",
            "workflow_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="UNKNOWN",
    )
    validation_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    based_on_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    rollback_from_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="NOT_REQUIRED",
    )
    review_requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
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


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "idempotency_key",
            name="uq_workflow_executions_idempotency",
        ),
        CheckConstraint(
            "status IN ("
            "'QUEUED','RUNNING','WAITING_TIMER','WAITING_APPROVAL',"
            "'WAITING_SUBFLOW','RETRY',"
            "'COMPENSATING','SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER',"
            "'DROPPED'"
            ")",
            name="ck_workflow_executions_status",
        ),
        CheckConstraint(
            "source IN ('AUTOMATIC','MANUAL','REPLAY')",
            name="ck_workflow_executions_source",
        ),
        Index(
            "ix_workflow_executions_due",
            "status",
            "next_run_at",
            "created_at",
        ),
        Index(
            "ix_workflow_executions_workflow_status",
            "workflow_id",
            "status",
        ),
        Index(
            "ix_workflow_executions_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_version_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workflow_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    replay_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_entity_type: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    trigger_entity_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    current_node_key: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_by_id: Mapped[str | None] = mapped_column(
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


class WorkflowStepExecution(Base):
    __tablename__ = "workflow_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "node_key",
            name="uq_workflow_step_executions_node",
        ),
        CheckConstraint(
            "status IN ("
            "'PENDING','RUNNING','WAITING','SUCCEEDED','FAILED','SKIPPED',"
            "'COMPENSATED','COMPENSATION_FAILED'"
            ")",
            name="ck_workflow_step_executions_status",
        ),
        Index(
            "ix_workflow_step_executions_execution_sequence",
            "execution_id",
            "sequence_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_version_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(80), nullable=False)
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    wait_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_status: Mapped[str | None] = mapped_column(
        String(24),
        nullable=True,
    )
    compensation_output_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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


class WorkflowApproval(Base):
    __tablename__ = "workflow_approvals"
    __table_args__ = (
        UniqueConstraint(
            "step_execution_id",
            name="uq_workflow_approvals_step",
        ),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED')",
            name="ck_workflow_approvals_status",
        ),
        Index(
            "ix_workflow_approvals_tenant_status",
            "tenant_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_step_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(80), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(80), nullable=False)
    allow_self_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requested_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
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


class WorkflowExecutionEvent(Base):
    __tablename__ = "workflow_execution_events"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "sequence_number",
            name="uq_workflow_execution_events_sequence",
        ),
        Index(
            "ix_workflow_execution_events_execution_created",
            "execution_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    node_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    details_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
