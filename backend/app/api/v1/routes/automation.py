from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.approval_request import ApprovalRequest
from app.models.automation_action_log import AutomationActionLog
from app.models.automation_rule import AutomationRule
from app.models.automation_run import AutomationRun
from app.models.runbook import Runbook
from app.models.runbook_execution import RunbookExecution
from app.models.ticket import Ticket
from app.models.user import User
from app.services.audit import log_audit
from app.services.automation import (
    AutomationEngine,
    approve_request,
    collect_automation_overview,
    execute_rule,
    reject_request,
    retry_execution,
    run_manual_rule,
    run_runbook,
)
from app.services.notifications import create_domain_event_notification
from app.services.rbac import has_permission, is_saas_root, require_permissions

router = APIRouter(prefix="/automation")


class AutomationRuleResponse(BaseModel):
    id: str
    tenant_id: str | None
    code: str
    name: str
    description: str | None
    trigger_type: str
    conditions_json: dict[str, Any] | list[Any]
    actions_json: list[dict[str, Any]]
    is_active: bool
    requires_approval: bool
    approval_role: str | None
    cooldown_minutes: int
    last_run_at: datetime | None
    run_count: int
    failure_count: int
    priority: int
    created_at: datetime
    updated_at: datetime


class AutomationRulePageResponse(BaseModel):
    items: list[AutomationRuleResponse]
    total: int
    page: int
    page_size: int


class AutomationRuleCreateRequest(BaseModel):
    tenant_id: str | None = Field(default=None, max_length=36)
    code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    trigger_type: str = Field(min_length=1, max_length=80)
    conditions_json: dict[str, Any] | list[Any] = Field(default_factory=dict)
    actions_json: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=50,
    )
    is_active: bool = True
    requires_approval: bool = False
    approval_role: str | None = Field(default=None, max_length=80)
    cooldown_minutes: int = Field(default=0, ge=0, le=10080)
    priority: int = Field(default=100, ge=0, le=10000)


class AutomationRulePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    trigger_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    conditions_json: dict[str, Any] | list[Any] | None = None
    actions_json: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=50,
    )
    is_active: bool | None = None
    requires_approval: bool | None = None
    approval_role: str | None = Field(default=None, max_length=80)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)
    priority: int | None = Field(default=None, ge=0, le=10000)


class AutomationRunResponse(BaseModel):
    id: str
    tenant_id: str | None
    rule_id: str
    runbook_id: str | None
    trigger_type: str
    trigger_entity_type: str | None
    trigger_entity_id: str | None
    status: str
    input_payload_json: dict[str, Any] | None
    output_payload_json: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    executed_by_id: str | None
    approval_request_id: str | None
    result_summary: dict[str, Any]
    error_message: str | None
    created_at: datetime


class AutomationExecutionPageResponse(BaseModel):
    items: list[AutomationRunResponse]
    total: int
    page: int
    page_size: int


class AutomationActionLogResponse(BaseModel):
    id: str
    tenant_id: str | None
    automation_run_id: str
    execution_id: str | None
    action_type: str
    action_payload_json: dict[str, Any]
    status: str
    result_payload_json: dict[str, Any]
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    error_message: str | None
    created_at: datetime


class DryRunRequest(BaseModel):
    trigger_type: str = Field(default="manual_run", max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)


class ManualRunRequest(BaseModel):
    trigger_type: str = Field(default="manual_run", max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class RunbookResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str | None
    code: str
    title: str
    description: str | None
    category: str
    severity: str
    steps_json: list[dict[str, Any]]
    estimated_minutes: int
    is_active: bool
    requires_approval: bool
    created_at: datetime
    updated_at: datetime


class RunbookPageResponse(BaseModel):
    items: list[RunbookResponse]
    total: int
    page: int
    page_size: int


class RunbookCreateRequest(BaseModel):
    tenant_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, max_length=255)
    code: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str = Field(min_length=1, max_length=80)
    severity: str = Field(min_length=1, max_length=40)
    steps_json: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=100,
    )
    estimated_minutes: int = Field(default=15, ge=1, le=1440)
    is_active: bool = True
    requires_approval: bool = False


class RunbookPatchRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    severity: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
    )
    steps_json: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=100,
    )
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    is_active: bool | None = None
    requires_approval: bool | None = None


