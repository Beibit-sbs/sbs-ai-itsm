from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, select
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
from app.services.automation import AutomationEngine, build_ticket_context, collect_automation_overview
from app.services.rbac import is_saas_root, require_permissions

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
    priority: int
    created_at: datetime
    updated_at: datetime


class AutomationRuleCreateRequest(BaseModel):
    tenant_id: str | None = None
    code: str
    name: str
    description: str | None = None
    trigger_type: str
    conditions_json: dict[str, Any] | list[Any] = Field(default_factory=dict)
    actions_json: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    priority: int = 100


class AutomationRulePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    conditions_json: dict[str, Any] | list[Any] | None = None
    actions_json: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    priority: int | None = None


class AutomationRunResponse(BaseModel):
    id: str
    tenant_id: str | None
    rule_id: str
    trigger_type: str
    trigger_entity_type: str | None
    trigger_entity_id: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    result_summary: dict[str, Any]
    error_message: str | None
    created_at: datetime


class AutomationActionLogResponse(BaseModel):
    id: str
    tenant_id: str | None
    automation_run_id: str
    action_type: str
    status: str
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    error_message: str | None
    created_at: datetime


class DryRunRequest(BaseModel):
    trigger_type: str = "manual_run"
    context: dict[str, Any] = Field(default_factory=dict)


class ManualRunRequest(BaseModel):
    trigger_type: str = "manual_run"
    context: dict[str, Any] = Field(default_factory=dict)


class RunbookResponse(BaseModel):
    id: str
    tenant_id: str | None
    code: str
    title: str
    description: str | None
    category: str
    severity: str
    steps_json: list[dict[str, Any]]
    estimated_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RunbookCreateRequest(BaseModel):
    tenant_id: str | None = None
    code: str
    title: str
    description: str | None = None
    category: str
    severity: str
    steps_json: list[dict[str, Any]] = Field(default_factory=list)
    estimated_minutes: int = 15
    is_active: bool = True


class RunbookPatchRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    severity: str | None = None
    steps_json: list[dict[str, Any]] | None = None
    estimated_minutes: int | None = None
    is_active: bool | None = None


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
    ticket_id: str | None = None


class PatchRunbookExecutionRequest(BaseModel):
    status: str | None = None
    current_step: int | None = None
    result_summary: str | None = None


class ApprovalRequestResponse(BaseModel):
    id: str
    tenant_id: str | None
    title: str
    description: str | None
    entity_type: str
    entity_id: str | None
    requested_by: str
    approver_name: str | None
    status: str
    decision_comment: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecisionRequest(BaseModel):
    decision: str
    comment: str | None = None


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
        priority=item.priority,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _run_response(item: AutomationRun) -> AutomationRunResponse:
    return AutomationRunResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        rule_id=item.rule_id,
        trigger_type=item.trigger_type,
        trigger_entity_type=item.trigger_entity_type,
        trigger_entity_id=item.trigger_entity_id,
        status=item.status,
        started_at=item.started_at,
        finished_at=item.finished_at,
        result_summary=_parse_json(item.result_summary, {}),
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _action_log_response(item: AutomationActionLog) -> AutomationActionLogResponse:
    return AutomationActionLogResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        automation_run_id=item.automation_run_id,
        action_type=item.action_type,
        status=item.status,
        input_json=_parse_json(item.input_json, {}),
        output_json=_parse_json(item.output_json, {}),
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _runbook_response(item: Runbook) -> RunbookResponse:
    return RunbookResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        code=item.code,
        title=item.title,
        description=item.description,
        category=item.category,
        severity=item.severity,
        steps_json=_parse_json(item.steps_json, []),
        estimated_minutes=item.estimated_minutes,
        is_active=item.is_active,
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
        requested_by=item.requested_by,
        approver_name=item.approver_name,
        status=item.status,
        decision_comment=item.decision_comment,
        created_at=item.created_at,
        decided_at=item.decided_at,
    )


