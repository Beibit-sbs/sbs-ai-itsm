from __future__ import annotations

import json
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.runbook import Runbook
from app.models.runbook_execution import RunbookExecution
from app.models.job_run import JobRun
from app.services.jobs import (
    JobQueueUnavailableError,
    UnknownTaskError,
    create_job_lifecycle_event,
    create_outbox_entry,
    enqueue_task,
    execute_job,
    get_job as service_get_job,
    job_event_bus_summary,
    job_event_consumers_diagnostics,
    job_event_consumer_autoremediation_preview,
    job_event_consumer_rate_shape_state,
    is_autoremediation_suppressed_now,
    job_event_consumer_recovery_safety_state,
    job_event_consumer_summary,
    job_summary,
    list_job_events,
    list_jobs,
    outbox_diagnostics,
    outbox_summary,
    recover_job_event_consumer_deliveries,
    registered_task_names,
    run_task,
)
from app.services.audit import log_audit
from app.services.jobs.policy_state import PolicyVersionConflictError, load_policy_into_settings, save_policy
from app.services.rbac import has_permission, is_saas_root

router = APIRouter(prefix="/jobs")

ALLOWED_RECOVERY_REASON_CODES = {
    "downstream_outage",
    "transient_dependency_failure",
    "bugfix_rollout",
    "manual_operator_intervention",
    "post_incident_reconciliation",
}


ALLOWED_READ_PERMISSIONS = (
    "admin.settings.read",
    "admin.users.read",
    "security.audit.read",
)


def _require_read(current_user: AuthUserResponse) -> None:
    if is_saas_root(current_user):
        return
    if not any(has_permission(current_user, perm) for perm in ALLOWED_READ_PERMISSIONS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission to read job runs",
        )


def _require_enqueue(current_user: AuthUserResponse) -> None:
    if not is_saas_root(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only saas_root can enqueue jobs",
        )