class RunbookExecutionResponse(BaseModel):
    id: str
    tenant_id: str | None
    runbook_id: str
    ticket_id: str | None
    status: str
    current_step: int
    started_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None
    created_at: datetime


class StartRunbookExecutionRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=36)


class PatchRunbookExecutionRequest(BaseModel):
    status: str | None = Field(
        default=None,
        pattern="^(running|completed|failed|cancelled)$",
    )
    current_step: int | None = Field(default=None, ge=1, le=100)
    result_summary: str | None = Field(default=None, max_length=4000)


class ApprovalRequestResponse(BaseModel):
    id: str
    tenant_id: str | None
    title: str
    description: str | None
    entity_type: str
    entity_id: str | None
    requested_by_id: str | None
    approver_id: str | None
    requested_by: str
    approver_name: str | None
    status: str
    reason: str | None
    decision_comment: str | None
    requested_at: datetime
    metadata_json: dict[str, Any]
    created_at: datetime
    decided_at: datetime | None


class ApprovalRequestPageResponse(BaseModel):
    items: list[ApprovalRequestResponse]
    total: int
    page: int
    page_size: int


class ApprovalDecisionRequest(BaseModel):
    decision: str | None = Field(default=None, max_length=16)
    comment: str | None = Field(default=None, max_length=4000)


class SuggestionResponse(BaseModel):
    ticket_id: str
    suggested_runbooks: list[dict[str, Any]]
    matched_rules: list[dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return fallback
    return parsed


def _actor(db: Session, current_user: AuthUserResponse) -> User | None:
    return db.get(User, current_user.id)


def _tenant_scope(current_user: AuthUserResponse) -> str | None:
    return None if is_saas_root(current_user) else current_user.tenant_id


def _filter_by_tenant(statement: Select, model: Any, current_user: AuthUserResponse) -> Select:
    if is_saas_root(current_user):
        return statement
    return statement.where((model.tenant_id == current_user.tenant_id) | (model.tenant_id.is_(None)))


def _require_any_permission(current_user: AuthUserResponse, *permissions: str) -> None:
    if any(has_permission(current_user, permission) for permission in permissions):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing one of permissions: {', '.join(permissions)}")


def _rule_response(item: AutomationRule) -> AutomationRuleResponse:
    return AutomationRuleResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        code=item.code,
        name=item.name,
        description=item.description,
        trigger_type=item.trigger_type,
        conditions_json=_parse_json(item.conditions_json, {}),
        actions_json=_parse_json(item.actions_json, []),
        is_active=item.is_active,
        requires_approval=item.requires_approval,
        approval_role=item.approval_role,
        cooldown_minutes=item.cooldown_minutes,
        last_run_at=item.last_run_at,
        run_count=item.run_count,
        failure_count=item.failure_count,
        priority=item.priority,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _run_response(item: AutomationRun) -> AutomationRunResponse:
    return AutomationRunResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        rule_id=item.rule_id,
        runbook_id=item.runbook_id,
        trigger_type=item.trigger_type,
        trigger_entity_type=item.trigger_entity_type,
        trigger_entity_id=item.trigger_entity_id,
        status=item.status,
        input_payload_json=_parse_json(item.input_payload_json, {}),
        output_payload_json=_parse_json(item.output_payload_json, {}),
        started_at=item.started_at,
        finished_at=item.finished_at,
        executed_by_id=item.executed_by_id,
        approval_request_id=item.approval_request_id,
        result_summary=_parse_json(item.result_summary, {}),
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _action_log_response(item: AutomationActionLog) -> AutomationActionLogResponse:
    return AutomationActionLogResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        automation_run_id=item.automation_run_id,
        execution_id=item.execution_id,
        action_type=item.action_type,
        action_payload_json=_parse_json(item.action_payload_json, {}),
        status=item.status,
        result_payload_json=_parse_json(item.result_payload_json, {}),
        input_json=_parse_json(item.input_json, {}),
        output_json=_parse_json(item.output_json, {}),
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _runbook_response(item: Runbook) -> RunbookResponse:
    return RunbookResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        name=item.name,
        code=item.code,
        title=item.title,
        description=item.description,
        category=item.category,
        severity=item.severity,
        steps_json=_parse_json(item.steps_json, []),
        estimated_minutes=item.estimated_minutes,
        is_active=item.is_active,
        requires_approval=item.requires_approval,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _runbook_execution_response(item: RunbookExecution) -> RunbookExecutionResponse:
    return RunbookExecutionResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        runbook_id=item.runbook_id,
        ticket_id=item.ticket_id,
        status=item.status,
        current_step=item.current_step,
        started_by=item.started_by,
        started_at=item.started_at,
        completed_at=item.completed_at,
        result_summary=item.result_summary,
        created_at=item.created_at,
    )