@router.get("/overview")
def get_overview(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    require_permissions(current_user, "automation.rules.read")
    return collect_automation_overview(db, _tenant_scope(current_user))


@router.get("/rules", response_model=list[AutomationRuleResponse])
def list_rules(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    trigger_type: str | None = Query(default=None),
    active: bool | None = Query(default=None),
) -> list[AutomationRuleResponse]:
    require_permissions(current_user, "automation.rules.read")
    statement = _filter_by_tenant(select(AutomationRule).order_by(AutomationRule.priority.asc(), AutomationRule.created_at.asc()), AutomationRule, current_user)
    if trigger_type:
        statement = statement.where(AutomationRule.trigger_type == trigger_type)
    if active is not None:
        statement = statement.where(AutomationRule.is_active == active)
    return [_rule_response(item) for item in db.scalars(statement).all()]


@router.post("/rules", response_model=AutomationRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    request: AutomationRuleCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutomationRuleResponse:
    require_permissions(current_user, "automation.rules.manage")
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
    require_permissions(current_user, "automation.rules.manage")
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


@router.post("/rules/{rule_id}/dry-run")
def dry_run_rule(
    rule_id: str,
    request: DryRunRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "automation.rules.execute")
    rule = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    context = dict(request.context)
    context.setdefault("entity_type", context.get("entity_type", "manual"))
    context.setdefault("entity_id", context.get("entity_id"))
    return AutomationEngine.dry_run_rule(rule, context)


@router.post("/rules/{rule_id}/manual-run")
def manual_run_rule(
    rule_id: str,
    request: ManualRunRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_permissions(current_user, "automation.rules.execute")
    rule = db.scalar(_filter_by_tenant(select(AutomationRule).where(AutomationRule.id == rule_id), AutomationRule, current_user))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    if not rule.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rule is inactive")

    context = dict(request.context)
    context.setdefault("entity_type", context.get("entity_type", "manual"))
    context.setdefault("entity_id", context.get("entity_id"))
    run = AutomationEngine.create_run(
        db,
        rule=rule,
        trigger_type=request.trigger_type,
        trigger_entity_type=str(context.get("entity_type")),
        trigger_entity_id=str(context.get("entity_id")) if context.get("entity_id") is not None else None,
    )
    summary = AutomationEngine.execute_actions(db, run=run, rule=rule, context=context, actor_email=current_user.email)
    log_audit(
        db,
        action="automation_manual_run_executed",
        entity_type="automation_rule",
        entity_id=rule.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"run_id": run.id, "status": run.status},
    )
    db.commit()
    db.refresh(run)
    return {"run": _run_response(run), "summary": summary}


@router.get("/runs", response_model=list[AutomationRunResponse])
def list_runs(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    trigger_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[AutomationRunResponse]:
    require_permissions(current_user, "automation.runs.read")
    statement = _filter_by_tenant(select(AutomationRun).order_by(AutomationRun.created_at.desc()), AutomationRun, current_user)
    if trigger_type:
        statement = statement.where(AutomationRun.trigger_type == trigger_type)
    if status_filter:
        statement = statement.where(AutomationRun.status == status_filter)
    return [_run_response(item) for item in db.scalars(statement).all()]


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


@router.get("/runbooks", response_model=list[RunbookResponse])
def list_runbooks(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db), active: bool | None = Query(default=None)) -> list[RunbookResponse]:
    require_permissions(current_user, "automation.runbooks.read")
    statement = _filter_by_tenant(select(Runbook).order_by(Runbook.title.asc()), Runbook, current_user)
    if active is not None:
        statement = statement.where(Runbook.is_active == active)
    return [_runbook_response(item) for item in db.scalars(statement).all()]


@router.post("/runbooks", response_model=RunbookResponse, status_code=status.HTTP_201_CREATED)
def create_runbook(
    request: RunbookCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunbookResponse:
    require_permissions(current_user, "automation.runbooks.manage")
    tenant_id = request.tenant_id if is_saas_root(current_user) else current_user.tenant_id
    now = _now()
    item = Runbook(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=request.code,
        title=request.title,
        description=request.description,
        category=request.category,
        severity=request.severity,
        steps_json=json.dumps(request.steps_json, ensure_ascii=False),
        estimated_minutes=request.estimated_minutes,
        is_active=request.is_active,
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
    require_permissions(current_user, "automation.runbooks.manage")
    item = db.scalar(_filter_by_tenant(select(Runbook).where(Runbook.id == runbook_id), Runbook, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runbook not found")
    updates = request.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if field_name == "steps_json" and value is not None:
            setattr(item, field_name, json.dumps(value, ensure_ascii=False))
            continue
        setattr(item, field_name, value)
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

    if request.ticket_id is not None:
        ticket = db.get(Ticket, request.ticket_id)
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        if not is_saas_root(current_user) and ticket.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    now = _now()
    item = RunbookExecution(
        id=str(uuid.uuid4()),
        tenant_id=runbook.tenant_id,
        runbook_id=runbook.id,
        ticket_id=request.ticket_id,
        status="running",
        current_step=1,
        started_by=current_user.email,
        started_at=now,
        completed_at=None,
        result_summary="Runbook started in demo mode.",
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

    updates = request.model_dump(exclude_unset=True)
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


@router.get("/approvals", response_model=list[ApprovalRequestResponse])
def list_approvals(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ApprovalRequestResponse]:
    require_permissions(current_user, "automation.approvals.read")
    statement = _filter_by_tenant(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()), ApprovalRequest, current_user)
    if status_filter:
        statement = statement.where(ApprovalRequest.status == status_filter)
    return [_approval_response(item) for item in db.scalars(statement).all()]


@router.patch("/approvals/{approval_id}", response_model=ApprovalRequestResponse)
def patch_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    require_permissions(current_user, "automation.approvals.manage")
    item = db.scalar(_filter_by_tenant(select(ApprovalRequest).where(ApprovalRequest.id == approval_id), ApprovalRequest, current_user))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    decision = request.decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be APPROVED or REJECTED")

    item.status = decision
    item.approver_name = current_user.full_name
    item.decision_comment = request.comment
    item.decided_at = _now()
    log_audit(
        db,
        action="approval_request_decided",
        entity_type="approval_request",
        entity_id=item.id,
        actor_user=_actor(db, current_user),
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"decision": decision},
    )
    db.commit()
    db.refresh(item)
    return _approval_response(item)


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
