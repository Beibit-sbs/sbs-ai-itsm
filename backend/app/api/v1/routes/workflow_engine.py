from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.workflow_engine import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionEvent,
    WorkflowStepExecution,
    WorkflowVersion,
)
from app.services.audit import log_audit
from app.services.cmdb_schema import canonical_json
from app.services.rbac import has_permission, is_saas_root, require_permissions
from app.services.workflow_engine import (
    WORKFLOW_ACTION_CATALOG,
    WORKFLOW_NODE_TYPES,
    WORKFLOW_SCHEMA_VERSION,
    WORKFLOW_TRIGGER_CATALOG,
    cancel_workflow_execution,
    compare_workflow_versions,
    create_workflow,
    create_workflow_draft,
    decide_workflow_review,
    decide_workflow_approval,
    enqueue_workflow_execution,
    publish_workflow_version,
    request_workflow_review,
    replay_workflow_execution,
    rollback_workflow,
    simulate_workflow,
    update_workflow_draft,
    validate_workflow_definition,
    verify_workflow_event_chain,
)


router = APIRouter(prefix="/workflows")


class WorkflowCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    trigger_type: str = Field(min_length=2, max_length=120)
    concurrency_policy: Literal["ALLOW", "SERIALIZE"] = "ALLOW"
    max_active_executions: int = Field(default=100, ge=1, le=1_000)
    publish_approval_required: bool = False


class WorkflowUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    concurrency_policy: Literal["ALLOW", "SERIALIZE"] | None = None
    max_active_executions: int | None = Field(default=None, ge=1, le=1_000)
    publish_approval_required: bool | None = None
    status: Literal["ACTIVE", "PAUSED", "ARCHIVED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class DraftCreate(BaseModel):
    expected_workflow_revision: int = Field(ge=1)
    change_summary: str = Field(min_length=3, max_length=2_000)


class DraftUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    definition: dict[str, Any]
    change_summary: str = Field(min_length=3, max_length=2_000)


class SimulationRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    expected_workflow_revision: int = Field(ge=1)
    expected_version_revision: int = Field(ge=1)
    activate: bool = True
    change_ticket: str = Field(min_length=3, max_length=200)


class ReviewRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    comment: str = Field(min_length=3, max_length=2_000)


class ReviewDecision(BaseModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=2_000)


class RollbackRequest(BaseModel):
    expected_workflow_revision: int = Field(ge=1)
    target_version_number: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class ExecutionStart(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=120)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class ApprovalDecision(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=2_000)


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tenant_id(
    db: Session,
    current_user: AuthUserResponse,
    requested: str | None,
) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required for SaaS Root workflow administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(current_user: AuthUserResponse, tenant_id: str) -> None:
    if not is_saas_root(current_user) and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Workflow resource not found")


def _workflow(
    db: Session,
    workflow_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> WorkflowDefinition:
    statement = select(WorkflowDefinition).where(
        WorkflowDefinition.id == workflow_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _scope(current_user, item.tenant_id)
    return item


def _version(
    db: Session,
    workflow: WorkflowDefinition,
    version_number: int,
    *,
    lock: bool = False,
) -> WorkflowVersion:
    statement = select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.version_number == version_number,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    return item


def _execution(
    db: Session,
    execution_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> WorkflowExecution:
    statement = select(WorkflowExecution).where(
        WorkflowExecution.id == execution_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    _scope(current_user, item.tenant_id)
    return item


def _approval(
    db: Session,
    approval_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> WorkflowApproval:
    statement = select(WorkflowApproval).where(
        WorkflowApproval.id == approval_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow approval not found")
    _scope(current_user, item.tenant_id)
    return item


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _workflow_response(item: WorkflowDefinition) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "trigger_type": item.trigger_type,
        "concurrency_policy": item.concurrency_policy,
        "max_active_executions": item.max_active_executions,
        "publish_approval_required": item.publish_approval_required,
        "latest_version_number": item.latest_version_number,
        "draft_version_number": item.draft_version_number,
        "published_version_number": item.published_version_number,
        "revision": item.revision,
        "total_executions": item.total_executions,
        "failed_executions": item.failed_executions,
        "last_execution_at": item.last_execution_at,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _version_integrity_valid(item: WorkflowVersion) -> bool:
    definition = _json_object(item.definition_json)
    return (
        hashlib.sha256(canonical_json(definition).encode("utf-8")).hexdigest()
        == item.definition_sha256
    )


def _version_response(
    item: WorkflowVersion,
    *,
    include_definition: bool = True,
) -> dict[str, object]:
    definition = _json_object(item.definition_json)
    result: dict[str, object] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "workflow_id": item.workflow_id,
        "version_number": item.version_number,
        "status": item.status,
        "definition_sha256": item.definition_sha256,
        "integrity_valid": _version_integrity_valid(item),
        "validation_status": item.validation_status,
        "validation": _json_object(item.validation_json),
        "revision": item.revision,
        "based_on_version_number": item.based_on_version_number,
        "rollback_from_version_number": item.rollback_from_version_number,
        "change_summary": item.change_summary,
        "review_status": item.review_status,
        "review_requested_by_id": item.review_requested_by_id,
        "reviewed_by_id": item.reviewed_by_id,
        "review_comment": item.review_comment,
        "review_requested_at": item.review_requested_at,
        "reviewed_at": item.reviewed_at,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "published_by_id": item.published_by_id,
        "published_at": item.published_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if include_definition:
        result["definition"] = definition
    return result


def _step_response(item: WorkflowStepExecution) -> dict[str, object]:
    return {
        "id": item.id,
        "node_key": item.node_key,
        "node_type": item.node_type,
        "sequence_number": item.sequence_number,
        "status": item.status,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "input": _json_object(item.input_json),
        "output": _json_object(item.output_json),
        "next_retry_at": item.next_retry_at,
        "wait_until": item.wait_until,
        "last_error": item.last_error,
        "compensation_status": item.compensation_status,
        "compensation_output": _json_object(item.compensation_output_json),
        "started_at": item.started_at,
        "completed_at": item.completed_at,
    }


def _execution_response(
    item: WorkflowExecution,
    *,
    steps: list[WorkflowStepExecution] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "workflow_id": item.workflow_id,
        "workflow_version_id": item.workflow_version_id,
        "workflow_version_number": item.workflow_version_number,
        "replay_of_id": item.replay_of_id,
        "idempotency_key": item.idempotency_key,
        "source": item.source,
        "trigger_type": item.trigger_type,
        "trigger_entity_type": item.trigger_entity_type,
        "trigger_entity_id": item.trigger_entity_id,
        "status": item.status,
        "current_node_key": item.current_node_key,
        "context": _json_object(item.context_json),
        "variables": _json_object(item.variables_json),
        "output": _json_object(item.output_json),
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "next_run_at": item.next_run_at,
        "started_by_id": item.started_by_id,
        "correlation_id": item.correlation_id,
        "last_error": item.last_error,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "cancelled_at": item.cancelled_at,
        "cancelled_by_id": item.cancelled_by_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if steps is not None:
        result["steps"] = [_step_response(step) for step in steps]
    return result


def _approval_response(item: WorkflowApproval) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "execution_id": item.execution_id,
        "step_execution_id": item.step_execution_id,
        "node_key": item.node_key,
        "approver_role": item.approver_role,
        "allow_self_approval": item.allow_self_approval,
        "status": item.status,
        "version": item.version,
        "requested_by_id": item.requested_by_id,
        "decided_by_id": item.decided_by_id,
        "decision_comment": item.decision_comment,
        "requested_at": item.requested_at,
        "expires_at": item.expires_at,
        "decided_at": item.decided_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _conflict(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "invalid" in message.lower() or "must" in message.lower():
        return HTTPException(status_code=422, detail=message)
    return HTTPException(status_code=409, detail=message)


@router.get("/catalog")
def get_workflow_catalog(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.read")
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "node_types": sorted(WORKFLOW_NODE_TYPES),
        "triggers": [
            {
                "code": trigger,
                "label": trigger.replace("_", " ").title(),
            }
            for trigger in WORKFLOW_TRIGGER_CATALOG
        ],
        "actions": [
            {"code": code, **contract}
            for code, contract in sorted(WORKFLOW_ACTION_CATALOG.items())
        ],
        "template_syntax": "${context.ticket.id}",
        "limits": {
            "nodes_per_version": 100,
            "step_retry_attempts": 10,
            "wait_seconds": 2_592_000,
            "approval_timeout_minutes": 43_200,
        },
    }


@router.get("/dashboard")
def get_workflow_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    workflow_counts = dict(
        db.execute(
            select(WorkflowDefinition.status, func.count())
            .where(WorkflowDefinition.tenant_id == scoped_tenant)
            .group_by(WorkflowDefinition.status)
        ).all()
    )
    execution_counts = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(WorkflowExecution.tenant_id == scoped_tenant)
            .group_by(WorkflowExecution.status)
        ).all()
    )
    pending_approvals = int(
        db.scalar(
            select(func.count())
            .select_from(WorkflowApproval)
            .where(
                WorkflowApproval.tenant_id == scoped_tenant,
                WorkflowApproval.status == "PENDING",
            )
        )
        or 0
    )
    return {
        "tenant_id": scoped_tenant,
        "workflows": {
            "total": sum(workflow_counts.values()),
            "by_status": workflow_counts,
        },
        "executions": {
            "total": sum(execution_counts.values()),
            "by_status": execution_counts,
        },
        "pending_approvals": pending_approvals,
        "generated_at": datetime.now(UTC),
    }


@router.get("")
def list_workflows(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    trigger_type: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(WorkflowDefinition).where(
        WorkflowDefinition.tenant_id == scoped_tenant
    )
    if status_filter:
        statement = statement.where(
            WorkflowDefinition.status == status_filter.strip().upper()
        )
    if trigger_type:
        statement = statement.where(
            WorkflowDefinition.trigger_type == trigger_type.strip().lower()
        )
    items = db.scalars(
        statement.order_by(WorkflowDefinition.updated_at.desc())
    ).all()
    return [_workflow_response(item) for item in items]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_workflow(
    payload: WorkflowCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.design")
    tenant_id = _tenant_id(db, current_user, payload.tenant_id)
    try:
        item, version = create_workflow(
            db,
            tenant_id=tenant_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            trigger_type=payload.trigger_type,
            concurrency_policy=payload.concurrency_policy,
            max_active_executions=payload.max_active_executions,
            actor_id=current_user.id,
            publish_approval_required=payload.publish_approval_required,
        )
        _audit(
            db,
            request,
            current_user,
            action="workflow_created",
            entity_type="workflow",
            entity_id=item.id,
            tenant_id=tenant_id,
            metadata={
                "code": item.code,
                "trigger_type": item.trigger_type,
                "draft_version": version.version_number,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Workflow code already exists in this tenant",
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    db.refresh(item)
    return {
        "workflow": _workflow_response(item),
        "draft": _version_response(version),
    }


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.read")
    item = _workflow(db, workflow_id, current_user)
    versions = db.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == item.id)
        .order_by(WorkflowVersion.version_number.desc())
    ).all()
    return {
        "workflow": _workflow_response(item),
        "versions": [
            _version_response(version, include_definition=False)
            for version in versions
        ],
    }


@router.patch("/{workflow_id}")
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.design")
    item = _workflow(db, workflow_id, current_user, lock=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow changed; current revision is {item.revision}",
        )
    before_status = item.status
    before_publish_approval_required = item.publish_approval_required
    if payload.status == "ACTIVE" and item.published_version_number is None:
        raise HTTPException(
            status_code=409,
            detail="Workflow requires a published version before activation",
        )
    if item.status == "ARCHIVED" and payload.status != "ARCHIVED":
        raise HTTPException(
            status_code=409,
            detail="Archived workflow cannot be reactivated",
        )
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.description is not None:
        item.description = payload.description.strip() or None
    if payload.concurrency_policy is not None:
        item.concurrency_policy = payload.concurrency_policy
    if payload.max_active_executions is not None:
        item.max_active_executions = payload.max_active_executions
    if payload.publish_approval_required is not None:
        item.publish_approval_required = payload.publish_approval_required
        if item.draft_version_number is not None:
            draft = _version(db, item, item.draft_version_number, lock=True)
            draft.review_status = (
                "PENDING" if payload.publish_approval_required else "NOT_REQUIRED"
            )
            draft.review_requested_by_id = None
            draft.reviewed_by_id = None
            draft.review_comment = None
            draft.review_requested_at = None
            draft.reviewed_at = None
            draft.revision += 1
            draft.updated_at = datetime.now(UTC)
    if payload.status is not None:
        item.status = payload.status
    item.revision += 1
    item.updated_by_id = current_user.id
    item.updated_at = datetime.now(UTC)
    _audit(
        db,
        request,
        current_user,
        action="workflow_updated",
        entity_type="workflow",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "reason": payload.reason,
            "before_status": before_status,
            "after_status": item.status,
            "before_publish_approval_required": (
                before_publish_approval_required
            ),
            "after_publish_approval_required": (
                item.publish_approval_required
            ),
            "revision": item.revision,
        },
    )
    db.commit()
    db.refresh(item)
    return _workflow_response(item)


@router.get("/{workflow_id}/versions")
def list_workflow_versions(
    workflow_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.read")
    item = _workflow(db, workflow_id, current_user)
    versions = db.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == item.id)
        .order_by(WorkflowVersion.version_number.desc())
    ).all()
    return [
        _version_response(version, include_definition=False)
        for version in versions
    ]


@router.get("/{workflow_id}/versions/compare")
def compare_versions(
    workflow_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "workflows.read")
    item = _workflow(db, workflow_id, current_user)
    source = _version(db, item, from_version)
    target = _version(db, item, to_version)
    try:
        return compare_workflow_versions(source, target)
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.get("/{workflow_id}/versions/{version_number}")
def get_workflow_version(
    workflow_id: str,
    version_number: int,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.read")
    item = _workflow(db, workflow_id, current_user)
    return _version_response(_version(db, item, version_number))


@router.post("/{workflow_id}/versions/{version_number}/review-request")
def request_version_review(
    workflow_id: str,
    version_number: int,
    payload: ReviewRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.reviews.request")
    item = _workflow(db, workflow_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        request_workflow_review(
            version,
            item,
            expected_revision=payload.expected_revision,
            actor_id=current_user.id,
            comment=payload.comment,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_review_requested",
        entity_type="workflow_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "version_number": version.version_number,
            "comment": payload.comment,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version)


@router.post("/{workflow_id}/versions/{version_number}/review-decision")
def decide_version_review(
    workflow_id: str,
    version_number: int,
    payload: ReviewDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.reviews.decide")
    item = _workflow(db, workflow_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        decide_workflow_review(
            version,
            item,
            expected_revision=payload.expected_revision,
            actor_id=current_user.id,
            decision=payload.decision,
            comment=payload.comment,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_review_decided",
        entity_type="workflow_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "version_number": version.version_number,
            "decision": payload.decision,
            "comment": payload.comment,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version)


@router.post("/{workflow_id}/drafts", status_code=status.HTTP_201_CREATED)
def add_workflow_draft(
    workflow_id: str,
    payload: DraftCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.design")
    item = _workflow(db, workflow_id, current_user, lock=True)
    if item.revision != payload.expected_workflow_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow changed; current revision is {item.revision}",
        )
    try:
        version = create_workflow_draft(
            db,
            item,
            actor_id=current_user.id,
            change_summary=payload.change_summary,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_draft_created",
        entity_type="workflow_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "version_number": version.version_number,
            "change_summary": payload.change_summary,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version)


@router.put("/{workflow_id}/versions/{version_number}")
def save_workflow_draft(
    workflow_id: str,
    version_number: int,
    payload: DraftUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.design")
    item = _workflow(db, workflow_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        validation = update_workflow_draft(
            version,
            item,
            definition=payload.definition,
            expected_revision=payload.expected_revision,
            change_summary=payload.change_summary,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_draft_saved",
        entity_type="workflow_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "version_number": version.version_number,
            "revision": version.revision,
            "valid": bool(validation["valid"]),
            "change_summary": payload.change_summary,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version)


@router.post("/{workflow_id}/versions/{version_number}/validate")
def validate_workflow_version(
    workflow_id: str,
    version_number: int,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "workflows.read")
    item = _workflow(db, workflow_id, current_user)
    version = _version(db, item, version_number)
    if not _version_integrity_valid(version):
        raise HTTPException(
            status_code=409,
            detail="Workflow version integrity check failed",
        )
    return validate_workflow_definition(
        _json_object(version.definition_json),
        expected_trigger_type=item.trigger_type,
    )


@router.post("/{workflow_id}/versions/{version_number}/simulate")
def simulate_workflow_version(
    workflow_id: str,
    version_number: int,
    payload: SimulationRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "workflows.execute")
    item = _workflow(db, workflow_id, current_user)
    version = _version(db, item, version_number)
    if not _version_integrity_valid(version):
        raise HTTPException(
            status_code=409,
            detail="Workflow version integrity check failed",
        )
    try:
        return simulate_workflow(
            _json_object(version.definition_json),
            payload.context,
            expected_trigger_type=item.trigger_type,
        )
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.post("/{workflow_id}/versions/{version_number}/publish")
def publish_workflow(
    workflow_id: str,
    version_number: int,
    payload: PublishRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.publish")
    item = _workflow(db, workflow_id, current_user, lock=True)
    version = _version(db, item, version_number, lock=True)
    try:
        publish_workflow_version(
            db,
            item,
            version,
            expected_workflow_revision=payload.expected_workflow_revision,
            expected_version_revision=payload.expected_version_revision,
            actor_id=current_user.id,
            activate=payload.activate,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_published",
        entity_type="workflow_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "version_number": version.version_number,
            "activate": payload.activate,
            "change_ticket": payload.change_ticket,
            "definition_sha256": version.definition_sha256,
        },
    )
    db.commit()
    db.refresh(item)
    db.refresh(version)
    return {
        "workflow": _workflow_response(item),
        "version": _version_response(version),
    }


@router.post("/{workflow_id}/rollback")
def rollback_published_workflow(
    workflow_id: str,
    payload: RollbackRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.publish")
    item = _workflow(db, workflow_id, current_user, lock=True)
    target = _version(db, item, payload.target_version_number, lock=True)
    try:
        restored = rollback_workflow(
            db,
            item,
            target,
            expected_workflow_revision=payload.expected_workflow_revision,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_rolled_back",
        entity_type="workflow_version",
        entity_id=restored.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "target_version_number": target.version_number,
            "restored_version_number": restored.version_number,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(item)
    db.refresh(restored)
    return {
        "workflow": _workflow_response(item),
        "version": _version_response(restored),
    }


@router.get("/executions/list")
def list_workflow_executions(
    tenant_id: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.executions.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(WorkflowExecution).where(
        WorkflowExecution.tenant_id == scoped_tenant
    )
    if workflow_id:
        statement = statement.where(WorkflowExecution.workflow_id == workflow_id)
    if status_filter:
        statement = statement.where(
            WorkflowExecution.status == status_filter.strip().upper()
        )
    items = db.scalars(
        statement.order_by(WorkflowExecution.created_at.desc()).limit(limit)
    ).all()
    return [_execution_response(item) for item in items]


@router.get("/executions/{execution_id}")
def get_workflow_execution(
    execution_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.executions.read")
    item = _execution(db, execution_id, current_user)
    steps = db.scalars(
        select(WorkflowStepExecution)
        .where(WorkflowStepExecution.execution_id == item.id)
        .order_by(WorkflowStepExecution.sequence_number)
    ).all()
    return _execution_response(item, steps=list(steps))


@router.get("/executions/{execution_id}/events")
def get_workflow_execution_events(
    execution_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.executions.read")
    item = _execution(db, execution_id, current_user)
    events = db.scalars(
        select(WorkflowExecutionEvent)
        .where(WorkflowExecutionEvent.execution_id == item.id)
        .order_by(WorkflowExecutionEvent.sequence_number)
    ).all()
    return [
        {
            "id": event.id,
            "sequence_number": event.sequence_number,
            "event_type": event.event_type,
            "node_key": event.node_key,
            "status": event.status,
            "details": _json_object(event.details_json),
            "previous_hash": event.previous_hash,
            "event_hash": event.event_hash,
            "created_at": event.created_at,
        }
        for event in events
    ]


@router.get("/executions/{execution_id}/events/verify")
def verify_workflow_execution_events(
    execution_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "workflows.executions.read")
    item = _execution(db, execution_id, current_user)
    return verify_workflow_event_chain(db, item.id)


@router.post("/{workflow_id}/executions", status_code=status.HTTP_202_ACCEPTED)
def start_workflow_execution(
    workflow_id: str,
    payload: ExecutionStart,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.execute")
    item = _workflow(db, workflow_id, current_user, lock=True)
    if item.published_version_number is None:
        raise HTTPException(
            status_code=409,
            detail="Workflow has no published version",
        )
    try:
        execution, deduplicated = enqueue_workflow_execution(
            db,
            item,
            context=payload.context,
            idempotency_key=payload.idempotency_key,
            source="MANUAL",
            actor_id=current_user.id,
            correlation_id=payload.correlation_id,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_execution_requested",
        entity_type="workflow_execution",
        entity_id=execution.id,
        tenant_id=item.tenant_id,
        metadata={
            "workflow_id": item.id,
            "deduplicated": deduplicated,
            "idempotency_key": payload.idempotency_key,
        },
    )
    db.commit()
    db.refresh(execution)
    return {
        "execution": _execution_response(execution),
        "deduplicated": deduplicated,
    }


@router.post("/executions/{execution_id}/cancel")
def cancel_execution(
    execution_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.executions.manage")
    item = _execution(db, execution_id, current_user, lock=True)
    try:
        cancel_workflow_execution(
            db,
            item,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_execution_cancelled",
        entity_type="workflow_execution",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _execution_response(item)


@router.post(
    "/executions/{execution_id}/replay",
    status_code=status.HTTP_202_ACCEPTED,
)
def replay_execution(
    execution_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.executions.manage")
    item = _execution(db, execution_id, current_user, lock=True)
    workflow = _workflow(db, item.workflow_id, current_user, lock=True)
    try:
        replay = replay_workflow_execution(
            db,
            item,
            workflow,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except ValueError as exc:
        db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_execution_replayed",
        entity_type="workflow_execution",
        entity_id=replay.id,
        tenant_id=item.tenant_id,
        metadata={
            "original_execution_id": item.id,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(replay)
    return _execution_response(replay)


@router.get("/reviews/list")
def list_workflow_reviews(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default="PENDING", alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.reviews.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = (
        select(WorkflowVersion, WorkflowDefinition)
        .join(
            WorkflowDefinition,
            WorkflowDefinition.id == WorkflowVersion.workflow_id,
        )
        .where(
            WorkflowVersion.tenant_id == scoped_tenant,
            WorkflowVersion.review_requested_at.is_not(None),
        )
    )
    if status_filter:
        statement = statement.where(
            WorkflowVersion.review_status == status_filter.strip().upper()
        )
    rows = db.execute(
        statement.order_by(WorkflowVersion.review_requested_at.desc()).limit(limit)
    ).all()
    return [
        {
            **_version_response(version, include_definition=False),
            "workflow_name": workflow.name,
            "workflow_code": workflow.code,
            "publish_approval_required": workflow.publish_approval_required,
        }
        for version, workflow in rows
    ]


@router.get("/approvals/list")
def list_workflow_approvals(
    tenant_id: str | None = Query(default=None),
    status_filter: str | None = Query(default="PENDING", alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_permissions(current_user, "workflows.approvals.read")
    scoped_tenant = _tenant_id(db, current_user, tenant_id)
    statement = select(WorkflowApproval).where(
        WorkflowApproval.tenant_id == scoped_tenant
    )
    if status_filter:
        statement = statement.where(
            WorkflowApproval.status == status_filter.strip().upper()
        )
    if not is_saas_root(current_user) and not has_permission(
        current_user,
        "workflows.approvals.override",
    ):
        statement = statement.where(
            WorkflowApproval.approver_role == current_user.role
        )
    items = db.scalars(
        statement.order_by(WorkflowApproval.requested_at.desc()).limit(limit)
    ).all()
    return [_approval_response(item) for item in items]


@router.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "workflows.approvals.decide")
    approval_reference = _approval(db, approval_id, current_user)
    execution = _execution(
        db,
        approval_reference.execution_id,
        current_user,
        lock=True,
    )
    approval = _approval(db, approval_id, current_user, lock=True)
    if approval.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Approval changed; current version is {approval.version}",
        )
    if (
        current_user.role != approval.approver_role
        and not is_saas_root(current_user)
        and not has_permission(current_user, "workflows.approvals.override")
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Approval requires role {approval.approver_role}",
        )
    try:
        decide_workflow_approval(
            db,
            approval,
            decision=payload.decision,
            comment=payload.comment,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        if approval.status == "EXPIRED":
            db.commit()
        else:
            db.rollback()
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        current_user,
        action="workflow_approval_decided",
        entity_type="workflow_approval",
        entity_id=approval.id,
        tenant_id=approval.tenant_id,
        metadata={
            "execution_id": execution.id,
            "decision": payload.decision,
            "approver_role": approval.approver_role,
        },
    )
    db.commit()
    db.refresh(approval)
    return _approval_response(approval)