def _approval_response(item: ApprovalRequest) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        title=item.title,
        description=item.description,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        requested_by_id=item.requested_by_id,
        approver_id=item.approver_id,
        requested_by=item.requested_by,
        approver_name=item.approver_name,
        status=item.status,
        reason=item.reason,
        decision_comment=item.decision_comment,
        requested_at=item.requested_at,
        metadata_json=_parse_json(item.metadata_json, {}),
        created_at=item.created_at,
        decided_at=item.decided_at,
    )


@router.get("/overview")
def get_overview(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    require_permissions(current_user, "automation.rules.read")
    return collect_automation_overview(db, _tenant_scope(current_user))


@router.get("/rules", response_model=AutomationRulePageResponse)
def list_rules(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    trigger_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> AutomationRulePageResponse:
    _require_any_permission(current_user, "automation.read", "automation.rules.read")
    statement = _filter_by_tenant(select(AutomationRule), AutomationRule, current_user)
    if trigger_type:
        statement = statement.where(AutomationRule.trigger_type == trigger_type)
    effective_active = is_active if is_active is not None else active
    if effective_active is not None:
        statement = statement.where(AutomationRule.is_active == effective_active)
    if q:
        token = f"%{q.strip()}%"
        statement = statement.where(or_(AutomationRule.name.ilike(token), AutomationRule.code.ilike(token), AutomationRule.description.ilike(token)))

    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(
        statement.order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return AutomationRulePageResponse(items=[_rule_response(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/rules/{rule_id}", response_model=AutomationRuleResponse)
def get_rule(rule_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> AutomationRuleResponse:
    _require_any_permission(current_user, "automation.read", "automation.rules.read")
    item = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return _rule_response(item)


@router.post("/rules", response_model=AutomationRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    request: AutomationRuleCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRuleResponse:
    _require_any_permission(current_user, "automation.create", "automation.rules.manage")
    if db.scalar(select(AutomationRule).where(AutomationRule.code == request.code, AutomationRule.tenant_id == (_tenant_scope(current_user) or request.tenant_id))) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rule code already exists")

    tenant_id = request.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    now = _now()
    item = AutomationRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=request.code,
        name=request.name,
        description=request.description,
        trigger_type=request.trigger_type,
        conditions_json=json.dumps(request.conditions_json, ensure_ascii=False),
        actions_json=json.dumps(request.actions_json, ensure_ascii=False),
        is_active=request.is_active,
        requires_approval=request.requires_approval,
        approval_role=request.approval_role,
        cooldown_minutes=request.cooldown_minutes,
        created_by_id=current_user.id,
        priority=request.priority,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="automation_rule_created",
        entity_type="automation_rule",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return _rule_response(item)


@router.patch("/rules/{rule_id}", response_model=AutomationRuleResponse)
def patch_rule(
    rule_id: str,
    request: AutomationRulePatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRuleResponse:
    _require_any_permission(current_user, "automation.update", "automation.rules.manage")
    item = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if field_name == "conditions_json" and value is not None:
            setattr(item, field_name, json.dumps(value, ensure_ascii=False))
            continue
        if field_name == "actions_json" and value is not None:
            setattr(item, field_name, json.dumps(value, ensure_ascii=False))
            continue
        setattr(item, field_name, value)
    item.updated_by_id = current_user.id
    item.updated_at = _now()
    log_audit(
        db,
        action="automation_rule_updated",
        entity_type="automation_rule",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(item)
    return _rule_response(item)


@router.post("/rules/{rule_id}/enable", response_model=AutomationRuleResponse)
def enable_rule(
    rule_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRuleResponse:
    _require_any_permission(current_user, "automation.update", "automation.rules.manage")
    item = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    item.is_active = True
    item.updated_by_id = current_user.id
    item.updated_at = _now()
    log_audit(
        db,
        action="automation_rule_enabled",
        entity_type="automation_rule",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _rule_response(item)


@router.post("/rules/{rule_id}/disable", response_model=AutomationRuleResponse)
def disable_rule(
    rule_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRuleResponse:
    _require_any_permission(current_user, "automation.update", "automation.rules.manage")
    item = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    item.is_active = False
    item.updated_by_id = current_user.id
    item.updated_at = _now()
    log_audit(
        db,
        action="automation_rule_disabled",
        entity_type="automation_rule",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _rule_response(item)


@router.post("/rules/{rule_id}/dry-run")
def dry_run_rule(
    rule_id: str,
    request: DryRunRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_any_permission(current_user, "automation.dry_run", "automation.rules.execute")
    rule = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    context = dict(request.context)
    context.setdefault("trigger_type", request.trigger_type)
    context.setdefault("entity_type", context.get("entity_type", "manual"))
    context.setdefault("entity_id", context.get("entity_id", f"dry-run-{rule.id}"))
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    dry_preview = AutomationEngine.dry_run_rule(rule, context)
    execution = execute_rule(db, rule, context, current_user=actor, dry_run=True)
    db.commit()
    db.refresh(execution)
    return {
        **dry_preview,
        "execution": _run_response(execution),
    }


@router.post("/rules/{rule_id}/run")
def run_rule(
    rule_id: str,
    request: RunRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_any_permission(current_user, "automation.run", "automation.rules.execute")
    rule = db.scalar(
        _filter_by_tenant(
            select(AutomationRule).where(AutomationRule.id == rule_id),
            AutomationRule,
            current_user,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found",
        )
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    payload = dict(request.payload)
    payload.setdefault("trigger_type", "manual")
    payload.setdefault("entity_type", payload.get("entity_type", "manual"))
    payload.setdefault("entity_id", payload.get("entity_id", f"manual-{rule_id}"))
    try:
        run = run_manual_rule(db, rule_id, payload, actor, dry_run=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit(
        db,
        action="automation_rule_executed",
        entity_type="automation_execution",
        entity_id=run.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"run_id": run.id, "status": run.status},
    )
    if run.status in {"failed", "waiting_approval"}:
        create_domain_event_notification(
            db,
            tenant_id=current_user.tenant_id,
            event_type="approval_required" if run.status == "waiting_approval" else "automation_failed",
            title="Automation требует согласования" if run.status == "waiting_approval" else "Automation run завершился с ошибкой",
            message=f"Execution {run.id} status={run.status}",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="warning",
            entity_type="automation_execution",
            entity_id=run.id,
            action_url="/automation",
            metadata={"rule_id": run.rule_id, "status": run.status},
        )
    db.commit()
    db.refresh(run)
    return {"execution": _run_response(run), "summary": _parse_json(run.result_summary, {})}


@router.post("/rules/{rule_id}/manual-run")
def legacy_manual_run_rule(
    rule_id: str,
    request: ManualRunRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = dict(request.context)
    payload.setdefault("trigger_type", request.trigger_type)
    result = run_rule(rule_id, RunRequest(payload=payload), http_request, current_user, db)
    return {"run": result["execution"], "summary": result["summary"]}


@router.get("/executions", response_model=AutomationExecutionPageResponse)
def list_executions(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    rule_id: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> AutomationExecutionPageResponse:
    _require_any_permission(current_user, "automation.executions.read", "automation.runs.read")
    statement = _filter_by_tenant(select(AutomationRun), AutomationRun, current_user)
    if rule_id:
        statement = statement.where(AutomationRun.rule_id == rule_id)
    if trigger_type:
        statement = statement.where(AutomationRun.trigger_type == trigger_type)
    if status_filter:
        statement = statement.where(AutomationRun.status == status_filter)

    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(statement.order_by(AutomationRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return AutomationExecutionPageResponse(items=[_run_response(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/runs", response_model=list[AutomationRunResponse])
def list_runs_legacy(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    trigger_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[AutomationRunResponse]:
    page = list_executions(current_user, db, None, trigger_type, status_filter, 1, 200)
    return page.items


@router.get("/executions/{execution_id}", response_model=dict[str, Any])
def get_execution(execution_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_any_permission(current_user, "automation.executions.read", "automation.logs.read")
    run = db.scalar(_filter_by_tenant(select(AutomationRun).where(AutomationRun.id == execution_id), AutomationRun, current_user))
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    logs = db.scalars(
        _filter_by_tenant(
            select(AutomationActionLog).where(AutomationActionLog.automation_run_id == run.id).order_by(AutomationActionLog.created_at.asc()),
            AutomationActionLog,
            current_user,
        )
    ).all()
    return {"execution": _run_response(run), "action_logs": [_action_log_response(item) for item in logs]}


@router.post("/executions/{execution_id}/retry", response_model=AutomationRunResponse)
def retry_failed_execution(
    execution_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRunResponse:
    _require_any_permission(current_user, "automation.executions.retry", "automation.executions.manage")
    source_execution = db.scalar(
        _filter_by_tenant(
            select(AutomationRun).where(AutomationRun.id == execution_id),
            AutomationRun,
            current_user,
        )
    )
    if source_execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found",
        )
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        retried = retry_execution(db, execution_id, actor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_audit(
        db,
        action="automation_execution_retried",
        entity_type="automation_execution",
        entity_id=retried.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"source_execution_id": execution_id},
    )
    db.commit()
    db.refresh(retried)
    return _run_response(retried)


@router.get("/runs/{run_id}/logs", response_model=list[AutomationActionLogResponse])
def list_action_logs(run_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AutomationActionLogResponse]:
    require_permissions(current_user, "automation.logs.read")
    run = db.scalar(_filter_by_tenant(select(AutomationRun).where(AutomationRun.id == run_id), AutomationRun, current_user))
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    statement = _filter_by_tenant(
        select(AutomationActionLog).where(AutomationActionLog.automation_run_id == run.id).order_by(AutomationActionLog.created_at.asc()),
        AutomationActionLog,
        current_user,
    )
    return [_action_log_response(item) for item in db.scalars(statement).all()]


@router.get("/runbooks", response_model=RunbookPageResponse)
def list_runbooks(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> RunbookPageResponse:
    require_permissions(current_user, "automation.runbooks.read")
    statement = _filter_by_tenant(select(Runbook), Runbook, current_user)
    if active is not None:
        statement = statement.where(Runbook.is_active == active)
    if q:
        token = f"%{q.strip()}%"
        statement = statement.where(or_(Runbook.title.ilike(token), Runbook.code.ilike(token), Runbook.description.ilike(token)))
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(statement.order_by(Runbook.title.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return RunbookPageResponse(items=[_runbook_response(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/runbooks/{runbook_id}", response_model=RunbookResponse)
def get_runbook(runbook_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> RunbookResponse:
    require_permissions(current_user, "automation.runbooks.read")
    item = db.scalar(_filter_by_tenant(select(Runbook).where(Runbook.id == runbook_id), Runbook, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runbook not found")
    return _runbook_response(item)


@router.post("/runbooks", response_model=RunbookResponse, status_code=status.HTTP_201_CREATED)
def create_runbook(
    request: RunbookCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunbookResponse:
    _require_any_permission(current_user, "automation.runbooks.create", "automation.runbooks.manage")
    tenant_id = request.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    now = _now()
    item = Runbook(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=request.name,
        code=request.code,
        title=request.title,
        description=request.description,
        category=request.category,
        severity=request.severity,
        steps_json=json.dumps(request.steps_json, ensure_ascii=False),
        estimated_minutes=request.estimated_minutes,
        is_active=request.is_active,
        requires_approval=request.requires_approval,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="runbook_created",
        entity_type="runbook",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return _runbook_response(item)


@router.patch("/runbooks/{runbook_id}", response_model=RunbookResponse)
def patch_runbook(
    runbook_id: str,
    request: RunbookPatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunbookResponse:
    _require_any_permission(current_user, "automation.runbooks.update", "automation.runbooks.manage")
    item = db.scalar(_filter_by_tenant(select(Runbook).where(Runbook.id == runbook_id), Runbook, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runbook not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if field_name == "steps_json" and value is not None:
            setattr(item, field_name, json.dumps(value, ensure_ascii=False))
            continue
        setattr(item, field_name, value)
    item.updated_by_id = current_user.id
    item.updated_at = _now()
    log_audit(
        db,
        action="runbook_updated",
        entity_type="runbook",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(item)
    return _runbook_response(item)


@router.post("/runbooks/{runbook_id}/dry-run", response_model=AutomationRunResponse)
def dry_run_runbook(
    runbook_id: str,
    request: RunRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRunResponse:
    _require_any_permission(current_user, "automation.dry_run", "automation.runbooks.run", "automation.runbooks.manage", "automation.rules.execute")
    runbook = db.scalar(
        _filter_by_tenant(
            select(Runbook).where(Runbook.id == runbook_id),
            Runbook,
            current_user,
        )
    )
    if runbook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runbook not found",
        )
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        execution = run_runbook(db, runbook_id, request.payload, actor, dry_run=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(execution)
    return _run_response(execution)


@router.post("/runbooks/{runbook_id}/run", response_model=AutomationRunResponse)
def run_runbook_endpoint(
    runbook_id: str,
    request: RunRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRunResponse:
    _require_any_permission(current_user, "automation.runbooks.run", "automation.executions.manage", "automation.runbooks.manage", "automation.rules.execute")
    runbook = db.scalar(
        _filter_by_tenant(
            select(Runbook).where(Runbook.id == runbook_id),
            Runbook,
            current_user,
        )
    )
    if runbook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runbook not found",
        )
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    try:
        execution = run_runbook(db, runbook_id, request.payload, actor, dry_run=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(execution)
    return _run_response(execution)


@router.get("/runbook-executions", response_model=list[RunbookExecutionResponse])
def list_runbook_executions(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RunbookExecutionResponse]:
    require_permissions(current_user, "automation.executions.read")
    statement = _filter_by_tenant(select(RunbookExecution).order_by(RunbookExecution.created_at.desc()), RunbookExecution, current_user)
    return [_runbook_execution_response(item) for item in db.scalars(statement).all()]


@router.post("/runbooks/{runbook_id}/executions", response_model=RunbookExecutionResponse, status_code=status.HTTP_201_CREATED)
def start_runbook_execution(
    runbook_id: str,
    request: StartRunbookExecutionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunbookExecutionResponse:
    require_permissions(current_user, "automation.executions.manage")
    runbook = db.scalar(_filter_by_tenant(select(Runbook).where(Runbook.id == runbook_id), Runbook, current_user))
    if runbook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runbook not found")
    runbook_steps = _parse_json(runbook.steps_json, [])
    if not isinstance(runbook_steps, list) or not runbook_steps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runbook has no executable checklist steps",
        )
    execution_tenant_id = runbook.tenant_id or current_user.tenant_id

    if request.ticket_id is not None:
        ticket = db.get(Ticket, request.ticket_id)
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        if not is_saas_root(current_user) and ticket.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        if (
            execution_tenant_id is not None
            and ticket.tenant_id != execution_tenant_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found",
            )
        execution_tenant_id = execution_tenant_id or ticket.tenant_id

    now = _now()
    item = RunbookExecution(
        id=str(uuid.uuid4()),
        tenant_id=execution_tenant_id,
        runbook_id=runbook.id,
        ticket_id=request.ticket_id,
        status="running",
        current_step=1,
        started_by=current_user.email,
        started_at=now,
        completed_at=None,
        result_summary="Runbook checklist started; completion is pending operator confirmation.",
        created_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="runbook_execution_started",
        entity_type="runbook_execution",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"runbook_id": runbook.id},
    )
    db.commit()
    db.refresh(item)
    return _runbook_execution_response(item)


@router.patch("/runbook-executions/{execution_id}", response_model=RunbookExecutionResponse)
def patch_runbook_execution(
    execution_id: str,
    request: PatchRunbookExecutionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunbookExecutionResponse:
    require_permissions(current_user, "automation.executions.manage")
    item = db.scalar(_filter_by_tenant(select(RunbookExecution).where(RunbookExecution.id == execution_id), RunbookExecution, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    if item.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Terminal runbook execution is immutable",
        )
    runbook = db.scalar(
        _filter_by_tenant(
            select(Runbook).where(Runbook.id == item.runbook_id),
            Runbook,
            current_user,
        )
    )
    if runbook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runbook not found",
        )
    runbook_steps = _parse_json(runbook.steps_json, [])
    step_count = len(runbook_steps) if isinstance(runbook_steps, list) else 0

    updates = request.model_dump(exclude_unset=True)
    target_step = int(updates.get("current_step", item.current_step))
    if step_count <= 0 or target_step > step_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runbook step exceeds the governed checklist",
        )
    if updates.get("status") == "completed" and target_step < step_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="All runbook checklist steps must be reached before completion",
        )
    for field_name, value in updates.items():
        setattr(item, field_name, value)
    if item.status in {"completed", "failed", "cancelled"} and item.completed_at is None:
        item.completed_at = _now()
    log_audit(
        db,
        action="runbook_execution_updated",
        entity_type="runbook_execution",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"updated_fields": list(updates.keys()), "status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _runbook_execution_response(item)


@router.get("/approvals", response_model=ApprovalRequestPageResponse)
def list_approvals(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> ApprovalRequestPageResponse:
    require_permissions(current_user, "automation.approvals.read")
    statement = _filter_by_tenant(select(ApprovalRequest), ApprovalRequest, current_user)
    if status_filter:
        statement = statement.where(ApprovalRequest.status == status_filter)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = db.scalars(statement.order_by(ApprovalRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return ApprovalRequestPageResponse(items=[_approval_response(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/approvals/{approval_id}", response_model=ApprovalRequestResponse)
def get_approval(approval_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> ApprovalRequestResponse:
    require_permissions(current_user, "automation.approvals.read")
    item = db.scalar(_filter_by_tenant(select(ApprovalRequest).where(ApprovalRequest.id == approval_id), ApprovalRequest, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    return _approval_response(item)


@router.patch("/approvals/{approval_id}", response_model=ApprovalRequestResponse)
def patch_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    _require_any_permission(current_user, "automation.approvals.decide", "automation.approvals.manage")
    item = db.scalar(_filter_by_tenant(select(ApprovalRequest).where(ApprovalRequest.id == approval_id), ApprovalRequest, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    decision = (request.decision or "").strip().lower()
    actor = _actor(db, current_user)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Actor not found")
    if decision == "approved":
        item = approve_request(db, approval_id, actor, request.comment)
    elif decision == "rejected":
        item = reject_request(db, approval_id, actor, request.comment)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be approved or rejected")

    log_audit(
        db,
        action="approval_request_decided",
        entity_type="approval_request",
        entity_id=item.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"decision": decision, "comment": request.comment},
    )
    if decision == "rejected":
        create_domain_event_notification(
            db,
            tenant_id=current_user.tenant_id,
            event_type="approval_rejected",
            title="Approval request отклонен",
            message=f"Запрос '{item.title}' был отклонен пользователем {current_user.full_name}.",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="warning",
            entity_type="approval_request",
            entity_id=item.id,
            action_url="/automation",
            metadata={"decision": decision},
        )
    else:
        create_domain_event_notification(
            db,
            tenant_id=current_user.tenant_id,
            event_type="approval_approved",
            title="Approval request подтвержден",
            message=f"Запрос '{item.title}' подтвержден пользователем {current_user.full_name}.",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="info",
            entity_type="approval_request",
            entity_id=item.id,
            action_url="/automation",
            metadata={"decision": decision},
        )
    db.commit()
    db.refresh(item)
    return _approval_response(item)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRequestResponse)
def approve_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    request.decision = "approved"
    return patch_approval(approval_id, request, http_request, current_user, db)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalRequestResponse)
def reject_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    request.decision = "rejected"
    return patch_approval(approval_id, request, http_request, current_user, db)


@router.get("/tickets/{ticket_id}/suggestions", response_model=SuggestionResponse)
def get_ticket_suggestions(ticket_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> SuggestionResponse:
    require_permissions(current_user, "automation.suggestions.read")
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if not is_saas_root(current_user) and ticket.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    suggestions = AutomationEngine.suggest_runbooks_for_ticket(db, ticket, _tenant_scope(current_user))
    return SuggestionResponse(**suggestions)


@router.post("/trigger")
def trigger_event(
    request: ManualRunRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "automation.rules.execute")
    runs = AutomationEngine.evaluate_rules(
        db,
        tenant_id=_tenant_scope(current_user),
        trigger_type=request.trigger_type,
        context=request.context,
        actor_email=current_user.email,
    )
    db.commit()
    return {"runs": [_run_response(item).model_dump() for item in runs]}