def _decode(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class JobRunResponse(BaseModel):
    id: str
    task_name: str
    status: str
    tenant_id: str | None
    actor_user_id: str | None
    correlation_id: str | None
    payload: object | None
    result: object | None
    error_message: str | None
    attempts: int
    max_attempts: int
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class JobLifecycleEventResponse(BaseModel):
    id: str
    job_id: str
    event_type: str
    task_name: str
    tenant_id: str | None
    actor_user_id: str | None
    correlation_id: str | None
    previous_status: str | None
    current_status: str
    payload: object | None
    created_at: datetime


class JobSummaryResponse(BaseModel):
    total: int
    queued: int
    running: int
    success: int
    failed: int
    dead_letter: int


class JobRuntimeResponse(BaseModel):
    executor_mode: str
    queue_name: str
    dead_letter_queue_name: str
    event_stream_name: str
    retry_base_seconds: float
    retry_max_seconds: float
    worker_required: bool


class JobOutboxSummaryResponse(BaseModel):
    total: int
    pending: int
    published: int
    with_failures: int


class JobOutboxDiagnosticsResponse(JobOutboxSummaryResponse):
    locked: int
    stale_locks: int
    dedup_skips: int
    publish_failure_rate_pct: float
    pending_alert_threshold: int
    failure_alert_threshold: int
    stale_lock_alert_threshold: int
    status: str
    recommended_actions: list[str]


class JobEventBusSummaryResponse(BaseModel):
    stream_name: str
    total: int
    pending: int
    published: int
    with_failures: int
    locked: int
    stale_locks: int
    failure_rate_pct: float


class JobEventConsumerSummaryResponse(BaseModel):
    consumer_name: str
    stream_name: str
    total: int
    pending: int
    delivered: int
    failed: int


class JobEventConsumerDiagnosticsItemResponse(BaseModel):
    consumer_name: str
    stream_name: str
    total_events: int
    delivery_rows: int
    delivered: int
    pending: int
    failed: int
    retryable_failed: int
    exhausted_failed: int
    unseen_events: int
    lag_events: int
    failure_rate_pct: float
    oldest_undelivered_age_seconds: int
    offset_updated_at: datetime | None
    stale_offset: bool
    recovery_preview_24h: int
    recovery_execute_24h: int
    autoremediation_24h: int
    governance_compliant_execute_24h: int
    governance_missing_execute_24h: int
    last_recovery_execute_at: datetime | None
    last_recovery_execute_actor_email: str | None
    effective_policy_hash: str
    policy_version: int
    policy_canary_mode: bool
    rate_budget_10m_used: int
    rate_budget_10m_limit: int
    rate_budget_1h_used: int
    rate_budget_1h_limit: int
    emergency_brake_active: bool
    emergency_brake_reason: str
    runbook_executions_24h: int
    runbook_governance_compliant_24h: int
    runbook_governance_denied_24h: int
    last_runbook_execution_at: datetime | None
    last_policy_change_at: datetime | None
    last_policy_change_actor_email: str | None
    status: str
    recommended_actions: list[str]


class JobEventConsumersDiagnosticsResponse(BaseModel):
    stream_name: str
    total_events: int
    consumer_count: int
    overall_status: str
    recovery_actions_24h: int
    autoremediation_actions_24h: int
    governance_execute_actions_24h: int
    governance_compliant_actions_24h: int
    governance_compliance_rate_pct: float
    policy_version: int
    policy_rollouts_24h: int
    emergency_brake_consumers: list[str]
    runbook_executions_24h: int
    runbook_failures_24h: int
    runbook_governance_compliant_actions_24h: int
    runbook_governance_denied_actions_24h: int
    recent_runbook_executions: list[dict[str, object]]
    recent_runbook_denied_actions: list[dict[str, object]]
    recent_policy_rollouts: list[dict[str, object]]
    recent_recovery_actions: list[dict[str, object]]
    recent_autoremediation_actions: list[dict[str, object]]
    consumers: list[JobEventConsumerDiagnosticsItemResponse]


class JobEventConsumerRecoveryRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    statuses: list[str] = Field(default_factory=lambda: ["failed", "pending"])
    event_types: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = True
    reason_code: str | None = Field(default=None, min_length=3, max_length=80)
    change_ticket_ref: str | None = Field(default=None, min_length=3, max_length=80)
    approved_by_email: str | None = Field(default=None, min_length=5, max_length=255)


class JobEventConsumerRecoveryItemResponse(BaseModel):
    delivery_id: str
    event_id: str
    event_type: str
    status_before: str
    attempts_before: int
    stream_entry_id: str


class JobEventConsumerRecoveryResponse(BaseModel):
    consumer_name: str
    stream_name: str
    dry_run: bool
    requested_limit: int
    selected: int
    requeued: int
    items: list[JobEventConsumerRecoveryItemResponse]


class JobEventConsumerAutoremediationPreviewItemResponse(BaseModel):
    delivery_id: str
    event_id: str
    event_type: str
    attempts: int
    last_error: str


class JobEventConsumerAutoremediationPreviewResponse(BaseModel):
    consumer_name: str
    stream_name: str
    requested_limit: int
    suppression_active: bool
    suppression_windows_utc: list[str]
    raw_candidates: int
    selected: int
    skipped_by_denylist: int
    effective_policy: dict[str, object]
    items: list[JobEventConsumerAutoremediationPreviewItemResponse]


class JobEventConsumerAutoremediationPolicyResponse(BaseModel):
    consumer_name: str
    policy_version: int
    effective_policy: dict[str, object]
    suppression_windows_utc: list[str]
    error_denylist: list[str]
    emergency_brake_consumers: list[str]
    effective_policy_hash: str
    last_policy_change_at: datetime | None
    last_policy_change_actor_email: str | None


class JobEventConsumerAutoremediationPolicyUpdateRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    expected_version: int = Field(..., ge=1)
    enabled: bool | None = None
    allowed_event_types: list[str] | None = None
    min_failed_age_seconds: int | None = Field(default=None, ge=0)
    max_requeued_per_cycle: int | None = Field(default=None, ge=1, le=200)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    max_per_hour: int | None = Field(default=None, ge=0)
    burst_limit_per_10m: int | None = Field(default=None, ge=0)
    canary_mode: bool | None = None
    canary_limit_per_cycle: int | None = Field(default=None, ge=1, le=200)
    suppression_windows_utc: list[str] | None = None
    error_denylist: list[str] | None = None


class JobEventConsumerAutoremediationBrakeResetRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    expected_version: int = Field(..., ge=1)


class JobEventConsumerRunbookRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    runbook_code: str = Field(..., min_length=3, max_length=120)
    dry_run: bool = True
    limit: int = Field(default=25, ge=1, le=200)
    reason_code: str | None = Field(default=None, min_length=3, max_length=80)
    change_ticket_ref: str | None = Field(default=None, min_length=3, max_length=80)
    approved_by_email: str | None = Field(default=None, min_length=5, max_length=255)


class JobEventConsumerRunbookResponse(BaseModel):
    execution_id: str
    consumer_name: str
    runbook_code: str
    dry_run: bool
    status: str
    guardrail_blocked: bool
    result: dict[str, object]


class EnqueueJobRequest(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=120)
    payload: dict[str, object] | None = None
    tenant_id: str | None = None
    max_attempts: int = Field(default=1, ge=1, le=10)


def _to_response(job: JobRun) -> JobRunResponse:
    return JobRunResponse(
        id=job.id,
        task_name=job.task_name,
        status=job.status,
        tenant_id=job.tenant_id,
        actor_user_id=job.actor_user_id,
        correlation_id=job.correlation_id,
        payload=_decode(job.payload_json),
        result=_decode(job.result_json),
        error_message=job.error_message,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _to_event_response(event) -> JobLifecycleEventResponse:
    return JobLifecycleEventResponse(
        id=event.id,
        job_id=event.job_id,
        event_type=event.event_type,
        task_name=event.task_name,
        tenant_id=event.tenant_id,
        actor_user_id=event.actor_user_id,
        correlation_id=event.correlation_id,
        previous_status=event.previous_status,
        current_status=event.current_status,
        payload=_decode(event.payload_json),
        created_at=event.created_at,
    )


@router.get("", response_model=list[JobRunResponse])
def list_job_runs(
    limit: int = Query(default=50, ge=1, le=200),
    task_name: str | None = Query(default=None, max_length=120),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    tenant_id: str | None = Query(default=None, max_length=36),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobRunResponse]:
    _require_read(current_user)
    scoped_tenant = tenant_id if is_saas_root(current_user) else current_user.tenant_id
    jobs = list_jobs(
        db,
        limit=limit,
        task_name=task_name,
        status=status_filter,
        tenant_id=scoped_tenant,
    )
    return [_to_response(item) for item in jobs]


@router.get("/summary", response_model=JobSummaryResponse)
def get_job_summary(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobSummaryResponse:
    _require_read(current_user)
    scoped_tenant = None if is_saas_root(current_user) else current_user.tenant_id
    data = job_summary(db, tenant_id=scoped_tenant)
    return JobSummaryResponse(**data)


@router.get("/tasks", response_model=list[str])
def list_task_registry(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> list[str]:
    _require_read(current_user)
    return registered_task_names()


@router.get("/runtime", response_model=JobRuntimeResponse)
def get_jobs_runtime(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> JobRuntimeResponse:
    _require_read(current_user)
    settings = get_settings()
    return JobRuntimeResponse(
        executor_mode=settings.jobs_executor_mode,
        queue_name=settings.jobs_queue_name,
        dead_letter_queue_name=settings.jobs_dead_letter_queue_name,
        event_stream_name=settings.jobs_event_stream_name,
        retry_base_seconds=settings.jobs_retry_base_seconds,
        retry_max_seconds=settings.jobs_retry_max_seconds,
        worker_required=settings.jobs_executor_mode == "redis",
    )


@router.get("/event-bus-summary", response_model=JobEventBusSummaryResponse)
def get_job_event_bus_summary(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventBusSummaryResponse:
    _require_read(current_user)
    settings = get_settings()
    data = job_event_bus_summary(db, stream_name=settings.jobs_event_stream_name)
    return JobEventBusSummaryResponse(**data)


@router.get("/event-consumer-summary", response_model=JobEventConsumerSummaryResponse)
def get_job_event_consumer_summary(
    consumer_name: str | None = Query(default=None, max_length=80),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerSummaryResponse:
    _require_read(current_user)
    settings = get_settings()
    selected_consumer = consumer_name or settings.jobs_event_consumer_name
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if selected_consumer not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown consumer_name",
        )
    data = job_event_consumer_summary(
        db,
        consumer_name=selected_consumer,
        stream_name=settings.jobs_event_stream_name,
    )
    return JobEventConsumerSummaryResponse(**data)


@router.get("/event-consumers-diagnostics", response_model=JobEventConsumersDiagnosticsResponse)
def get_job_event_consumers_diagnostics(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumersDiagnosticsResponse:
    _require_read(current_user)
    settings = get_settings()
    policy_state = _policy_state(settings, db)
    data = job_event_consumers_diagnostics(
        db,
        stream_name=settings.jobs_event_stream_name,
        consumer_names=[
            settings.jobs_event_consumer_name,
            settings.jobs_event_automation_consumer_name,
        ],
        max_attempts=settings.jobs_event_consumer_max_attempts,
        lag_alert_threshold=settings.jobs_event_consumer_lag_alert_threshold,
        stale_offset_seconds=settings.jobs_event_consumer_stale_offset_seconds,
    )
    consumers = data.get("consumers", [])
    consumer_names = [str(item.get("consumer_name") or "") for item in consumers if isinstance(item, dict)]
    policy_changes = _latest_policy_change_map(db, consumer_names)
    rollouts_24h, recent_rollouts = _recent_policy_rollouts(db)
    (
        runbook_execs_24h,
        runbook_failures_24h,
        recent_runbooks,
        per_consumer_runbooks,
        runbook_governance_compliant_actions_24h,
        runbook_governance_denied_actions_24h,
        recent_runbook_denied_actions,
    ) = _recent_jobs_runbook_metrics(db, consumer_names)
    for item in consumers:
        if not isinstance(item, dict):
            continue
        consumer_name = str(item.get("consumer_name") or "")
        effective_policy = _effective_autoremediation_policy(settings, consumer_name)
        rate_shape = job_event_consumer_rate_shape_state(
            db,
            consumer_name=consumer_name,
            burst_limit_per_10m=int(effective_policy.get("burst_limit_per_10m", 0) or 0),
            steady_limit_per_hour=int(effective_policy.get("max_per_hour", 0) or 0),
        )
        item["effective_policy_hash"] = _policy_hash(effective_policy)
        item["policy_version"] = int(policy_state.get("version", 1) or 1)
        item["policy_canary_mode"] = bool(effective_policy.get("canary_mode", False))
        item["rate_budget_10m_used"] = int(rate_shape.get("executed_10m", 0) or 0)
        item["rate_budget_10m_limit"] = int(rate_shape.get("burst_limit_per_10m", 0) or 0)
        item["rate_budget_1h_used"] = int(rate_shape.get("executed_1h", 0) or 0)
        item["rate_budget_1h_limit"] = int(rate_shape.get("steady_limit_per_hour", 0) or 0)
        brake_active = consumer_name in settings.jobs_event_autoremediation_braked_consumers
        item["emergency_brake_active"] = brake_active
        item["emergency_brake_reason"] = "error_threshold_exceeded_15m" if brake_active else ""
        runbook_meta = per_consumer_runbooks.get(consumer_name, {})
        item["runbook_executions_24h"] = int(runbook_meta.get("count", 0) or 0)
        item["runbook_governance_compliant_24h"] = int(runbook_meta.get("governance_compliant", 0) or 0)
        item["runbook_governance_denied_24h"] = int(runbook_meta.get("governance_denied", 0) or 0)
        item["last_runbook_execution_at"] = runbook_meta.get("last_at")
        policy_change = policy_changes.get(consumer_name, {})
        item["last_policy_change_at"] = policy_change.get("created_at")
        item["last_policy_change_actor_email"] = policy_change.get("actor_email")
    data["policy_version"] = int(policy_state.get("version", 1) or 1)
    data["policy_rollouts_24h"] = int(rollouts_24h)
    data["emergency_brake_consumers"] = [
        str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()
    ]
    data["runbook_executions_24h"] = int(runbook_execs_24h)
    data["runbook_failures_24h"] = int(runbook_failures_24h)
    data["runbook_governance_compliant_actions_24h"] = int(runbook_governance_compliant_actions_24h)
    data["runbook_governance_denied_actions_24h"] = int(runbook_governance_denied_actions_24h)
    data["recent_runbook_executions"] = recent_runbooks
    data["recent_runbook_denied_actions"] = recent_runbook_denied_actions
    data["recent_policy_rollouts"] = recent_rollouts
    return JobEventConsumersDiagnosticsResponse(**data)


def _effective_autoremediation_policy(settings, consumer_name: str) -> dict[str, object]:
    profile_raw = settings.jobs_event_autoremediation_policy_profiles.get(consumer_name, {})
    profile = profile_raw if isinstance(profile_raw, dict) else {}

    allowed_event_types = profile.get("allowed_event_types", settings.jobs_event_autoremediation_allowed_event_types)
    if not isinstance(allowed_event_types, list):
        allowed_event_types = settings.jobs_event_autoremediation_allowed_event_types

    return {
        "enabled": bool(profile.get("enabled", True)),
        "min_failed_age_seconds": int(
            profile.get("min_failed_age_seconds", settings.jobs_event_autoremediation_min_failed_age_seconds)
        ),
        "max_requeued_per_cycle": int(
            profile.get("max_requeued_per_cycle", settings.jobs_event_autoremediation_max_requeued_per_cycle)
        ),
        "cooldown_seconds": int(profile.get("cooldown_seconds", settings.jobs_event_autoremediation_cooldown_seconds)),
        "max_per_hour": int(profile.get("max_per_hour", settings.jobs_event_autoremediation_max_per_hour)),
        "canary_mode": bool(profile.get("canary_mode", settings.jobs_event_autoremediation_canary_mode)),
        "canary_limit_per_cycle": int(
            profile.get("canary_limit_per_cycle", settings.jobs_event_autoremediation_canary_limit_per_cycle)
        ),
        "burst_limit_per_10m": int(
            profile.get("burst_limit_per_10m", settings.jobs_event_autoremediation_burst_max_per_10m)
        ),
        "allowed_event_types": [str(item) for item in allowed_event_types if str(item).strip()],
    }


def _policy_hash(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _latest_policy_change_map(db: Session, consumer_names: list[str]) -> dict[str, dict[str, object]]:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_autoremediation_policy.update")
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
    )
    out: dict[str, dict[str, object]] = {}
    for row in rows:
        metadata = _decode(row.metadata_json)
        if not isinstance(metadata, dict):
            continue
        consumer = str(metadata.get("consumer_name") or "")
        if consumer not in consumer_names:
            continue
        if consumer in out:
            continue
        out[consumer] = {
            "created_at": row.created_at,
            "actor_email": row.actor_email,
        }
    return out


def _jobs_runbook_catalog() -> dict[str, dict[str, object]]:
    return {
        "jobs.consumer.repeated_failures_requeue": {
            "title": "Consumer repeated failures requeue",
            "description": "Bounded replay of failed consumer deliveries for repeated failure incidents.",
            "severity": "high",
            "category": "jobs",
            "steps": [
                {"step": 1, "action": "inspect_failed_deliveries"},
                {"step": 2, "action": "bounded_requeue"},
            ],
        },
        "jobs.consumer.lag_spike_triage": {
            "title": "Consumer lag spike triage",
            "description": "Capture deterministic triage snapshot for lag spike incidents.",
            "severity": "medium",
            "category": "jobs",
            "steps": [
                {"step": 1, "action": "capture_lag_snapshot"},
                {"step": 2, "action": "recommend_worker_health_checks"},
            ],
        },
        "jobs.consumer.stale_offset_triage": {
            "title": "Consumer stale offset triage",
            "description": "Capture deterministic triage snapshot for stale offset incidents.",
            "severity": "medium",
            "category": "jobs",
            "steps": [
                {"step": 1, "action": "capture_offset_snapshot"},
                {"step": 2, "action": "recommend_offset_remediation"},
            ],
        },
        "jobs.consumer.emergency_brake_reset": {
            "title": "Consumer emergency brake reset",
            "description": "Release emergency brake for a consumer after operator validation.",
            "severity": "high",
            "category": "jobs",
            "steps": [
                {"step": 1, "action": "verify_brake_state"},
                {"step": 2, "action": "reset_brake"},
            ],
        },
    }


def _get_or_create_jobs_runbook(db: Session, *, code: str) -> Runbook:
    catalog = _jobs_runbook_catalog()
    if code not in catalog:
        raise ValueError("Unknown runbook_code")
    row = db.scalar(select(Runbook).where(Runbook.code == code))
    if row is not None:
        return row
    meta = catalog[code]
    row = Runbook(
        id=str(uuid.uuid4()),
        tenant_id=None,
        name=code,
        code=code,
        title=str(meta["title"]),
        description=str(meta["description"]),
        category=str(meta["category"]),
        severity=str(meta["severity"]),
        steps_json=json.dumps(meta["steps"], ensure_ascii=False),
        estimated_minutes=10,
        is_active=True,
        requires_approval=False,
        created_by_id=None,
        updated_by_id=None,
    )
    db.add(row)
    db.flush()
    return row


def _create_jobs_runbook_execution(
    db: Session,
    *,
    runbook: Runbook,
    consumer_name: str,
    started_by: str,
    dry_run: bool,
    status: str,
    result: dict[str, object],
    reason_code: str,
    change_ticket_ref: str,
    approved_by_email: str,
    governance_compliant: bool,
) -> RunbookExecution:
    execution = RunbookExecution(
        id=str(uuid.uuid4()),
        tenant_id=None,
        runbook_id=runbook.id,
        ticket_id=None,
        status=status,
        current_step=2,
        started_by=started_by,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result_summary=json.dumps(
            {
                "consumer_name": consumer_name,
                "runbook_code": runbook.code,
                "dry_run": dry_run,
                "status": status,
                "reason_code": reason_code,
                "change_ticket_ref": change_ticket_ref,
                "approved_by_email": approved_by_email,
                "governance_compliant": governance_compliant,
                "result": result,
            },
            ensure_ascii=False,
        ),
    )
    db.add(execution)
    db.flush()
    return execution


def _recent_jobs_runbook_metrics(
    db: Session,
    consumer_names: list[str],
) -> tuple[int, int, list[dict[str, object]], dict[str, dict[str, object]], int, int, list[dict[str, object]]]:
    window_start = datetime.now(UTC) - timedelta(hours=24)
    rows = list(
        db.scalars(
            select(RunbookExecution)
            .join(Runbook, Runbook.id == RunbookExecution.runbook_id)
            .where(Runbook.code.like("jobs.consumer.%"))
            .where(RunbookExecution.created_at >= window_start)
            .order_by(RunbookExecution.created_at.desc())
            .limit(200)
        ).all()
    )
    recent: list[dict[str, object]] = []
    per_consumer: dict[str, dict[str, object]] = {
        name: {"count": 0, "last_at": None, "governance_compliant": 0, "governance_denied": 0}
        for name in consumer_names
    }
    failures = 0
    governance_compliant_actions = 0
    for row in rows:
        summary = _decode(row.result_summary)
        if not isinstance(summary, dict):
            summary = {}
        consumer_name = str(summary.get("consumer_name") or "")
        governance_compliant = bool(summary.get("governance_compliant", False))
        if consumer_name in per_consumer:
            per_consumer[consumer_name]["count"] = int(per_consumer[consumer_name]["count"] or 0) + 1
            if governance_compliant:
                per_consumer[consumer_name]["governance_compliant"] = (
                    int(per_consumer[consumer_name]["governance_compliant"] or 0) + 1
                )
            if per_consumer[consumer_name]["last_at"] is None:
                per_consumer[consumer_name]["last_at"] = row.completed_at or row.created_at
        if governance_compliant:
            governance_compliant_actions += 1
        if row.status in {"failed", "guardrail_blocked"}:
            failures += 1
        if len(recent) < 12:
            recent.append(
                {
                    "execution_id": row.id,
                    "consumer_name": consumer_name,
                    "status": row.status,
                    "started_by": row.started_by,
                    "created_at": row.created_at,
                    "runbook_code": str(summary.get("runbook_code") or ""),
                    "dry_run": bool(summary.get("dry_run", False)),
                    "governance_compliant": governance_compliant,
                }
            )

    denied_rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_runbook.denied")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
    )
    recent_denied: list[dict[str, object]] = []
    for row in denied_rows:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        consumer_name = str(metadata_map.get("consumer_name") or "")
        if consumer_name in per_consumer:
            per_consumer[consumer_name]["governance_denied"] = int(
                per_consumer[consumer_name]["governance_denied"] or 0
            ) + 1
        if len(recent_denied) < 12:
            recent_denied.append(
                {
                    "consumer_name": consumer_name,
                    "runbook_code": str(metadata_map.get("runbook_code") or ""),
                    "denial_reason": str(metadata_map.get("denial_reason") or ""),
                    "detail": str(metadata_map.get("detail") or ""),
                    "actor_email": row.actor_email,
                    "created_at": row.created_at,
                }
            )

    return (
        len(rows),
        failures,
        recent,
        per_consumer,
        governance_compliant_actions,
        len(denied_rows),
        recent_denied,
    )


def _runbook_policy(settings) -> dict[str, object]:
    catalog_codes = set(_jobs_runbook_catalog().keys())

    allowed_raw = [str(item).strip() for item in settings.jobs_event_runbook_allowed_codes if str(item).strip()]
    denied_raw = [str(item).strip() for item in settings.jobs_event_runbook_denied_codes if str(item).strip()]
    high_impact_raw = [str(item).strip() for item in settings.jobs_event_runbook_high_impact_codes if str(item).strip()]

    allowed_codes = [code for code in allowed_raw if code in catalog_codes]
    denied_codes = [code for code in denied_raw if code in catalog_codes]
    high_impact_codes = [code for code in high_impact_raw if code in catalog_codes]

    cooldown_raw = (
        settings.jobs_event_runbook_cooldown_seconds_map
        if isinstance(settings.jobs_event_runbook_cooldown_seconds_map, dict)
        else {}
    )
    cooldown_seconds: dict[str, int] = {}
    for key, value in cooldown_raw.items():
        code = str(key).strip()
        if not code or code not in catalog_codes:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        cooldown_seconds[code] = max(0, parsed)

    return {
        "catalog_codes": catalog_codes,
        "allowed_codes": set(allowed_codes),
        "denied_codes": set(denied_codes),
        "high_impact_codes": set(high_impact_codes),
        "cooldown_seconds": cooldown_seconds,
        "require_change_ticket": bool(settings.jobs_event_runbook_require_change_ticket),
        "dual_control_required": bool(settings.jobs_event_runbook_dual_control_required),
    }


def _runbook_execution_cooldown_state(
    db: Session,
    *,
    consumer_name: str,
    runbook_code: str,
    cooldown_seconds: int,
) -> dict[str, object]:
    if cooldown_seconds <= 0:
        return {
            "cooldown_active": False,
            "retry_after_seconds": 0,
            "last_executed_at": None,
        }
    now = datetime.now(UTC)
    window_start = now - timedelta(seconds=cooldown_seconds)
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_runbook.execute")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
    )
    for row in rows:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        if str(metadata_map.get("consumer_name") or "") != consumer_name:
            continue
        if str(metadata_map.get("runbook_code") or "") != runbook_code:
            continue
        created_at = row.created_at if row.created_at.tzinfo is not None else row.created_at.replace(tzinfo=UTC)
        elapsed = int((now - created_at).total_seconds())
        remaining = max(0, cooldown_seconds - elapsed)
        if remaining > 0:
            return {
                "cooldown_active": True,
                "retry_after_seconds": remaining,
                "last_executed_at": created_at,
            }
    return {
        "cooldown_active": False,
        "retry_after_seconds": 0,
        "last_executed_at": None,
    }


def _policy_state(settings, db: Session) -> dict[str, object]:
    return load_policy_into_settings(db, settings)


def _recent_policy_rollouts(db: Session) -> tuple[int, list[dict[str, object]]]:
    window_start = datetime.now(UTC) - timedelta(hours=24)
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_autoremediation_policy.update")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        ).all()
    )
    items: list[dict[str, object]] = []
    for row in rows[:12]:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        items.append(
            {
                "consumer_name": str(metadata_map.get("consumer_name") or ""),
                "old_policy_hash": str(metadata_map.get("old_policy_hash") or ""),
                "new_policy_hash": str(metadata_map.get("new_policy_hash") or ""),
                "actor_email": row.actor_email,
                "created_at": row.created_at,
            }
        )
    return len(rows), items


@router.get(
    "/event-consumer-autoremediation-preview",
    response_model=JobEventConsumerAutoremediationPreviewResponse,
)
def get_job_event_consumer_autoremediation_preview(
    consumer_name: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerAutoremediationPreviewResponse:
    _require_read(current_user)
    settings = get_settings()
    _policy_state(settings, db)
    selected_consumer = consumer_name or settings.jobs_event_consumer_name
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if selected_consumer not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")

    effective_policy = _effective_autoremediation_policy(settings, selected_consumer)
    suppression_windows_utc = [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item]
    suppression_active = is_autoremediation_suppressed_now(now=datetime.now(UTC), windows_utc=suppression_windows_utc)

    data = job_event_consumer_autoremediation_preview(
        db,
        consumer_name=selected_consumer,
        stream_name=settings.jobs_event_stream_name,
        max_attempts=settings.jobs_event_consumer_max_attempts,
        min_failed_age_seconds=max(0, int(effective_policy["min_failed_age_seconds"])),
        allowed_event_types=[str(item) for item in effective_policy["allowed_event_types"]],
        error_denylist=[str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
        limit=min(limit, int(effective_policy["max_requeued_per_cycle"])),
    )
    return JobEventConsumerAutoremediationPreviewResponse(
        consumer_name=str(data["consumer_name"]),
        stream_name=str(data["stream_name"]),
        requested_limit=int(data["requested_limit"]),
        suppression_active=suppression_active,
        suppression_windows_utc=suppression_windows_utc,
        raw_candidates=int(data["raw_candidates"]),
        selected=int(data["selected"]),
        skipped_by_denylist=int(data["skipped_by_denylist"]),
        effective_policy=effective_policy,
        items=[JobEventConsumerAutoremediationPreviewItemResponse(**item) for item in data["items"]],
    )


@router.get(
    "/event-consumer-autoremediation-policy",
    response_model=JobEventConsumerAutoremediationPolicyResponse,
)
def get_job_event_consumer_autoremediation_policy(
    consumer_name: str | None = Query(default=None, max_length=80),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerAutoremediationPolicyResponse:
    _require_read(current_user)
    settings = get_settings()
    policy_state = _policy_state(settings, db)
    selected_consumer = consumer_name or settings.jobs_event_consumer_name
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if selected_consumer not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")

    effective_policy = _effective_autoremediation_policy(settings, selected_consumer)
    policy_changes = _latest_policy_change_map(db, [selected_consumer])
    policy_change = policy_changes.get(selected_consumer, {})
    return JobEventConsumerAutoremediationPolicyResponse(
        consumer_name=selected_consumer,
        policy_version=int(policy_state.get("version", 1) or 1),
        effective_policy=effective_policy,
        suppression_windows_utc=[str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item],
        error_denylist=[str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
        emergency_brake_consumers=[
            str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()
        ],
        effective_policy_hash=_policy_hash(effective_policy),
        last_policy_change_at=policy_change.get("created_at"),
        last_policy_change_actor_email=policy_change.get("actor_email"),
    )


@router.post(
    "/event-consumer-autoremediation-policy",
    response_model=JobEventConsumerAutoremediationPolicyResponse,
)
def update_job_event_consumer_autoremediation_policy(
    request: JobEventConsumerAutoremediationPolicyUpdateRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerAutoremediationPolicyResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    policy_state = _policy_state(settings, db)
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if request.consumer_name not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")

    profile_map = (
        dict(settings.jobs_event_autoremediation_policy_profiles)
        if isinstance(settings.jobs_event_autoremediation_policy_profiles, dict)
        else {}
    )
    old_effective = _effective_autoremediation_policy(settings, request.consumer_name)
    profile_raw = profile_map.get(request.consumer_name, {})
    profile = dict(profile_raw) if isinstance(profile_raw, dict) else {}

    updates: dict[str, object | None] = {
        "enabled": request.enabled,
        "allowed_event_types": request.allowed_event_types,
        "min_failed_age_seconds": request.min_failed_age_seconds,
        "max_requeued_per_cycle": request.max_requeued_per_cycle,
        "cooldown_seconds": request.cooldown_seconds,
        "max_per_hour": request.max_per_hour,
        "burst_limit_per_10m": request.burst_limit_per_10m,
        "canary_mode": request.canary_mode,
        "canary_limit_per_cycle": request.canary_limit_per_cycle,
    }
    for key, value in updates.items():
        if value is not None:
            profile[key] = value

    profile_map[request.consumer_name] = profile

    suppression_windows = (
        [str(item).strip() for item in request.suppression_windows_utc if str(item).strip()]
        if request.suppression_windows_utc is not None
        else [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item]
    )
    error_denylist = (
        [str(item).strip() for item in request.error_denylist if str(item).strip()]
        if request.error_denylist is not None
        else [str(item) for item in settings.jobs_event_autoremediation_error_denylist if item]
    )

    payload = {
        "policy_profiles": profile_map,
        "suppression_windows_utc": suppression_windows,
        "error_denylist": error_denylist,
        "canary_mode": bool(settings.jobs_event_autoremediation_canary_mode),
        "canary_limit_per_cycle": int(settings.jobs_event_autoremediation_canary_limit_per_cycle),
        "burst_max_per_10m": int(settings.jobs_event_autoremediation_burst_max_per_10m),
        "brake_error_threshold": int(settings.jobs_event_autoremediation_brake_error_threshold),
        "braked_consumers": [str(item) for item in settings.jobs_event_autoremediation_braked_consumers if item],
    }

    try:
        saved_state = save_policy(
            db,
            settings,
            payload=payload,
            expected_version=request.expected_version,
            actor_email=current_user.email,
        )
    except PolicyVersionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    new_effective = _effective_autoremediation_policy(settings, request.consumer_name)
    old_hash = _policy_hash(old_effective)
    new_hash = _policy_hash(new_effective)
    log_audit(
        db,
        action="jobs.event_consumer_autoremediation_policy.update",
        entity_type="job_event_consumer_policy",
        entity_id=request.consumer_name,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "consumer_name": request.consumer_name,
            "old_policy_hash": old_hash,
            "new_policy_hash": new_hash,
            "previous_version": int(policy_state.get("version", 1) or 1),
            "new_version": int(saved_state.get("version", 1) or 1),
            "suppression_windows_utc": suppression_windows,
            "error_denylist": error_denylist,
        },
    )
    db.commit()
    return JobEventConsumerAutoremediationPolicyResponse(
        consumer_name=request.consumer_name,
        policy_version=int(saved_state.get("version", 1) or 1),
        effective_policy=new_effective,
        suppression_windows_utc=suppression_windows,
        error_denylist=error_denylist,
        emergency_brake_consumers=[
            str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()
        ],
        effective_policy_hash=new_hash,
        last_policy_change_at=saved_state.get("updated_at"),
        last_policy_change_actor_email=current_user.email,
    )


@router.post(
    "/event-consumer-autoremediation-brake-reset",
    response_model=JobEventConsumerAutoremediationPolicyResponse,
)
def reset_job_event_consumer_autoremediation_brake(
    request: JobEventConsumerAutoremediationBrakeResetRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerAutoremediationPolicyResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    policy_state = _policy_state(settings, db)
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if request.consumer_name not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")

    remaining = [
        str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item) != request.consumer_name
    ]
    payload = {
        "policy_profiles": (
            settings.jobs_event_autoremediation_policy_profiles
            if isinstance(settings.jobs_event_autoremediation_policy_profiles, dict)
            else {}
        ),
        "suppression_windows_utc": [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item],
        "error_denylist": [str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
        "canary_mode": bool(settings.jobs_event_autoremediation_canary_mode),
        "canary_limit_per_cycle": int(settings.jobs_event_autoremediation_canary_limit_per_cycle),
        "burst_max_per_10m": int(settings.jobs_event_autoremediation_burst_max_per_10m),
        "brake_error_threshold": int(settings.jobs_event_autoremediation_brake_error_threshold),
        "braked_consumers": remaining,
    }
    try:
        saved_state = save_policy(
            db,
            settings,
            payload=payload,
            expected_version=request.expected_version,
            actor_email=current_user.email,
        )
    except PolicyVersionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    effective_policy = _effective_autoremediation_policy(settings, request.consumer_name)
    log_audit(
        db,
        action="jobs.event_consumer_autoremediation_brake.reset",
        entity_type="job_event_consumer_policy",
        entity_id=request.consumer_name,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "consumer_name": request.consumer_name,
            "previous_version": int(policy_state.get("version", 1) or 1),
            "new_version": int(saved_state.get("version", 1) or 1),
        },
    )
    db.commit()
    return JobEventConsumerAutoremediationPolicyResponse(
        consumer_name=request.consumer_name,
        policy_version=int(saved_state.get("version", 1) or 1),
        effective_policy=effective_policy,
        suppression_windows_utc=[str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item],
        error_denylist=[str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
        emergency_brake_consumers=[str(item) for item in remaining if str(item).strip()],
        effective_policy_hash=_policy_hash(effective_policy),
        last_policy_change_at=saved_state.get("updated_at"),
        last_policy_change_actor_email=current_user.email,
    )


@router.post("/event-consumer-runbook", response_model=JobEventConsumerRunbookResponse)
def execute_job_event_consumer_runbook(
    request: JobEventConsumerRunbookRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    runbook_confirm: str | None = Header(default=None, alias="X-Runbook-Confirm"),
) -> JobEventConsumerRunbookResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    _policy_state(settings, db)
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if request.consumer_name not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")
    if request.runbook_code not in _jobs_runbook_catalog():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown runbook_code")

    runbook_policy = _runbook_policy(settings)
    denied_codes = runbook_policy["denied_codes"]
    allowed_codes = runbook_policy["allowed_codes"]
    high_impact_codes = runbook_policy["high_impact_codes"]
    cooldown_seconds_map = runbook_policy["cooldown_seconds"]

    def _deny(detail: str, denial_reason: str, status_code: int) -> None:
        log_audit(
            db,
            action="jobs.event_consumer_runbook.denied",
            entity_type="runbook_execution",
            entity_id=request.runbook_code,
            actor_email=current_user.email,
            tenant_id=current_user.tenant_id,
            metadata={
                "consumer_name": request.consumer_name,
                "runbook_code": request.runbook_code,
                "dry_run": request.dry_run,
                "denial_reason": denial_reason,
                "detail": detail,
            },
        )
        db.commit()
        raise HTTPException(status_code=status_code, detail=detail)

    if request.runbook_code in denied_codes:
        _deny("Runbook is denied by governance policy", "runbook_denied_by_policy", status.HTTP_403_FORBIDDEN)
    if allowed_codes and request.runbook_code not in allowed_codes:
        _deny("Runbook is not allowlisted by governance policy", "runbook_not_allowlisted", status.HTTP_403_FORBIDDEN)

    governance_compliant = True
    reason_code = (request.reason_code or "").strip().lower()
    change_ticket_ref = (request.change_ticket_ref or "").strip()
    approved_by_email = (request.approved_by_email or "").strip().lower()

    if not request.dry_run and request.runbook_code in high_impact_codes:
        governance_compliant = False
        if reason_code not in ALLOWED_RECOVERY_REASON_CODES:
            _deny(
                "reason_code is required and must be one of allowed governance codes",
                "missing_or_invalid_reason_code",
                status.HTTP_400_BAD_REQUEST,
            )
        if bool(runbook_policy["require_change_ticket"]) and not change_ticket_ref:
            _deny("change_ticket_ref is required for execute runbook", "missing_change_ticket_ref", status.HTTP_400_BAD_REQUEST)
        if bool(runbook_policy["dual_control_required"]):
            if not approved_by_email:
                _deny(
                    "approved_by_email is required when runbook dual-control mode is enabled",
                    "missing_approved_by_email",
                    status.HTTP_400_BAD_REQUEST,
                )
            if approved_by_email == current_user.email.lower():
                _deny(
                    "approved_by_email must be different from actor",
                    "invalid_dual_control_approver",
                    status.HTTP_400_BAD_REQUEST,
                )
        governance_compliant = True

    if not request.dry_run:
        cooldown_state = _runbook_execution_cooldown_state(
            db,
            consumer_name=request.consumer_name,
            runbook_code=request.runbook_code,
            cooldown_seconds=int(cooldown_seconds_map.get(request.runbook_code, 0) or 0),
        )
        if bool(cooldown_state.get("cooldown_active")):
            _deny(
                f"Runbook cooldown active; retry after {int(cooldown_state.get('retry_after_seconds') or 0)}s",
                "runbook_cooldown_active",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )

    if not request.dry_run and runbook_confirm != "CONFIRM":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Execution requires header X-Runbook-Confirm: CONFIRM")

    diagnostics = job_event_consumers_diagnostics(
        db,
        stream_name=settings.jobs_event_stream_name,
        consumer_names=[settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name],
        max_attempts=settings.jobs_event_consumer_max_attempts,
        lag_alert_threshold=settings.jobs_event_consumer_lag_alert_threshold,
        stale_offset_seconds=settings.jobs_event_consumer_stale_offset_seconds,
    )
    consumer_diag = next(
        (item for item in diagnostics.get("consumers", []) if item.get("consumer_name") == request.consumer_name),
        None,
    )
    if not isinstance(consumer_diag, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consumer diagnostics not found")

    runbook = _get_or_create_jobs_runbook(db, code=request.runbook_code)
    status_value = "dry_run" if request.dry_run else "success"
    guardrail_blocked = False
    result: dict[str, object]

    if request.runbook_code == "jobs.consumer.repeated_failures_requeue":
        if int(consumer_diag.get("failed", 0) or 0) <= 0:
            guardrail_blocked = True
            status_value = "guardrail_blocked"
            result = {"reason": "no_failed_deliveries", "consumer_name": request.consumer_name}
        else:
            recovery = recover_job_event_consumer_deliveries(
                db,
                consumer_name=request.consumer_name,
                stream_name=settings.jobs_event_stream_name,
                statuses=["failed"],
                event_types=None,
                limit=request.limit,
                dry_run=request.dry_run,
            )
            result = {
                "consumer_name": request.consumer_name,
                "selected": int(recovery.get("selected", 0) or 0),
                "requeued": int(recovery.get("requeued", 0) or 0),
            }
    elif request.runbook_code == "jobs.consumer.lag_spike_triage":
        if int(consumer_diag.get("lag_events", 0) or 0) <= 0:
            guardrail_blocked = True
            status_value = "guardrail_blocked"
            result = {"reason": "no_lag_spike_detected", "consumer_name": request.consumer_name}
        else:
            result = {
                "consumer_name": request.consumer_name,
                "lag_events": int(consumer_diag.get("lag_events", 0) or 0),
                "recommended_actions": list(consumer_diag.get("recommended_actions") or []),
            }
    elif request.runbook_code == "jobs.consumer.stale_offset_triage":
        if not bool(consumer_diag.get("stale_offset", False)):
            guardrail_blocked = True
            status_value = "guardrail_blocked"
            result = {"reason": "offset_not_stale", "consumer_name": request.consumer_name}
        else:
            result = {
                "consumer_name": request.consumer_name,
                "offset_updated_at": consumer_diag.get("offset_updated_at"),
                "oldest_undelivered_age_seconds": int(consumer_diag.get("oldest_undelivered_age_seconds", 0) or 0),
            }
    else:
        policy = get_job_event_consumer_autoremediation_policy(
            consumer_name=request.consumer_name,
            current_user=current_user,
            db=db,
        )
        if request.consumer_name not in policy.emergency_brake_consumers:
            guardrail_blocked = True
            status_value = "guardrail_blocked"
            result = {"reason": "emergency_brake_not_active", "consumer_name": request.consumer_name}
        elif request.dry_run:
            result = {
                "consumer_name": request.consumer_name,
                "would_reset_brake": True,
                "policy_version": policy.policy_version,
            }
        else:
            brake_request = JobEventConsumerAutoremediationBrakeResetRequest(
                consumer_name=request.consumer_name,
                expected_version=policy.policy_version,
            )
            reset_result = reset_job_event_consumer_autoremediation_brake(
                request=brake_request,
                current_user=current_user,
                db=db,
            )
            result = {
                "consumer_name": request.consumer_name,
                "policy_version": reset_result.policy_version,
                "emergency_brake_consumers": reset_result.emergency_brake_consumers,
            }

    execution = _create_jobs_runbook_execution(
        db,
        runbook=runbook,
        consumer_name=request.consumer_name,
        started_by=current_user.email,
        dry_run=request.dry_run,
        status=status_value,
        result=result,
        reason_code=reason_code,
        change_ticket_ref=change_ticket_ref,
        approved_by_email=approved_by_email,
        governance_compliant=governance_compliant,
    )
    log_audit(
        db,
        action="jobs.event_consumer_runbook.dry_run" if request.dry_run else "jobs.event_consumer_runbook.execute",
        entity_type="runbook_execution",
        entity_id=execution.id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "consumer_name": request.consumer_name,
            "runbook_code": request.runbook_code,
            "dry_run": request.dry_run,
            "status": status_value,
            "guardrail_blocked": guardrail_blocked,
            "reason_code": reason_code,
            "change_ticket_ref": change_ticket_ref,
            "approved_by_email": approved_by_email,
            "governance_compliant": governance_compliant,
        },
    )
    db.commit()
    return JobEventConsumerRunbookResponse(
        execution_id=execution.id,
        consumer_name=request.consumer_name,
        runbook_code=request.runbook_code,
        dry_run=request.dry_run,
        status=status_value,
        guardrail_blocked=guardrail_blocked,
        result=result,
    )


@router.post("/event-consumer-recovery", response_model=JobEventConsumerRecoveryResponse)
def recover_job_event_consumer(
    request: JobEventConsumerRecoveryRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    recovery_confirm: str | None = Header(default=None, alias="X-Recovery-Confirm"),
) -> JobEventConsumerRecoveryResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    allowed_consumers = {
        settings.jobs_event_consumer_name,
        settings.jobs_event_automation_consumer_name,
    }
    if request.consumer_name not in allowed_consumers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")
    allowed_statuses = {"failed", "pending"}
    normalized_statuses = [item.strip().lower() for item in request.statuses if item and item.strip()]
    if not normalized_statuses or any(item not in allowed_statuses for item in normalized_statuses):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="statuses must be failed and/or pending")
    if not request.dry_run and recovery_confirm != "CONFIRM":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execution requires header X-Recovery-Confirm: CONFIRM",
        )
    reason_code = (request.reason_code or "").strip().lower()
    change_ticket_ref = (request.change_ticket_ref or "").strip()
    approved_by_email = (request.approved_by_email or "").strip().lower()
    if not request.dry_run:
        if reason_code not in ALLOWED_RECOVERY_REASON_CODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="reason_code is required and must be one of allowed governance codes",
            )
        if settings.jobs_event_recovery_require_change_ticket and not change_ticket_ref:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="change_ticket_ref is required for execute recovery",
            )
        if settings.jobs_event_recovery_dual_control_required:
            if not approved_by_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="approved_by_email is required when dual-control mode is enabled",
                )
            if approved_by_email == current_user.email.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="approved_by_email must be different from actor",
                )

    if not request.dry_run:
        safety = job_event_consumer_recovery_safety_state(
            db,
            consumer_name=request.consumer_name,
            cooldown_seconds=settings.jobs_event_recovery_cooldown_seconds,
            max_exec_per_hour=settings.jobs_event_recovery_max_exec_per_hour,
        )
        if bool(safety.get("cooldown_active")):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Recovery cooldown active; retry after {int(safety.get('retry_after_seconds') or 0)}s",
            )
        if bool(safety.get("rate_limit_exceeded")):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Recovery hourly rate limit exceeded",
            )

    data = recover_job_event_consumer_deliveries(
        db,
        consumer_name=request.consumer_name,
        stream_name=settings.jobs_event_stream_name,
        statuses=normalized_statuses,
        event_types=request.event_types,
        limit=request.limit,
        dry_run=request.dry_run,
    )
    log_audit(
        db,
        action="jobs.event_consumer_recovery.preview" if request.dry_run else "jobs.event_consumer_recovery.execute",
        entity_type="job_event_consumer_delivery",
        entity_id=request.consumer_name,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "consumer_name": request.consumer_name,
            "statuses": normalized_statuses,
            "event_types": request.event_types or [],
            "limit": request.limit,
            "dry_run": request.dry_run,
            "selected": int(data.get("selected", 0) or 0),
            "requeued": int(data.get("requeued", 0) or 0),
            "reason_code": reason_code,
            "change_ticket_ref": change_ticket_ref,
            "approved_by_email": approved_by_email,
        },
    )
    if not request.dry_run:
        db.commit()
    else:
        db.flush()
        db.commit()
    return JobEventConsumerRecoveryResponse(**data)


