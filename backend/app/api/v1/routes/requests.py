from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.catalog_form import CatalogFormVersion
from app.models.role import Role
from app.models.service_catalog import CatalogItem
from app.models.service_request import (
    FulfillmentTask,
    RequestActivity,
    RequestApproval,
    RequestedItem,
    ServiceRequest,
)
from app.models.user import User
from app.services.audit import log_audit
from app.services.catalog_forms import validate_submission
from app.services.catalog_governance import (
    add_service_minutes,
    approval_decision,
    entitlement_decision,
    normalize_entitlement_rules,
    normalize_sla_policy,
    sla_status,
)
from app.services.catalog_personalization import touch_catalog_preference
from app.services.rbac import has_permission, is_saas_root, require_permissions
from app.services.request_fulfillment import (
    REQUEST_TERMINAL_STATUSES,
    TASK_TRANSITIONS,
    add_activity,
    create_approval_round,
    create_task,
    json_object,
    refresh_request_status,
    request_number,
    utc_now,
)


router = APIRouter(prefix="/requests")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AttachmentMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=104_857_600)
    content_type: str | None = Field(default=None, max_length=160)


class ServiceRequestCreate(BaseModel):
    catalog_item_id: str
    form_version: int = Field(ge=1)
    schema_hash: str = Field(min_length=64, max_length=64)
    values: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentMetadata] = Field(default_factory=list, max_length=20)
    quantity: int = Field(default=1, ge=1, le=100)
    idempotency_key: str = Field(min_length=8, max_length=120)
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    approval_mode: Literal["SEQUENTIAL", "PARALLEL"] = "SEQUENTIAL"


class RequestCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    is_internal: bool = False


