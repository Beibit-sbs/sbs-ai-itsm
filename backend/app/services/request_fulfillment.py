from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.service_request import (
    FulfillmentTask,
    RequestActivity,
    RequestApproval,
    RequestedItem,
    ServiceRequest,
)
from app.services.catalog_governance import add_service_minutes


REQUEST_TERMINAL_STATUSES = {"COMPLETED", "REJECTED", "CANCELLED"}
TASK_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
TASK_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"WAITING", "COMPLETED", "FAILED", "CANCELLED"},
    "WAITING": {"IN_PROGRESS", "CANCELLED"},
    "FAILED": {"OPEN", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def request_number(now: datetime | None = None) -> str:
    timestamp = now or utc_now()
    return f"REQ-{timestamp:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def task_number(now: datetime | None = None) -> str:
    timestamp = now or utc_now()
    return f"RITM-{timestamp:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def add_activity(
    db: Session,
    service_request: ServiceRequest,
    *,
    actor: Any,
    entity_type: str,
    entity_id: str,
    event_type: str,
    message: str,
    requested_item_id: str | None = None,
    visibility: str = "PUBLIC",
    old_value: object | None = None,
    new_value: object | None = None,
) -> RequestActivity:
    activity = RequestActivity(
        id=str(uuid.uuid4()),
        tenant_id=service_request.tenant_id,
        request_id=service_request.id,
        requested_item_id=requested_item_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_user_id=getattr(actor, "id", None),
        actor_name=getattr(actor, "full_name", "System"),
        actor_email=getattr(actor, "email", None),
        visibility=visibility,
        message=message,
        old_value_json=(
            json.dumps(old_value, ensure_ascii=False, sort_keys=True)
            if old_value is not None
            else None
        ),
        new_value_json=(
            json.dumps(new_value, ensure_ascii=False, sort_keys=True)
            if new_value is not None
            else None
        ),
    )
    db.add(activity)
    return activity


def create_task(
    db: Session,
    service_request: ServiceRequest,
    item: RequestedItem,
    *,
    actor: Any,
) -> FulfillmentTask:
    existing = db.scalar(
        select(FulfillmentTask).where(
            FulfillmentTask.requested_item_id == item.id,
            FulfillmentTask.status.notin_(["FAILED", "CANCELLED"]),
        )
    )
    if existing is not None:
        return existing
    policy = json_object(item.sla_policy_snapshot_json)
    now = utc_now()
    ola_minutes = int(policy.get("ola_minutes") or 0)
    calendar_code = str(policy.get("calendar_code") or "24X7")
    task = FulfillmentTask(
        id=str(uuid.uuid4()),
        tenant_id=service_request.tenant_id,
        request_id=service_request.id,
        requested_item_id=item.id,
        task_number=task_number(),
        sequence=1,
        title=f"Выполнить: {item.item_name}",
        description=f"Задача исполнения для {service_request.request_number}",
        status="OPEN",
        version=1,
        support_group=item.support_group,
        due_at=(
            add_service_minutes(now, ola_minutes, calendar_code)
            if ola_minutes
            else item.sla_due_at
        ),
        evidence_json="{}",
    )
    db.add(task)
    item.status = "IN_FULFILLMENT"
    item.version += 1
    service_request.status = "IN_FULFILLMENT"
    service_request.version += 1
    add_activity(
        db,
        service_request,
        actor=actor,
        requested_item_id=item.id,
        entity_type="fulfillment_task",
        entity_id=task.id,
        event_type="task.created",
        message=f"Создана задача исполнения {task.task_number}",
        new_value={"status": task.status, "support_group": task.support_group},
    )
    return task


def create_approval_round(
    db: Session,
    service_request: ServiceRequest,
    item: RequestedItem,
    *,
    actor: Any,
    approvers: list[Any],
    due_minutes: int = 1440,
) -> list[RequestApproval]:
    current_round = db.scalar(
        select(func.max(RequestApproval.round)).where(
            RequestApproval.requested_item_id == item.id
        )
    )
    round_number = int(current_round or 0) + 1
    candidates = approvers or [None]
    approvals: list[RequestApproval] = []
    due_at = utc_now() + timedelta(minutes=due_minutes)
    for index, approver in enumerate(candidates, start=1):
        approval = RequestApproval(
            id=str(uuid.uuid4()),
            tenant_id=service_request.tenant_id,
            request_id=service_request.id,
            requested_item_id=item.id,
            round=round_number,
            sequence=index if item.approval_mode == "SEQUENTIAL" else 1,
            approval_mode=item.approval_mode,
            approver_id=getattr(approver, "id", None),
            approver_name=getattr(approver, "full_name", "Назначит менеджер"),
            approver_email=getattr(approver, "email", None),
            status="PENDING",
            due_at=due_at,
        )
        db.add(approval)
        approvals.append(approval)
    item.status = "PENDING_APPROVAL"
    item.version += 1
    service_request.status = "PENDING_APPROVAL"
    service_request.version += 1
    add_activity(
        db,
        service_request,
        actor=actor,
        requested_item_id=item.id,
        entity_type="requested_item",
        entity_id=item.id,
        event_type="approval.requested",
        message=f"Запущен раунд согласования {round_number}",
        new_value={
            "round": round_number,
            "mode": item.approval_mode,
            "approvals": len(approvals),
        },
    )
    return approvals


def refresh_request_status(
    db: Session,
    service_request: ServiceRequest,
    *,
    actor: Any,
) -> str:
    items = db.scalars(
        select(RequestedItem).where(RequestedItem.request_id == service_request.id)
    ).all()
    if not items:
        return service_request.status
    old_status = service_request.status
    statuses = {item.status for item in items}
    now = utc_now()
    if statuses == {"COMPLETED"}:
        new_status = "COMPLETED"
        service_request.completed_at = now
    elif "REJECTED" in statuses:
        new_status = "REJECTED"
        service_request.rejected_at = now
    elif statuses <= {"CANCELLED"}:
        new_status = "CANCELLED"
        service_request.cancelled_at = now
    elif statuses & {"IN_FULFILLMENT", "APPROVED", "COMPLETED"}:
        new_status = "IN_FULFILLMENT"
    elif "PENDING_APPROVAL" in statuses:
        new_status = "PENDING_APPROVAL"
    else:
        new_status = "SUBMITTED"
    if old_status != new_status:
        service_request.status = new_status
        service_request.version += 1
        add_activity(
            db,
            service_request,
            actor=actor,
            entity_type="service_request",
            entity_id=service_request.id,
            event_type="request.status_changed",
            message=f"Статус заявки изменён: {old_status} → {new_status}",
            old_value={"status": old_status},
            new_value={"status": new_status},
        )
    return new_status