@router.get("/outbox-summary", response_model=JobOutboxSummaryResponse)
def get_jobs_outbox_summary(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOutboxSummaryResponse:
    _require_read(current_user)
    settings = get_settings()
    data = outbox_summary(db, queue_name=settings.jobs_queue_name)
    return JobOutboxSummaryResponse(**data)


@router.get("/outbox-diagnostics", response_model=JobOutboxDiagnosticsResponse)
def get_jobs_outbox_diagnostics(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOutboxDiagnosticsResponse:
    _require_read(current_user)
    settings = get_settings()
    data = outbox_diagnostics(db, queue_name=settings.jobs_queue_name)
    return JobOutboxDiagnosticsResponse(**data)


@router.get("/{job_id}", response_model=JobRunResponse)
def get_job_run(
    job_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobRunResponse:
    _require_read(current_user)
    job = service_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not is_saas_root(current_user):
        if job.tenant_id is not None and job.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_response(job)


@router.get("/{job_id}/events", response_model=list[JobLifecycleEventResponse])
def get_job_run_events(
    job_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobLifecycleEventResponse]:
    _require_read(current_user)
    job = service_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not is_saas_root(current_user):
        if job.tenant_id is not None and job.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return [_to_event_response(event) for event in list_job_events(db, job_id)]


@router.post("/{job_id}/replay", response_model=JobRunResponse)
async def replay_dead_letter_job(
    job_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobRunResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    job = service_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != "dead_letter":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only dead-letter jobs can be replayed")

    previous_status = job.status
    job.status = "queued"
    job.attempts = 0
    job.error_message = None
    job.result_json = None
    job.started_at = None
    job.finished_at = None
    job.duration_ms = None
    db.flush()
    create_job_lifecycle_event(
        db,
        job=job,
        event_type="replayed",
        previous_status=previous_status,
        current_status=job.status,
        payload={"attempts_reset_to": 0},
    )

    if settings.jobs_executor_mode == "redis":
        try:
            create_outbox_entry(db, job_id=job.id, queue_name=settings.jobs_queue_name)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to replay job") from exc
    else:
        await execute_job(db, job)

    db.commit()
    db.refresh(job)
    return _to_response(job)


@router.post("/enqueue", response_model=JobRunResponse, status_code=status.HTTP_201_CREATED)
async def enqueue_job_run(
    request: EnqueueJobRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobRunResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    try:
        if settings.jobs_executor_mode == "redis":
            job = enqueue_task(
                db,
                request.task_name,
                request.payload or {},
                redis_url=settings.redis_url,
                queue_name=settings.jobs_queue_name,
                tenant_id=request.tenant_id,
                actor_user_id=current_user.id,
                max_attempts=request.max_attempts,
            )
        else:
            job = await run_task(
                db,
                request.task_name,
                request.payload or {},
                tenant_id=request.tenant_id,
                actor_user_id=current_user.id,
                max_attempts=request.max_attempts,
            )
    except UnknownTaskError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except JobQueueUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    db.commit()
    db.refresh(job)
    return _to_response(job)