class RequestCancel(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class RequestedItemRework(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class ApprovalDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    comment: str | None = Field(default=None, max_length=5_000)


class TaskAssignment(BaseModel):
    expected_version: int = Field(ge=1)
    assignee_id: str | None = None
    comment: str | None = Field(default=None, max_length=2_000)


class TaskTransition(BaseModel):
    expected_version: int = Field(ge=1)
    target_status: Literal[
        "OPEN",
        "IN_PROGRESS",
        "WAITING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ]
    comment: str | None = Field(default=None, max_length=5_000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SlaControl(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


def _client_ip(http_request: Request) -> str | None:
    return http_request.client.host if http_request.client else None


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _ensure_tenant(entity: Any, current_user: AuthUserResponse, label: str) -> Any:
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if not is_saas_root(current_user) and entity.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return entity


def _request_visibility_scopes(current_user: AuthUserResponse) -> frozenset[str]:
    if is_saas_root(current_user):
        return frozenset({"all"})
    scopes = {
        scope
        for scope in ("all", "requester")
        if has_permission(current_user, f"requests.scope.{scope}")
    }
    if any(
        has_permission(current_user, permission)
        for permission in (
            "requests.manage",
            "requests.fulfill",
            "requests.approve",
        )
    ):
        scopes.add("all")
    return frozenset(scopes)


def _is_requester_only(current_user: AuthUserResponse) -> bool:
    scopes = _request_visibility_scopes(current_user)
    return "requester" in scopes and "all" not in scopes


def _ensure_request_read(
    service_request: ServiceRequest,
    current_user: AuthUserResponse,
) -> None:
    _ensure_tenant(service_request, current_user, "Service request")
    scopes = _request_visibility_scopes(current_user)
    requested_by_current = (
        service_request.requester_id == current_user.id
        or service_request.requester_email.lower() == current_user.email.lower()
    )
    if "all" not in scopes and not (
        "requester" in scopes and requested_by_current
    ):
        raise HTTPException(status_code=404, detail="Service request not found")


def _can_manage_request(
    service_request: ServiceRequest,
    current_user: AuthUserResponse,
) -> bool:
    if has_permission(current_user, "requests.manage"):
        return True
    return (
        service_request.requester_id == current_user.id
        or service_request.requester_email.lower() == current_user.email.lower()
    )


def _item_sla_policy(item: RequestedItem) -> dict[str, Any]:
    return normalize_sla_policy(
        json_object(item.sla_policy_snapshot_json),
        default_target_minutes=1440,
    )


def _refresh_item_sla(item: RequestedItem, *, now=None) -> str:
    if item.status in {"CANCELLED", "REJECTED"}:
        item.sla_status = item.status
        return item.status
    timestamp = now or utc_now()
    policy = _item_sla_policy(item)
    state = sla_status(
        started_at=item.sla_started_at,
        due_at=item.sla_due_at,
        paused_at=item.sla_paused_at,
        completed_at=item.completed_at,
        breached_at=item.sla_breached_at,
        policy=policy,
        now=timestamp,
    )
    if state == "BREACHED" and item.sla_breached_at is None:
        item.sla_breached_at = timestamp
    item.sla_status = state
    return state


def _pause_item_sla(
    db: Session,
    service_request: ServiceRequest,
    item: RequestedItem,
    *,
    actor: Any,
    reason: str,
) -> bool:
    policy = _item_sla_policy(item)
    if not policy["pause_on_waiting"] or item.sla_paused_at is not None:
        return False
    if item.status in {"COMPLETED", "CANCELLED", "REJECTED"}:
        return False
    item.sla_paused_at = utc_now()
    item.sla_status = "PAUSED"
    add_activity(
        db,
        service_request,
        actor=actor,
        requested_item_id=item.id,
        entity_type="requested_item",
        entity_id=item.id,
        event_type="sla.paused",
        message=f"SLA приостановлен: {reason}",
        new_value={"status": "PAUSED", "reason": reason},
    )
    return True


def _resume_item_sla(
    db: Session,
    service_request: ServiceRequest,
    item: RequestedItem,
    *,
    actor: Any,
    reason: str,
) -> bool:
    if item.sla_paused_at is None:
        return False
    now = utc_now()
    paused_seconds = max(
        0,
        int((now - _as_utc(item.sla_paused_at)).total_seconds()),
    )
    shift = timedelta(seconds=paused_seconds)
    item.sla_paused_seconds += paused_seconds
    item.sla_paused_at = None
    if item.sla_due_at is not None:
        item.sla_due_at += shift
    for task in db.scalars(
        select(FulfillmentTask).where(
            FulfillmentTask.requested_item_id == item.id,
            FulfillmentTask.status.notin_(["COMPLETED", "CANCELLED"]),
        )
    ).all():
        if task.due_at is not None:
            task.due_at += shift
    _refresh_item_sla(item, now=now)
    add_activity(
        db,
        service_request,
        actor=actor,
        requested_item_id=item.id,
        entity_type="requested_item",
        entity_id=item.id,
        event_type="sla.resumed",
        message=f"SLA возобновлён: {reason}",
        new_value={
            "status": item.sla_status,
            "paused_seconds": paused_seconds,
            "due_at": item.sla_due_at.isoformat() if item.sla_due_at else None,
        },
    )
    return True


def _approvers(
    db: Session,
    *,
    tenant_id: str,
    requester_id: str | None,
    role_codes: list[str] | None = None,
) -> list[User]:
    statement = (
        select(User)
        .join(Role, Role.id == User.role_id)
        .where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            Role.code.in_(role_codes or ["organization_admin", "it_manager"]),
        )
        .order_by(User.full_name.asc(), User.email.asc())
    )
    if requester_id:
        statement = statement.where(User.id != requester_id)
    return list(db.scalars(statement).all())


def _activity_payload(activity: RequestActivity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "requested_item_id": activity.requested_item_id,
        "entity_type": activity.entity_type,
        "entity_id": activity.entity_id,
        "event_type": activity.event_type,
        "actor_user_id": activity.actor_user_id,
        "actor_name": activity.actor_name,
        "actor_email": activity.actor_email,
        "visibility": activity.visibility,
        "message": activity.message,
        "old_value": json_object(activity.old_value_json),
        "new_value": json_object(activity.new_value_json),
        "created_at": activity.created_at,
    }


def _approval_payload(
    approval: RequestApproval,
    current_user: AuthUserResponse,
) -> dict[str, Any]:
    can_decide = (
        approval.status == "PENDING"
        and has_permission(current_user, "requests.approve")
        and (
            approval.approver_id is None
            or approval.approver_id == current_user.id
            or has_permission(current_user, "requests.manage")
        )
    )
    return {
        "id": approval.id,
        "requested_item_id": approval.requested_item_id,
        "round": approval.round,
        "sequence": approval.sequence,
        "approval_mode": approval.approval_mode,
        "approver_id": approval.approver_id,
        "approver_name": approval.approver_name,
        "approver_email": approval.approver_email,
        "status": approval.status,
        "comment": approval.comment,
        "due_at": approval.due_at,
        "decided_at": approval.decided_at,
        "created_at": approval.created_at,
        "updated_at": approval.updated_at,
        "can_decide": can_decide,
    }


def _task_payload(
    task: FulfillmentTask,
    current_user: AuthUserResponse,
) -> dict[str, Any]:
    manager = has_permission(current_user, "requests.manage")
    can_fulfill = has_permission(current_user, "requests.fulfill") and (
        manager or task.assignee_id is None or task.assignee_id == current_user.id
    )
    return {
        "id": task.id,
        "requested_item_id": task.requested_item_id,
        "task_number": task.task_number,
        "sequence": task.sequence,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "version": task.version,
        "assignee_id": task.assignee_id,
        "assignee_name": task.assignee_name,
        "support_group": task.support_group,
        "due_at": task.due_at,
        "evidence": json_object(task.evidence_json),
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "can_fulfill": can_fulfill,
        "allowed_transitions": (
            sorted(TASK_TRANSITIONS.get(task.status, set())) if can_fulfill else []
        ),
    }


def _item_payload(
    item: RequestedItem,
    *,
    field_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    sla_policy = json_object(item.sla_policy_snapshot_json)
    current_sla_status = (
        item.status
        if item.status in {"CANCELLED", "REJECTED"}
        else sla_status(
            started_at=item.sla_started_at,
            due_at=item.sla_due_at,
            paused_at=item.sla_paused_at,
            completed_at=item.completed_at,
            breached_at=item.sla_breached_at,
            policy=sla_policy,
        )
    )
    return {
        "id": item.id,
        "catalog_item_id": item.catalog_item_id,
        "catalog_form_version_id": item.catalog_form_version_id,
        "item_code": item.item_code,
        "item_name": item.item_name,
        "quantity": item.quantity,
        "status": item.status,
        "version": item.version,
        "form_version": item.form_version,
        "schema_hash": item.schema_hash,
        "form_values": json_object(item.form_values_json),
        "field_labels": field_labels or {},
        "support_group": item.support_group,
        "approval_required": item.approval_required,
        "approval_mode": item.approval_mode,
        "unit_cost_minor": item.unit_cost_minor,
        "total_cost_minor": item.total_cost_minor,
        "currency": item.currency,
        "cost_type": item.cost_type,
        "cost_center": item.cost_center,
        "risk_level": item.risk_level,
        "entitlement_snapshot": json_object(item.entitlement_snapshot_json),
        "approval_policy_snapshot": json_object(
            item.approval_policy_snapshot_json
        ),
        "sla_policy_snapshot": sla_policy,
        "sla_started_at": item.sla_started_at,
        "sla_due_at": item.sla_due_at,
        "sla_paused_at": item.sla_paused_at,
        "sla_paused_seconds": item.sla_paused_seconds,
        "sla_status": current_sla_status,
        "sla_breached_at": item.sla_breached_at,
        "sla_escalation_level": item.sla_escalation_level,
        "expected_delivery_at": item.expected_delivery_at,
        "completed_at": item.completed_at,
        "cancelled_at": item.cancelled_at,
        "rejected_at": item.rejected_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _summary_payload(service_request: ServiceRequest) -> dict[str, Any]:
    return {
        "id": service_request.id,
        "tenant_id": service_request.tenant_id,
        "request_number": service_request.request_number,
        "requester_id": service_request.requester_id,
        "requester_name": service_request.requester_name,
        "requester_email": service_request.requester_email,
        "title": service_request.title,
        "description": service_request.description,
        "source": service_request.source,
        "status": service_request.status,
        "priority": service_request.priority,
        "requester_department": service_request.requester_department,
        "requester_location": service_request.requester_location,
        "cost_center": service_request.cost_center,
        "total_cost_minor": service_request.total_cost_minor,
        "currency": service_request.currency,
        "risk_level": service_request.risk_level,
        "version": service_request.version,
        "completed_at": service_request.completed_at,
        "cancelled_at": service_request.cancelled_at,
        "rejected_at": service_request.rejected_at,
        "created_at": service_request.created_at,
        "updated_at": service_request.updated_at,
    }


def _detail_payload(
    db: Session,
    service_request: ServiceRequest,
    current_user: AuthUserResponse,
) -> dict[str, Any]:
    items = db.scalars(
        select(RequestedItem)
        .where(RequestedItem.request_id == service_request.id)
        .order_by(RequestedItem.created_at.asc())
    ).all()
    form_ids = {
        item.catalog_form_version_id
        for item in items
        if item.catalog_form_version_id is not None
    }
    form_field_labels: dict[str, dict[str, str]] = {}
    if form_ids:
        forms = db.scalars(
            select(CatalogFormVersion).where(CatalogFormVersion.id.in_(form_ids))
        ).all()
        for form in forms:
            schema = json_object(form.schema_json)
            labels: dict[str, str] = {}
            for field in schema.get("fields", []):
                if not isinstance(field, dict):
                    continue
                key = field.get("key")
                label = field.get("label")
                if isinstance(key, str) and isinstance(label, str) and label.strip():
                    labels[key] = label.strip()
            form_field_labels[form.id] = labels
    approvals = db.scalars(
        select(RequestApproval)
        .where(RequestApproval.request_id == service_request.id)
        .order_by(
            RequestApproval.round.asc(),
            RequestApproval.sequence.asc(),
            RequestApproval.created_at.asc(),
        )
    ).all()
    tasks = db.scalars(
        select(FulfillmentTask)
        .where(FulfillmentTask.request_id == service_request.id)
        .order_by(FulfillmentTask.sequence.asc(), FulfillmentTask.created_at.asc())
    ).all()
    activity_statement = (
        select(RequestActivity)
        .where(RequestActivity.request_id == service_request.id)
        .order_by(RequestActivity.created_at.asc(), RequestActivity.id.asc())
    )
    if _is_requester_only(current_user):
        activity_statement = activity_statement.where(
            RequestActivity.visibility == "PUBLIC"
        )
    activities = db.scalars(activity_statement).all()
    payload = _summary_payload(service_request)
    payload.update(
        {
            "items": [
                _item_payload(
                    item,
                    field_labels=form_field_labels.get(
                        item.catalog_form_version_id or "", {}
                    ),
                )
                for item in items
            ],
            "approvals": [
                _approval_payload(approval, current_user) for approval in approvals
            ],
            "tasks": [_task_payload(task, current_user) for task in tasks],
            "activities": [_activity_payload(activity) for activity in activities],
            "can_cancel": (
                service_request.status not in REQUEST_TERMINAL_STATUSES
                and _can_manage_request(service_request, current_user)
            ),
        }
    )
    return payload


@router.post("", status_code=status.HTTP_201_CREATED)
def create_service_request(
    payload: ServiceRequestCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.create")
    item = _ensure_tenant(
        db.get(CatalogItem, payload.catalog_item_id),
        current_user,
        "Catalog item",
    )
    if item.lifecycle_status != "PUBLISHED":
        raise HTTPException(status_code=422, detail="Catalog item is not published")
    existing = db.scalar(
        select(ServiceRequest).where(
            ServiceRequest.tenant_id == item.tenant_id,
            ServiceRequest.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        _ensure_request_read(existing, current_user)
        return _detail_payload(db, existing, current_user)

    requester = _actor(db, current_user)
    entitled, entitlement_reason = entitlement_decision(
        item,
        user=requester,
        fallback_user_id=current_user.id,
        fallback_tenant_id=current_user.tenant_id,
        fallback_role=current_user.role,
        bypass=is_saas_root(current_user),
    )
    if not entitled:
        raise HTTPException(
            status_code=403,
            detail=f"Catalog entitlement denied: {entitlement_reason}",
        )

    form = db.scalar(
        select(CatalogFormVersion).where(
            CatalogFormVersion.catalog_item_id == item.id,
            CatalogFormVersion.version == payload.form_version,
            CatalogFormVersion.status == "PUBLISHED",
        )
    )
    if form is None or form.schema_hash != payload.schema_hash:
        raise HTTPException(
            status_code=409,
            detail="Published form version changed; refresh the catalog form",
        )
    schema = json.loads(form.schema_json)
    attachment_rules = json.loads(form.attachment_rules_json)
    attachments = [entry.model_dump() for entry in payload.attachments]
    errors, normalized_values, _ = validate_submission(
        schema,
        attachment_rules,
        payload.values,
        attachments,
    )
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Catalog form validation failed", "errors": errors},
        )

    now = utc_now()
    total_cost_minor = item.unit_cost_minor * payload.quantity
    approval_required, approval_policy, approval_reasons = approval_decision(
        item,
        total_cost_minor=total_cost_minor,
    )
    sla_policy = normalize_sla_policy(
        json_object(item.sla_policy_json),
        default_target_minutes=item.expected_delivery_minutes,
    )
    sla_due_at = add_service_minutes(
        now,
        int(sla_policy["target_minutes"]),
        str(sla_policy["calendar_code"]),
    )
    requester_department = requester.department if requester else None
    requester_location = requester.location if requester else None
    cost_center = requester.cost_center if requester else None
    service_request = ServiceRequest(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        request_number=request_number(now),
        idempotency_key=payload.idempotency_key,
        requester_id=current_user.id,
        requester_name=current_user.full_name,
        requester_email=current_user.email,
        title=(payload.title or item.name).strip(),
        description=payload.description or item.short_description,
        source="CATALOG",
        status="SUBMITTED",
        priority=payload.priority,
        requester_department=requester_department,
        requester_location=requester_location,
        cost_center=cost_center,
        total_cost_minor=total_cost_minor,
        currency=item.currency,
        risk_level=item.risk_level,
        version=1,
    )
    requested_item = RequestedItem(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        request_id=service_request.id,
        catalog_item_id=item.id,
        catalog_form_version_id=form.id,
        item_code=item.code,
        item_name=item.name,
        quantity=payload.quantity,
        status="SUBMITTED",
        version=1,
        form_version=form.version,
        schema_hash=form.schema_hash,
        form_values_json=json.dumps(
            normalized_values, ensure_ascii=False, sort_keys=True
        ),
        support_group=item.support_group,
        approval_required=approval_required,
        approval_mode=str(approval_policy["mode"]),
        unit_cost_minor=item.unit_cost_minor,
        total_cost_minor=total_cost_minor,
        currency=item.currency,
        cost_type=item.cost_type,
        cost_center=cost_center,
        risk_level=item.risk_level,
        entitlement_snapshot_json=json.dumps(
            {
                "rules": normalize_entitlement_rules(
                    json_object(item.entitlement_rules_json)
                ),
                "decision": "ALLOWED",
                "reason": entitlement_reason,
                "requester": {
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id,
                    "role": current_user.role,
                    "department": requester_department,
                    "location": requester_location,
                    "cost_center": cost_center,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        approval_policy_snapshot_json=json.dumps(
            {
                **approval_policy,
                "decision": approval_required,
                "reasons": approval_reasons,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        sla_policy_snapshot_json=json.dumps(
            sla_policy, ensure_ascii=False, sort_keys=True
        ),
        sla_started_at=now,
        sla_due_at=sla_due_at,
        sla_status="ACTIVE",
        expected_delivery_at=sla_due_at,
    )
    # The aggregate is intentionally modeled without broad ORM relationships,
    # so SQLAlchemy cannot infer insert dependencies. Persist each parent level
    # explicitly to guarantee FK-safe ordering on PostgreSQL.
    db.add(service_request)
    db.flush()
    db.add(requested_item)
    db.flush()
    add_activity(
        db,
        service_request,
        actor=current_user,
        entity_type="service_request",
        entity_id=service_request.id,
        event_type="request.created",
        message=f"Создана заявка {service_request.request_number}",
        new_value={
            "catalog_item": item.code,
            "form_version": form.version,
            "schema_hash": form.schema_hash,
            "cost": {
                "unit_minor": item.unit_cost_minor,
                "total_minor": total_cost_minor,
                "currency": item.currency,
                "cost_center": cost_center,
            },
            "risk_level": item.risk_level,
            "sla_due_at": sla_due_at.isoformat(),
        },
    )
    if approval_required:
        create_approval_round(
            db,
            service_request,
            requested_item,
            actor=current_user,
            approvers=_approvers(
                db,
                tenant_id=item.tenant_id,
                requester_id=current_user.id,
                role_codes=list(approval_policy["approver_roles"]),
            ),
            due_minutes=int(approval_policy["due_minutes"]),
        )
    else:
        requested_item.status = "APPROVED"
        create_task(
            db,
            service_request,
            requested_item,
            actor=current_user,
        )
    touch_catalog_preference(
        db,
        tenant_id=item.tenant_id,
        user_id=current_user.id,
        catalog_item_id=item.id,
        requested=True,
    )
    log_audit(
        db,
        action="service_request.created",
        entity_type="service_request",
        entity_id=service_request.id,
        actor_user=_actor(db, current_user),
        tenant_id=item.tenant_id,
        ip_address=_client_ip(http_request),
        user_agent=http_request.headers.get("user-agent"),
        metadata={
            "request_number": service_request.request_number,
            "catalog_item_id": item.id,
            "form_version": form.version,
            "total_cost_minor": total_cost_minor,
            "currency": item.currency,
            "risk_level": item.risk_level,
            "approval_reasons": approval_reasons,
            "sla_due_at": sla_due_at.isoformat(),
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ServiceRequest).where(
                ServiceRequest.tenant_id == item.tenant_id,
                ServiceRequest.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None:
            raise
        return _detail_payload(db, existing, current_user)
    created = db.get(ServiceRequest, service_request.id)
    return _detail_payload(db, created, current_user)


@router.get("")
def list_service_requests(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    search: str | None = Query(default=None, max_length=200),
    request_status: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    require_permissions(current_user, "requests.read")
    filters = []
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        filters.append(ServiceRequest.tenant_id == current_user.tenant_id)
    scopes = _request_visibility_scopes(current_user)
    if "all" not in scopes:
        if "requester" in scopes:
            filters.append(
                or_(
                    ServiceRequest.requester_id == current_user.id,
                    func.lower(ServiceRequest.requester_email)
                    == current_user.email.lower(),
                )
            )
        else:
            filters.append(ServiceRequest.id.is_(None))
    if request_status:
        filters.append(ServiceRequest.status == request_status.strip().upper())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        filters.append(
            or_(
                func.lower(ServiceRequest.request_number).like(term),
                func.lower(ServiceRequest.title).like(term),
                func.lower(ServiceRequest.requester_name).like(term),
                func.lower(ServiceRequest.requester_email).like(term),
            )
        )
    statement = select(ServiceRequest).where(*filters)
    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    rows = db.scalars(
        statement.order_by(ServiceRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_summary_payload(entry) for entry in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.get("/analytics/governance")
def request_governance_analytics(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.manage")
    request_statement = select(ServiceRequest)
    item_statement = select(RequestedItem)
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        request_statement = request_statement.where(
            ServiceRequest.tenant_id == current_user.tenant_id
        )
        item_statement = item_statement.where(
            RequestedItem.tenant_id == current_user.tenant_id
        )
    requests = list(db.scalars(request_statement).all())
    items = list(db.scalars(item_statement).all())
    currency_totals: dict[str, int] = {}
    cost_centers: dict[str, dict[str, int]] = {}
    demand: dict[str, dict[str, Any]] = {}
    sla_counts: dict[str, int] = {}
    completed_durations: list[float] = []
    approved_items = 0
    for service_request in requests:
        currency_totals[service_request.currency] = (
            currency_totals.get(service_request.currency, 0)
            + service_request.total_cost_minor
        )
        center = service_request.cost_center or "UNASSIGNED"
        center_row = cost_centers.setdefault(
            center,
            {"requests": 0, "total_cost_minor": 0},
        )
        center_row["requests"] += 1
        center_row["total_cost_minor"] += service_request.total_cost_minor
        if service_request.completed_at is not None:
            created = _as_utc(service_request.created_at)
            completed = _as_utc(service_request.completed_at)
            completed_durations.append((completed - created).total_seconds() / 3600)
    for item in items:
        state = _refresh_item_sla(item)
        sla_counts[state] = sla_counts.get(state, 0) + 1
        row = demand.setdefault(
            item.item_code,
            {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "request_count": 0,
                "quantity": 0,
                "total_cost_minor": 0,
                "currency": item.currency,
            },
        )
        row["request_count"] += 1
        row["quantity"] += item.quantity
        row["total_cost_minor"] += item.total_cost_minor
        if item.approval_required:
            approved_items += 1
    return {
        "total_requests": len(requests),
        "total_requested_items": len(items),
        "currency_totals": currency_totals,
        "cost_centers": [
            {"cost_center": key, **value}
            for key, value in sorted(
                cost_centers.items(),
                key=lambda entry: (-entry[1]["total_cost_minor"], entry[0]),
            )
        ],
        "demand_by_item": sorted(
            demand.values(),
            key=lambda entry: (-entry["request_count"], entry["item_name"]),
        )[:20],
        "sla": sla_counts,
        "approval_required_items": approved_items,
        "approval_rate_percent": round(approved_items / len(items) * 100, 2)
        if items
        else 0.0,
        "average_fulfillment_hours": round(
            sum(completed_durations) / len(completed_durations),
            2,
        )
        if completed_durations
        else None,
    }


@router.post("/sla/evaluate")
def evaluate_request_sla(
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.manage")
    statement = select(RequestedItem).where(
        RequestedItem.status.notin_(["COMPLETED", "CANCELLED", "REJECTED"])
    )
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        statement = statement.where(RequestedItem.tenant_id == current_user.tenant_id)
    now = utc_now()
    changed: list[dict[str, Any]] = []
    for item in db.scalars(statement).all():
        old_status = item.sla_status
        old_level = item.sla_escalation_level
        state = _refresh_item_sla(item, now=now)
        policy = _item_sla_policy(item)
        overdue_minutes = (
            max(0, int((now - _as_utc(item.sla_due_at)).total_seconds() // 60))
            if item.sla_due_at and state == "BREACHED"
            else 0
        )
        level = sum(
            1
            for threshold in policy["escalation_minutes"]
            if overdue_minutes >= int(threshold)
        )
        item.sla_escalation_level = level
        if state != old_status or level != old_level:
            service_request = db.get(ServiceRequest, item.request_id)
            add_activity(
                db,
                service_request,
                actor=current_user,
                requested_item_id=item.id,
                entity_type="requested_item",
                entity_id=item.id,
                event_type="sla.evaluated",
                message=(
                    f"SLA: {old_status} → {state}; уровень эскалации {level}"
                ),
                old_value={"status": old_status, "escalation_level": old_level},
                new_value={
                    "status": state,
                    "escalation_level": level,
                    "overdue_minutes": overdue_minutes,
                },
            )
            changed.append(
                {
                    "requested_item_id": item.id,
                    "status": state,
                    "escalation_level": level,
                }
            )
    log_audit(
        db,
        action="service_request.sla_evaluated",
        entity_type="requested_item",
        entity_id=None,
        actor_user=_actor(db, current_user),
        tenant_id=current_user.tenant_id,
        ip_address=_client_ip(http_request),
        user_agent=http_request.headers.get("user-agent"),
        metadata={"changed": len(changed)},
    )
    db.commit()
    return {"evaluated_at": now, "changed": changed, "changed_count": len(changed)}


@router.get("/{request_id}")
def get_service_request(
    request_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.read")
    service_request = db.get(ServiceRequest, request_id)
    _ensure_request_read(service_request, current_user)
    return _detail_payload(db, service_request, current_user)


@router.post("/{request_id}/comments", status_code=status.HTTP_201_CREATED)
def add_request_comment(
    request_id: str,
    payload: RequestCommentCreate,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.comment")
    service_request = db.get(ServiceRequest, request_id)
    _ensure_request_read(service_request, current_user)
    if payload.is_internal and _is_requester_only(current_user):
        raise HTTPException(status_code=403, detail="Requester cannot post internal notes")
    activity = add_activity(
        db,
        service_request,
        actor=current_user,
        entity_type="service_request",
        entity_id=service_request.id,
        event_type="comment.added",
        message=payload.body.strip(),
        visibility="INTERNAL" if payload.is_internal else "PUBLIC",
    )
    log_audit(
        db,
        action="service_request.comment_added",
        entity_type="service_request",
        entity_id=service_request.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={"visibility": activity.visibility},
    )
    db.commit()
    db.refresh(activity)
    return _activity_payload(activity)


@router.post("/{request_id}/cancel")
def cancel_service_request(
    request_id: str,
    payload: RequestCancel,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.read")
    service_request = db.get(ServiceRequest, request_id)
    _ensure_request_read(service_request, current_user)
    if not _can_manage_request(service_request, current_user):
        raise HTTPException(status_code=403, detail="Request cancellation is not allowed")
    if service_request.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Service request version changed")
    if service_request.status in REQUEST_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Service request is already terminal")
    now = utc_now()
    old_status = service_request.status
    service_request.status = "CANCELLED"
    service_request.cancelled_at = now
    service_request.version += 1
    items = db.scalars(
        select(RequestedItem).where(RequestedItem.request_id == service_request.id)
    ).all()
    for item in items:
        if item.status not in {"COMPLETED", "REJECTED", "CANCELLED"}:
            item.status = "CANCELLED"
            item.cancelled_at = now
            item.version += 1
    for approval in db.scalars(
        select(RequestApproval).where(
            RequestApproval.request_id == service_request.id,
            RequestApproval.status == "PENDING",
        )
    ).all():
        approval.status = "CANCELLED"
        approval.comment = payload.reason
        approval.decided_at = now
    for task in db.scalars(
        select(FulfillmentTask).where(
            FulfillmentTask.request_id == service_request.id,
            FulfillmentTask.status.notin_(["COMPLETED", "CANCELLED"]),
        )
    ).all():
        task.status = "CANCELLED"
        task.version += 1
    add_activity(
        db,
        service_request,
        actor=current_user,
        entity_type="service_request",
        entity_id=service_request.id,
        event_type="request.cancelled",
        message=f"Заявка отменена: {payload.reason}",
        old_value={"status": old_status},
        new_value={"status": "CANCELLED"},
    )
    log_audit(
        db,
        action="service_request.cancelled",
        entity_type="service_request",
        entity_id=service_request.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={"reason": payload.reason},
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


@router.post("/{request_id}/items/{item_id}/rework")
def rework_requested_item(
    request_id: str,
    item_id: str,
    payload: RequestedItemRework,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.create")
    service_request = db.get(ServiceRequest, request_id)
    _ensure_request_read(service_request, current_user)
    if not _can_manage_request(service_request, current_user):
        raise HTTPException(status_code=403, detail="Request rework is not allowed")
    item = db.get(RequestedItem, item_id)
    if item is None or item.request_id != service_request.id:
        raise HTTPException(status_code=404, detail="Requested item not found")
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Requested item version changed")
    if item.status != "REJECTED":
        raise HTTPException(status_code=409, detail="Only rejected items can be reworked")
    item.rejected_at = None
    service_request.rejected_at = None
    create_approval_round(
        db,
        service_request,
        item,
        actor=current_user,
        approvers=_approvers(
            db,
            tenant_id=service_request.tenant_id,
            requester_id=service_request.requester_id,
        ),
    )
    add_activity(
        db,
        service_request,
        actor=current_user,
        requested_item_id=item.id,
        entity_type="requested_item",
        entity_id=item.id,
        event_type="item.reworked",
        message=f"Позиция повторно отправлена: {payload.reason}",
    )
    log_audit(
        db,
        action="service_request.item_reworked",
        entity_type="requested_item",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={"request_id": service_request.id, "reason": payload.reason},
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


@router.post("/items/{item_id}/sla/pause")
def pause_requested_item_sla(
    item_id: str,
    payload: SlaControl,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.manage")
    item = db.get(RequestedItem, item_id)
    _ensure_tenant(item, current_user, "Requested item")
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Requested item version changed")
    service_request = db.get(ServiceRequest, item.request_id)
    if not _pause_item_sla(
        db,
        service_request,
        item,
        actor=current_user,
        reason=payload.reason.strip(),
    ):
        raise HTTPException(status_code=409, detail="SLA cannot be paused")
    item.version += 1
    log_audit(
        db,
        action="service_request.sla_paused",
        entity_type="requested_item",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        tenant_id=item.tenant_id,
        ip_address=_client_ip(http_request),
        user_agent=http_request.headers.get("user-agent"),
        metadata={"reason": payload.reason},
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


@router.post("/items/{item_id}/sla/resume")
def resume_requested_item_sla(
    item_id: str,
    payload: SlaControl,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.manage")
    item = db.get(RequestedItem, item_id)
    _ensure_tenant(item, current_user, "Requested item")
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Requested item version changed")
    service_request = db.get(ServiceRequest, item.request_id)
    if not _resume_item_sla(
        db,
        service_request,
        item,
        actor=current_user,
        reason=payload.reason.strip(),
    ):
        raise HTTPException(status_code=409, detail="SLA is not paused")
    item.version += 1
    log_audit(
        db,
        action="service_request.sla_resumed",
        entity_type="requested_item",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        tenant_id=item.tenant_id,
        ip_address=_client_ip(http_request),
        user_agent=http_request.headers.get("user-agent"),
        metadata={"reason": payload.reason},
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


@router.post("/approvals/{approval_id}/decision")
def decide_request_approval(
    approval_id: str,
    payload: ApprovalDecision,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.approve")
    approval = db.get(RequestApproval, approval_id)
    _ensure_tenant(approval, current_user, "Approval")
    service_request = db.get(ServiceRequest, approval.request_id)
    item = db.get(RequestedItem, approval.requested_item_id)
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail="Approval is already decided")
    privileged = has_permission(current_user, "requests.manage")
    if (
        approval.approver_id is not None
        and approval.approver_id != current_user.id
        and not privileged
    ):
        raise HTTPException(status_code=403, detail="Approval is assigned to another user")
    if approval.approval_mode == "SEQUENTIAL":
        blocked = db.scalar(
            select(RequestApproval.id).where(
                RequestApproval.requested_item_id == item.id,
                RequestApproval.round == approval.round,
                RequestApproval.sequence < approval.sequence,
                RequestApproval.status != "APPROVED",
            )
        )
        if blocked:
            raise HTTPException(status_code=409, detail="Previous approval step is pending")
    if payload.decision == "REJECTED" and not (payload.comment or "").strip():
        raise HTTPException(status_code=422, detail="Rejection comment is required")

    now = utc_now()
    approval.status = payload.decision
    approval.comment = (payload.comment or "").strip() or None
    approval.decided_at = now
    add_activity(
        db,
        service_request,
        actor=current_user,
        requested_item_id=item.id,
        entity_type="request_approval",
        entity_id=approval.id,
        event_type=f"approval.{payload.decision.lower()}",
        message=(
            f"{'Согласовано' if payload.decision == 'APPROVED' else 'Отклонено'}: "
            f"{approval.approver_name}"
            + (f" — {approval.comment}" if approval.comment else "")
        ),
        new_value={"status": payload.decision, "round": approval.round},
    )
    if payload.decision == "REJECTED":
        for pending in db.scalars(
            select(RequestApproval).where(
                RequestApproval.requested_item_id == item.id,
                RequestApproval.round == approval.round,
                RequestApproval.status == "PENDING",
                RequestApproval.id != approval.id,
            )
        ).all():
            pending.status = "CANCELLED"
            pending.comment = "Раунд закрыт после отказа"
            pending.decided_at = now
        item.status = "REJECTED"
        item.rejected_at = now
        item.version += 1
    else:
        db.flush()
        pending_count = db.scalar(
            select(func.count(RequestApproval.id)).where(
                RequestApproval.requested_item_id == item.id,
                RequestApproval.round == approval.round,
                RequestApproval.status == "PENDING",
            )
        )
        if not pending_count:
            item.status = "APPROVED"
            item.version += 1
            create_task(db, service_request, item, actor=current_user)
    refresh_request_status(db, service_request, actor=current_user)
    log_audit(
        db,
        action=f"service_request.approval_{payload.decision.lower()}",
        entity_type="request_approval",
        entity_id=approval.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={
            "request_id": service_request.id,
            "requested_item_id": item.id,
            "round": approval.round,
        },
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


def _task_context(
    db: Session,
    task_id: str,
    current_user: AuthUserResponse,
) -> tuple[FulfillmentTask, ServiceRequest, RequestedItem]:
    task = db.get(FulfillmentTask, task_id)
    _ensure_tenant(task, current_user, "Fulfillment task")
    service_request = db.get(ServiceRequest, task.request_id)
    item = db.get(RequestedItem, task.requested_item_id)
    return task, service_request, item


def _ensure_task_actor(
    task: FulfillmentTask,
    current_user: AuthUserResponse,
) -> None:
    if has_permission(current_user, "requests.manage"):
        return
    if task.assignee_id is not None and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Task is assigned to another user")


@router.post("/tasks/{task_id}/assign")
def assign_fulfillment_task(
    task_id: str,
    payload: TaskAssignment,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.fulfill")
    task, service_request, item = _task_context(db, task_id, current_user)
    if task.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Fulfillment task version changed")
    manager = has_permission(current_user, "requests.manage")
    target_id = payload.assignee_id or current_user.id
    if not manager and (task.assignee_id not in {None, current_user.id} or target_id != current_user.id):
        raise HTTPException(status_code=403, detail="Only a manager can reassign tasks")
    assignee = db.get(User, target_id)
    if (
        assignee is None
        or not assignee.is_active
        or assignee.tenant_id != task.tenant_id
    ):
        raise HTTPException(status_code=422, detail="Assignee is unavailable")
    old_assignee = task.assignee_name
    task.assignee_id = assignee.id
    task.assignee_name = assignee.full_name
    task.version += 1
    add_activity(
        db,
        service_request,
        actor=current_user,
        requested_item_id=item.id,
        entity_type="fulfillment_task",
        entity_id=task.id,
        event_type="task.assigned",
        message=f"Задача {task.task_number} назначена: {assignee.full_name}",
        old_value={"assignee_name": old_assignee},
        new_value={"assignee_id": assignee.id, "assignee_name": assignee.full_name},
    )
    log_audit(
        db,
        action="service_request.task_assigned",
        entity_type="fulfillment_task",
        entity_id=task.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={"assignee_id": assignee.id, "request_id": service_request.id},
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)


@router.post("/tasks/{task_id}/transition")
def transition_fulfillment_task(
    task_id: str,
    payload: TaskTransition,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "requests.fulfill")
    task, service_request, item = _task_context(db, task_id, current_user)
    _ensure_task_actor(task, current_user)
    if task.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Fulfillment task version changed")
    if payload.target_status not in TASK_TRANSITIONS.get(task.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Transition {task.status} → {payload.target_status} is unavailable",
        )
    if payload.target_status in {"COMPLETED", "FAILED"} and len(
        (payload.comment or "").strip()
    ) < 3:
        raise HTTPException(
            status_code=422,
            detail="Completion or failure comment is required",
        )
    old_status = task.status
    now = utc_now()
    task.status = payload.target_status
    task.version += 1
    if payload.evidence:
        task.evidence_json = json.dumps(
            payload.evidence, ensure_ascii=False, sort_keys=True
        )
    if task.status == "COMPLETED":
        task.completed_at = now
    elif task.status == "OPEN":
        task.completed_at = None
    add_activity(
        db,
        service_request,
        actor=current_user,
        requested_item_id=item.id,
        entity_type="fulfillment_task",
        entity_id=task.id,
        event_type="task.status_changed",
        message=(
            f"Задача {task.task_number}: {old_status} → {task.status}"
            + (f" — {payload.comment.strip()}" if payload.comment else "")
        ),
        old_value={"status": old_status},
        new_value={"status": task.status, "evidence": payload.evidence},
    )
    if task.status == "WAITING":
        _pause_item_sla(
            db,
            service_request,
            item,
            actor=current_user,
            reason=payload.comment or f"{task.task_number} ожидает внешних данных",
        )
    elif old_status == "WAITING" and task.status == "IN_PROGRESS":
        _resume_item_sla(
            db,
            service_request,
            item,
            actor=current_user,
            reason=payload.comment or f"{task.task_number} продолжена",
        )
    db.flush()
    item_tasks = db.scalars(
        select(FulfillmentTask).where(
            FulfillmentTask.requested_item_id == item.id
        )
    ).all()
    if item_tasks and all(entry.status == "COMPLETED" for entry in item_tasks):
        item.status = "COMPLETED"
        item.completed_at = now
        if item.sla_paused_at is not None:
            _resume_item_sla(
                db,
                service_request,
                item,
                actor=current_user,
                reason="Исполнение завершено",
            )
        _refresh_item_sla(item, now=now)
        item.version += 1
    elif item_tasks and all(entry.status == "CANCELLED" for entry in item_tasks):
        item.status = "CANCELLED"
        item.cancelled_at = now
        item.version += 1
    else:
        item.status = "IN_FULFILLMENT"
        _refresh_item_sla(item, now=now)
    refresh_request_status(db, service_request, actor=current_user)
    log_audit(
        db,
        action="service_request.task_transitioned",
        entity_type="fulfillment_task",
        entity_id=task.id,
        actor_user=_actor(db, current_user),
        tenant_id=service_request.tenant_id,
        ip_address=_client_ip(http_request),
        metadata={
            "request_id": service_request.id,
            "old_status": old_status,
            "new_status": task.status,
        },
    )
    db.commit()
    return _detail_payload(db, service_request, current_user)
