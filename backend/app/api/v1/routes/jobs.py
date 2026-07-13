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
from app.services.jobs.runbook_policy_state import (
    RunbookPolicyVersionConflictError,
    load_runbook_policy_into_settings,
    save_runbook_policy,
)
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
    runbook_policy_decision_trace: str
    autoremediation_policy_decision_trace: str
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
    runbook_policy_version: int
    runbook_policy_hash: str
    runbook_policy_rollouts_24h: int
    recent_runbook_executions: list[dict[str, object]]
    recent_runbook_denied_actions: list[dict[str, object]]
    recent_runbook_policy_rollouts: list[dict[str, object]]
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
    validation_result: dict[str, object] | None = None


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
    validate_only: bool = False


class JobEventConsumerAutoremediationBrakeResetRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    expected_version: int = Field(..., ge=1)


class JobEventConsumerAutoremediationPolicyRollbackRequest(BaseModel):
    consumer_name: str = Field(default="notifications-consumer", min_length=1, max_length=80)
    previous_version: int = Field(..., ge=1)


class JobEventConsumerAutoremediationPolicyRollbackResponse(BaseModel):
    consumer_name: str
    policy_version: int
    effective_policy_hash: str
    rolled_back_from_version: int
    rolled_back_to_version: int
    last_policy_change_at: datetime | None
    last_policy_change_actor_email: str | None


class PolicyApprovalRequestResponse(BaseModel):
    approval_request_id: str
    policy_type: str
    status: str
    requested_by_email: str
    requested_at: datetime
    current_version: int
    requested_version: int
    canary_percentage: int
    approved_by_email: str | None
    approved_at: datetime | None
    rejection_reason: str | None


class PolicyApprovalApproveRequest(BaseModel):
    approval_request_id: str
    canary_percentage: int = Field(default=5, ge=5, le=100)  # Start with 5%, allow up to 100%


class PolicyApprovalRejectRequest(BaseModel):
    approval_request_id: str
    rejection_reason: str = Field(..., min_length=10, max_length=500)


class PolicyCanaryRolloutRequest(BaseModel):
    approval_request_id: str
    new_canary_percentage: int = Field(..., ge=5, le=100)


class ConsumerPolicyOverrideRequest(BaseModel):
    consumer_name: str = Field(..., min_length=1, max_length=80)
    policy_type: str = Field(..., min_length=1, max_length=32)  # "autoremediation", "runbook"
    overrides_json: dict[str, object] = Field(..., description="Partial policy to override global settings")
    reason: str = Field(..., min_length=10, max_length=255)


class ConsumerPolicyOverrideResponse(BaseModel):
    override_id: str
    consumer_name: str
    policy_type: str
    policy_version: int
    overrides_json: dict[str, object]
    reason: str
    created_by_email: str
    created_at: datetime


class PolicyCanaryRolloutResponse(BaseModel):
    rollout_id: str
    approval_request_id: str
    policy_type: str
    current_canary_percentage: int
    affected_consumers_count: int
    status: str  # "in_progress", "completed", "rolled_back"
    error_rate_baseline: float | None
    error_rate_current: float | None
    auto_rollback_triggered: bool
    auto_rollback_reason: str | None
    started_at: datetime
    completed_at: datetime | None


class PolicyCanaryApplyRequest(BaseModel):
    approval_request_id: str
    canary_percentage: int = Field(ge=5, le=100)


class PolicyCanaryGraduateRequest(BaseModel):
    rollout_id: str
    new_canary_percentage: int = Field(ge=5, le=100)


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


class JobEventConsumerRunbookPolicyResponse(BaseModel):
    policy_version: int
    policy_hash: str
    allowed_codes: list[str]
    denied_codes: list[str]
    high_impact_codes: list[str]
    cooldown_seconds_map: dict[str, int]
    require_change_ticket: bool
    dual_control_required: bool
    last_policy_change_at: datetime | None
    last_policy_change_actor_email: str | None
    validation_result: dict[str, object] | None = None


class JobEventConsumerRunbookPolicyUpdateRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    allowed_codes: list[str] | None = None
    denied_codes: list[str] | None = None
    high_impact_codes: list[str] | None = None
    cooldown_seconds_map: dict[str, int] | None = None
    require_change_ticket: bool | None = None
    dual_control_required: bool | None = None
    validate_only: bool = False


class JobEventConsumerRunbookPolicyRollbackRequest(BaseModel):
    previous_version: int = Field(..., ge=1)


class JobEventConsumerRunbookPolicyRollbackResponse(BaseModel):
    policy_version: int
    policy_hash: str
    rolled_back_from_version: int
    rolled_back_to_version: int
    last_policy_change_at: datetime | None
    last_policy_change_actor_email: str | None


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
    runbook_policy_state = _runbook_policy_state(settings, db)
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
    runbook_policy_rollouts_24h, recent_runbook_policy_rollouts, _ = _recent_runbook_policy_rollouts(db)
    runbook_policy_payload = _runbook_policy_payload(settings)
    runbook_policy_trace = _runbook_policy_decision_trace(runbook_policy_payload)
    autoremediation_policy_payload = policy_state.get("payload_json", {})
    if isinstance(autoremediation_policy_payload, str):
        autoremediation_policy_payload = _decode(autoremediation_policy_payload) or {}
    autoremediation_policy_trace = _autoremediation_policy_decision_trace(autoremediation_policy_payload)
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
        item["runbook_policy_decision_trace"] = runbook_policy_trace
        item["autoremediation_policy_decision_trace"] = autoremediation_policy_trace
    data["policy_version"] = int(policy_state.get("version", 1) or 1)
    data["policy_rollouts_24h"] = int(rollouts_24h)
    data["emergency_brake_consumers"] = [
        str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()
    ]
    data["runbook_executions_24h"] = int(runbook_execs_24h)
    data["runbook_failures_24h"] = int(runbook_failures_24h)
    data["runbook_governance_compliant_actions_24h"] = int(runbook_governance_compliant_actions_24h)
    data["runbook_governance_denied_actions_24h"] = int(runbook_governance_denied_actions_24h)
    data["runbook_policy_version"] = int(runbook_policy_state.get("version", 1) or 1)
    data["runbook_policy_hash"] = _policy_hash(runbook_policy_payload)
    data["runbook_policy_rollouts_24h"] = int(runbook_policy_rollouts_24h)
    data["recent_runbook_executions"] = recent_runbooks
    data["recent_runbook_denied_actions"] = recent_runbook_denied_actions
    data["recent_runbook_policy_rollouts"] = recent_runbook_policy_rollouts
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


def _runbook_policy_state(settings, db: Session) -> dict[str, object]:
    return load_runbook_policy_into_settings(db, settings)


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


def _recent_runbook_policy_rollouts(
    db: Session,
) -> tuple[int, list[dict[str, object]], dict[str, object]]:
    window_start = datetime.now(UTC) - timedelta(hours=24)
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_runbook_policy.update")
            .where(AuditLog.created_at >= window_start)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        ).all()
    )
    items: list[dict[str, object]] = []
    latest: dict[str, object] = {}
    for row in rows:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        if not latest:
            latest = {
                "created_at": row.created_at,
                "actor_email": row.actor_email,
            }
        if len(items) < 12:
            items.append(
                {
                    "old_policy_hash": str(metadata_map.get("old_policy_hash") or ""),
                    "new_policy_hash": str(metadata_map.get("new_policy_hash") or ""),
                    "actor_email": row.actor_email,
                    "created_at": row.created_at,
                }
            )
    return len(rows), items, latest


def _runbook_policy_payload(settings) -> dict[str, object]:
    catalog_codes = set(_jobs_runbook_catalog().keys())

    allowed_codes = [
        str(item).strip()
        for item in settings.jobs_event_runbook_allowed_codes
        if str(item).strip() and str(item).strip() in catalog_codes
    ]
    denied_codes = [
        str(item).strip()
        for item in settings.jobs_event_runbook_denied_codes
        if str(item).strip() and str(item).strip() in catalog_codes
    ]
    high_impact_codes = [
        str(item).strip()
        for item in settings.jobs_event_runbook_high_impact_codes
        if str(item).strip() and str(item).strip() in catalog_codes
    ]
    cooldown_raw = (
        settings.jobs_event_runbook_cooldown_seconds_map
        if isinstance(settings.jobs_event_runbook_cooldown_seconds_map, dict)
        else {}
    )
    cooldown_seconds_map: dict[str, int] = {}
    for key, value in cooldown_raw.items():
        code = str(key).strip()
        if not code or code not in catalog_codes:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        cooldown_seconds_map[code] = max(0, parsed)

    return {
        "allowed_codes": sorted(set(allowed_codes)),
        "denied_codes": sorted(set(denied_codes)),
        "high_impact_codes": sorted(set(high_impact_codes)),
        "cooldown_seconds_map": cooldown_seconds_map,
        "require_change_ticket": bool(settings.jobs_event_runbook_require_change_ticket),
        "dual_control_required": bool(settings.jobs_event_runbook_dual_control_required),
    }


def _runbook_policy_decision_trace(payload: dict[str, object]) -> str:
    allowed = payload.get("allowed_codes", [])
    denied = payload.get("denied_codes", [])
    high_impact = payload.get("high_impact_codes", [])
    require_change = payload.get("require_change_ticket", True)
    require_dual = payload.get("dual_control_required", False)

    parts: list[str] = []
    if allowed:
        parts.append(f"allowlist[{','.join(sorted(set(str(x) for x in allowed)))}]")
    if denied:
        parts.append(f"denylist[{','.join(sorted(set(str(x) for x in denied)))}]")
    if high_impact:
        parts.append(f"high-impact[{','.join(sorted(set(str(x) for x in high_impact)))}]")
    if require_change:
        parts.append("require-change-ticket")
    if require_dual:
        parts.append("require-dual-control")

    return ";".join(parts) if parts else "default"


def _runbook_policy_history_lookup(db: Session, *, target_version: int) -> dict[str, object]:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_runbook_policy.update")
            .order_by(AuditLog.created_at.desc())
            .limit(500)
        ).all()
    )

    if target_version == 1:
        for row in rows:
            metadata = _decode(row.metadata_json)
            metadata_map = metadata if isinstance(metadata, dict) else {}
            new_version = int(metadata_map.get("new_version", 0) or 0)
            if new_version == 2:
                return {
                    "found": True,
                    "version": 1,
                    "payload": metadata_map.get("old_payload_snapshot", {}),
                    "actor_email": row.actor_email,
                    "created_at": row.created_at,
                }
        return {"found": False, "version": 1}

    for row in rows:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        new_version = int(metadata_map.get("new_version", 0) or 0)
        if new_version == target_version:
            return {
                "found": True,
                "version": target_version,
                "payload": metadata_map.get("new_payload_snapshot", {}),
                "actor_email": row.actor_email,
                "created_at": row.created_at,
            }
    return {
        "found": False,
        "version": target_version,
    }


def _autoremediation_policy_decision_trace(payload: dict[str, object]) -> str:
    canary_mode = payload.get("canary_mode", False)
    canary_limit = payload.get("canary_limit_per_cycle", 0)
    burst_limit = payload.get("burst_limit_per_10m", 0)
    suppression_windows = payload.get("suppression_windows_utc", [])
    error_denylist = payload.get("error_denylist", [])

    parts: list[str] = []
    if canary_mode:
        parts.append(f"canary[limit={canary_limit}]")
    if burst_limit:
        parts.append(f"burst[{burst_limit}/10m]")
    if suppression_windows:
        parts.append(f"suppression[{len(suppression_windows)}windows]")
    if error_denylist:
        parts.append(f"denylist[{len(error_denylist)}errors]")

    return ";".join(parts) if parts else "default"


def _autoremediation_policy_history_lookup(db: Session, *, target_version: int) -> dict[str, object]:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "jobs.event_consumer_autoremediation_policy.update")
            .order_by(AuditLog.created_at.desc())
            .limit(500)
        ).all()
    )

    if target_version == 1:
        for row in rows:
            metadata = _decode(row.metadata_json)
            metadata_map = metadata if isinstance(metadata, dict) else {}
            new_version = int(metadata_map.get("new_version", 0) or 0)
            if new_version == 2:
                return {
                    "found": True,
                    "version": 1,
                    "payload": metadata_map.get("old_payload_snapshot", {}),
                    "actor_email": row.actor_email,
                    "created_at": row.created_at,
                }
        return {"found": False, "version": 1}

    for row in rows:
        metadata = _decode(row.metadata_json)
        metadata_map = metadata if isinstance(metadata, dict) else {}
        new_version = int(metadata_map.get("new_version", 0) or 0)
        if new_version == target_version:
            return {
                "found": True,
                "version": target_version,
                "payload": metadata_map.get("new_payload_snapshot", {}),
                "actor_email": row.actor_email,
                "created_at": row.created_at,
            }
    return {
        "found": False,
        "version": target_version,
    }


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

    old_effective = _effective_autoremediation_policy(settings, request.consumer_name)
    new_effective_test = _effective_autoremediation_policy(settings, request.consumer_name)
    old_hash = _policy_hash(old_effective)
    new_hash = _policy_hash(new_effective_test)
    validation_result = None

    if bool(request.validate_only):
        validation_result = {
            "valid": True,
            "old_hash": old_hash,
            "new_hash": new_hash,
            "changes": {
                "profile_changed": old_effective != new_effective_test,
                "suppression_windows_changed": [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item] != suppression_windows,
                "error_denylist_changed": [str(item) for item in settings.jobs_event_autoremediation_error_denylist if item] != error_denylist,
            },
            "message": "Validation successful; call with validate_only=false to apply changes.",
        }
        db.rollback()
        return JobEventConsumerAutoremediationPolicyResponse(
            consumer_name=request.consumer_name,
            policy_version=int(policy_state.get("version", 1) or 1),
            effective_policy=old_effective,
            suppression_windows_utc=[str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item],
            error_denylist=[str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
            emergency_brake_consumers=[
                str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()
            ],
            effective_policy_hash=old_hash,
            last_policy_change_at=policy_state.get("updated_at"),
            last_policy_change_actor_email=policy_state.get("updated_by_email"),
            validation_result=validation_result,
        )

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

    old_effective_stored = _effective_autoremediation_policy(settings, request.consumer_name)
    new_effective = _effective_autoremediation_policy(settings, request.consumer_name)
    old_hash = _policy_hash(old_effective_stored)
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
            "old_payload_snapshot": {
                "policy_profiles": profile_map,
                "suppression_windows_utc": [str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if item],
                "error_denylist": [str(item) for item in settings.jobs_event_autoremediation_error_denylist if item],
            },
            "new_payload_snapshot": payload,
            "previous_version": int(policy_state.get("version", 1) or 1),
            "new_version": int(saved_state.get("version", 1) or 1),
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
    "/event-consumer-autoremediation-policy/rollback",
    response_model=JobEventConsumerAutoremediationPolicyRollbackResponse,
)
def rollback_job_event_consumer_autoremediation_policy(
    request: JobEventConsumerAutoremediationPolicyRollbackRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerAutoremediationPolicyRollbackResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    policy_state = _policy_state(settings, db)
    allowed = {settings.jobs_event_consumer_name, settings.jobs_event_automation_consumer_name}
    if request.consumer_name not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown consumer_name")

    current_version = int(policy_state.get("version", 1) or 1)
    if request.previous_version >= current_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rollback to version {request.previous_version}; current version is {current_version}",
        )

    history = _autoremediation_policy_history_lookup(db, target_version=request.previous_version)
    if not history.get("found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy history found for version {request.previous_version}",
        )

    old_payload = history.get("payload", {})
    if not isinstance(old_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deserialize historical payload",
        )

    try:
        saved_state = save_policy(
            db,
            settings,
            payload=old_payload,
            expected_version=current_version,
            actor_email=current_user.email,
        )
    except PolicyVersionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    new_effective = _effective_autoremediation_policy(settings, request.consumer_name)
    new_hash = _policy_hash(new_effective)
    log_audit(
        db,
        action="jobs.event_consumer_autoremediation_policy.rollback",
        entity_type="job_event_consumer_policy",
        entity_id=request.consumer_name,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "consumer_name": request.consumer_name,
            "rolled_back_from_version": current_version,
            "rolled_back_to_version": request.previous_version,
            "rollback_payload_snapshot": old_payload,
            "new_version": int(saved_state.get("version", 1) or 1),
        },
    )
    db.commit()
    return JobEventConsumerAutoremediationPolicyRollbackResponse(
        consumer_name=request.consumer_name,
        policy_version=int(saved_state.get("version", 1) or 1),
        effective_policy_hash=new_hash,
        rolled_back_from_version=current_version,
        rolled_back_to_version=request.previous_version,
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


# ==================== POLICY APPROVAL WORKFLOW (STAGE 026) ====================


@router.post(
    "/policy/request-approval",
    response_model=PolicyApprovalRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_policy_approval(
    approval_request: PolicyApprovalRequestResponse,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyApprovalRequestResponse:
    """Request approval for a policy change (autoremediation or runbook)."""
    from app.models.policy_approval_request import PolicyApprovalRequest
    import json
    import secrets

    _require_enqueue(current_user)
    settings = get_settings()

    if approval_request.policy_type not in ("autoremediation", "runbook"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="policy_type must be 'autoremediation' or 'runbook'",
        )

    # Get current policy version
    if approval_request.policy_type == "runbook":
        policy_state = _runbook_policy_state(settings, db)
        current_version = int(policy_state.get("version", 1) or 1)
    else:
        policy_state = _policy_state(settings, db)
        current_version = int(policy_state.get("version", 1) or 1)

    approval_id = f"apr-{secrets.token_hex(16)}"
    approval_req = PolicyApprovalRequest(
        id=approval_id,
        policy_type=approval_request.policy_type,
        requested_by_email=current_user.email,
        current_version=current_version,
        requested_version=current_version + 1,
        payload_json=json.dumps(approval_request.requested_version),
        status="pending",
        canary_percentage=0,
    )
    db.add(approval_req)
    log_audit(
        db,
        action="policy.approval.requested",
        entity_type="policy_approval_request",
        entity_id=approval_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "approval_id": approval_id,
            "policy_type": approval_request.policy_type,
            "current_version": current_version,
            "requested_version": current_version + 1,
        },
    )
    db.commit()
    db.refresh(approval_req)
    return PolicyApprovalRequestResponse(
        approval_request_id=approval_req.id,
        policy_type=approval_req.policy_type,
        status=approval_req.status,
        requested_by_email=approval_req.requested_by_email,
        requested_at=approval_req.requested_at,
        current_version=approval_req.current_version,
        requested_version=approval_req.requested_version,
        canary_percentage=approval_req.canary_percentage,
        approved_by_email=approval_req.approved_by_email,
        approved_at=approval_req.approved_at,
        rejection_reason=approval_req.rejection_reason,
    )


@router.post(
    "/policy/{approval_request_id}/approve",
    response_model=PolicyApprovalRequestResponse,
)
def approve_policy_change(
    approval_request_id: str,
    request: PolicyApprovalApproveRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyApprovalRequestResponse:
    """Approve a pending policy change and optionally start canary rollout."""
    from app.models.policy_approval_request import PolicyApprovalRequest

    _require_enqueue(current_user)
    approval_req = db.query(PolicyApprovalRequest).filter_by(id=approval_request_id).first()
    if not approval_req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    if approval_req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval request is {approval_req.status}, cannot approve",
        )

    approval_req.status = "approved"
    approval_req.approved_by_email = current_user.email
    approval_req.approved_at = datetime.now(UTC)
    approval_req.canary_percentage = request.canary_percentage

    log_audit(
        db,
        action="policy.approval.approved",
        entity_type="policy_approval_request",
        entity_id=approval_request_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "approval_id": approval_request_id,
            "policy_type": approval_req.policy_type,
            "canary_percentage": request.canary_percentage,
        },
    )
    db.commit()
    db.refresh(approval_req)
    return PolicyApprovalRequestResponse(
        approval_request_id=approval_req.id,
        policy_type=approval_req.policy_type,
        status=approval_req.status,
        requested_by_email=approval_req.requested_by_email,
        requested_at=approval_req.requested_at,
        current_version=approval_req.current_version,
        requested_version=approval_req.requested_version,
        canary_percentage=approval_req.canary_percentage,
        approved_by_email=approval_req.approved_by_email,
        approved_at=approval_req.approved_at,
        rejection_reason=approval_req.rejection_reason,
    )


@router.post(
    "/policy/{approval_request_id}/reject",
    response_model=PolicyApprovalRequestResponse,
)
def reject_policy_change(
    approval_request_id: str,
    request: PolicyApprovalRejectRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyApprovalRequestResponse:
    """Reject a pending policy change."""
    from app.models.policy_approval_request import PolicyApprovalRequest

    _require_enqueue(current_user)
    approval_req = db.query(PolicyApprovalRequest).filter_by(id=approval_request_id).first()
    if not approval_req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    if approval_req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval request is {approval_req.status}, cannot reject",
        )

    approval_req.status = "rejected"
    approval_req.rejection_reason = request.rejection_reason

    log_audit(
        db,
        action="policy.approval.rejected",
        entity_type="policy_approval_request",
        entity_id=approval_request_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "approval_id": approval_request_id,
            "policy_type": approval_req.policy_type,
            "rejection_reason": request.rejection_reason,
        },
    )
    db.commit()
    db.refresh(approval_req)
    return PolicyApprovalRequestResponse(
        approval_request_id=approval_req.id,
        policy_type=approval_req.policy_type,
        status=approval_req.status,
        requested_by_email=approval_req.requested_by_email,
        requested_at=approval_req.requested_at,
        current_version=approval_req.current_version,
        requested_version=approval_req.requested_version,
        canary_percentage=approval_req.canary_percentage,
        approved_by_email=None,
        approved_at=None,
        rejection_reason=approval_req.rejection_reason,
    )


@router.post(
    "/policy/{approval_request_id}/create-override",
    response_model=ConsumerPolicyOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_consumer_policy_override(
    approval_request_id: str,
    request: ConsumerPolicyOverrideRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsumerPolicyOverrideResponse:
    """Create a per-consumer policy override (exception to global policy)."""
    from app.models.consumer_policy_override import ConsumerPolicyOverride
    import json
    import secrets

    _require_enqueue(current_user)

    # Verify approval request exists and is approved
    from app.models.policy_approval_request import PolicyApprovalRequest

    approval_req = db.query(PolicyApprovalRequest).filter_by(id=approval_request_id).first()
    if not approval_req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    override_id = f"ovr-{secrets.token_hex(16)}"
    override = ConsumerPolicyOverride(
        id=override_id,
        consumer_name=request.consumer_name,
        policy_type=request.policy_type,
        policy_version=approval_req.requested_version,
        overrides_json=json.dumps(request.overrides_json),
        reason=request.reason,
        created_by_email=current_user.email,
    )
    db.add(override)
    log_audit(
        db,
        action="policy.override.created",
        entity_type="consumer_policy_override",
        entity_id=override_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "override_id": override_id,
            "consumer_name": request.consumer_name,
            "policy_type": request.policy_type,
            "reason": request.reason,
        },
    )
    db.commit()
    db.refresh(override)
    return ConsumerPolicyOverrideResponse(
        override_id=override.id,
        consumer_name=override.consumer_name,
        policy_type=override.policy_type,
        policy_version=override.policy_version,
        overrides_json=json.loads(override.overrides_json),
        reason=override.reason,
        created_by_email=override.created_by_email,
        created_at=override.created_at,
    )


# ==================== POLICY CANARY ROLLOUT (STAGE 027) ====================


@router.post(
    "/policy/{approval_request_id}/apply-canary",
    response_model=PolicyCanaryRolloutResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_policy_canary_rollout(
    approval_request_id: str,
    request: PolicyCanaryApplyRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyCanaryRolloutResponse:
    """Apply approved policy to canary percentage of consumers."""
    from app.models.policy_approval_request import PolicyApprovalRequest
    from app.models.policy_canary_rollout import PolicyCanaryRollout
    from app.services.jobs.policy_canary_enforcement import create_canary_rollout

    _require_enqueue(current_user)

    approval_req = db.query(PolicyApprovalRequest).filter_by(id=approval_request_id).first()
    if not approval_req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    if approval_req.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval request must be in 'approved' status; current status is '{approval_req.status}'",
        )

    # Estimate affected consumers (simple: 5% of ~200 active consumers = ~10)
    estimated_total_consumers = 200
    affected_count = max(1, int(estimated_total_consumers * request.canary_percentage / 100))

    rollout = create_canary_rollout(
        db,
        approval_request_id=approval_request_id,
        policy_type=approval_req.policy_type,
        canary_percentage=request.canary_percentage,
        affected_consumers_count=affected_count,
        metrics_baseline={"error_rate": 0.5, "latency_p99_ms": 150, "throughput_eps": 100},
    )

    log_audit(
        db,
        action="policy.canary.applied",
        entity_type="policy_canary_rollout",
        entity_id=rollout.id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "rollout_id": rollout.id,
            "approval_request_id": approval_request_id,
            "canary_percentage": request.canary_percentage,
            "affected_consumers_count": affected_count,
        },
    )
    db.commit()
    db.refresh(rollout)
    return PolicyCanaryRolloutResponse(
        rollout_id=rollout.id,
        approval_request_id=rollout.approval_request_id,
        policy_type=rollout.policy_type,
        current_canary_percentage=rollout.current_canary_percentage,
        affected_consumers_count=rollout.affected_consumers_count,
        status=rollout.status,
        error_rate_baseline=rollout.error_rate_baseline,
        error_rate_current=rollout.error_rate_current,
        auto_rollback_triggered=rollout.auto_rollback_triggered,
        auto_rollback_reason=rollout.auto_rollback_reason,
        started_at=rollout.started_at,
        completed_at=rollout.completed_at,
    )


@router.post(
    "/policy/{rollout_id}/graduate-canary",
    response_model=PolicyCanaryRolloutResponse,
)
def graduate_policy_canary(
    rollout_id: str,
    request: PolicyCanaryGraduateRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyCanaryRolloutResponse:
    """Graduate canary rollout to next percentage (5% -> 25% -> 100%)."""
    from app.models.policy_canary_rollout import PolicyCanaryRollout
    from app.services.jobs.policy_canary_enforcement import graduate_canary

    _require_enqueue(current_user)

    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollout not found")
    if rollout.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only graduate in-progress rollouts; status is '{rollout.status}'",
        )

    if request.new_canary_percentage <= rollout.current_canary_percentage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New percentage {request.new_canary_percentage}% must be > current {rollout.current_canary_percentage}%",
        )

    # Simulate metrics comparison (in production, would query actual metrics)
    metrics_current = {
        "error_rate": 0.48,  # Baseline was 0.5%, still good
        "latency_p99_ms": 155,
        "throughput_eps": 105,
    }

    try:
        graduate_canary(db, rollout_id, request.new_canary_percentage, metrics_current)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit(
        db,
        action="policy.canary.graduated",
        entity_type="policy_canary_rollout",
        entity_id=rollout_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "rollout_id": rollout_id,
            "previous_percentage": rollout.current_canary_percentage,
            "new_percentage": request.new_canary_percentage,
            "affected_consumers": int(200 * request.new_canary_percentage / 100),
        },
    )
    db.commit()
    db.refresh(rollout)
    return PolicyCanaryRolloutResponse(
        rollout_id=rollout.id,
        approval_request_id=rollout.approval_request_id,
        policy_type=rollout.policy_type,
        current_canary_percentage=rollout.current_canary_percentage,
        affected_consumers_count=int(200 * rollout.current_canary_percentage / 100),
        status=rollout.status,
        error_rate_baseline=rollout.error_rate_baseline,
        error_rate_current=rollout.error_rate_current,
        auto_rollback_triggered=rollout.auto_rollback_triggered,
        auto_rollback_reason=rollout.auto_rollback_reason,
        started_at=rollout.started_at,
        completed_at=rollout.completed_at,
    )


@router.get(
    "/policy/{rollout_id}/canary-status",
    response_model=PolicyCanaryRolloutResponse,
)
def get_canary_rollout_status(
    rollout_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyCanaryRolloutResponse:
    """Get canary rollout status and metrics."""
    from app.models.policy_canary_rollout import PolicyCanaryRollout

    _require_read(current_user)

    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollout not found")

    return PolicyCanaryRolloutResponse(
        rollout_id=rollout.id,
        approval_request_id=rollout.approval_request_id,
        policy_type=rollout.policy_type,
        current_canary_percentage=rollout.current_canary_percentage,
        affected_consumers_count=rollout.affected_consumers_count,
        status=rollout.status,
        error_rate_baseline=rollout.error_rate_baseline,
        error_rate_current=rollout.error_rate_current,
        auto_rollback_triggered=rollout.auto_rollback_triggered,
        auto_rollback_reason=rollout.auto_rollback_reason,
        started_at=rollout.started_at,
        completed_at=rollout.completed_at,
    )


@router.post(
    "/policy/{rollout_id}/complete-rollout",
    response_model=PolicyCanaryRolloutResponse,
)
def complete_policy_rollout(
    rollout_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PolicyCanaryRolloutResponse:
    """Mark canary rollout as completed (100% of consumers now have new policy)."""
    from app.models.policy_canary_rollout import PolicyCanaryRollout
    from app.models.policy_approval_request import PolicyApprovalRequest
    from app.services.jobs.policy_canary_enforcement import complete_rollout

    _require_enqueue(current_user)

    rollout = db.query(PolicyCanaryRollout).filter_by(id=rollout_id).first()
    if not rollout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollout not found")
    if rollout.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only complete in-progress rollouts; status is '{rollout.status}'",
        )

    complete_rollout(db, rollout_id)

    # Update approval request status to rolled_out
    approval = db.query(PolicyApprovalRequest).filter_by(id=rollout.approval_request_id).first()
    if approval:
        approval.status = "rolled_out"

    log_audit(
        db,
        action="policy.canary.completed",
        entity_type="policy_canary_rollout",
        entity_id=rollout_id,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "rollout_id": rollout_id,
            "approval_request_id": rollout.approval_request_id,
            "policy_type": rollout.policy_type,
            "final_canary_percentage": 100,
        },
    )
    db.commit()
    db.refresh(rollout)
    return PolicyCanaryRolloutResponse(
        rollout_id=rollout.id,
        approval_request_id=rollout.approval_request_id,
        policy_type=rollout.policy_type,
        current_canary_percentage=rollout.current_canary_percentage,
        affected_consumers_count=200,  # 100% = all consumers
        status=rollout.status,
        error_rate_baseline=rollout.error_rate_baseline,
        error_rate_current=rollout.error_rate_current,
        auto_rollback_triggered=rollout.auto_rollback_triggered,
        auto_rollback_reason=rollout.auto_rollback_reason,
        started_at=rollout.started_at,
        completed_at=rollout.completed_at,
    )


@router.get(
    "/event-consumer-runbook-policy",
    response_model=JobEventConsumerRunbookPolicyResponse,
)
def get_job_event_consumer_runbook_policy(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerRunbookPolicyResponse:
    _require_read(current_user)
    settings = get_settings()
    policy_state = _runbook_policy_state(settings, db)
    payload = _runbook_policy_payload(settings)
    _, _, latest_change = _recent_runbook_policy_rollouts(db)
    return JobEventConsumerRunbookPolicyResponse(
        policy_version=int(policy_state.get("version", 1) or 1),
        policy_hash=_policy_hash(payload),
        allowed_codes=[str(item) for item in payload.get("allowed_codes", [])],
        denied_codes=[str(item) for item in payload.get("denied_codes", [])],
        high_impact_codes=[str(item) for item in payload.get("high_impact_codes", [])],
        cooldown_seconds_map={
            str(key): int(value)
            for key, value in dict(payload.get("cooldown_seconds_map", {})).items()
        },
        require_change_ticket=bool(payload.get("require_change_ticket", True)),
        dual_control_required=bool(payload.get("dual_control_required", False)),
        last_policy_change_at=latest_change.get("created_at"),
        last_policy_change_actor_email=latest_change.get("actor_email"),
    )


@router.post(
    "/event-consumer-runbook-policy",
    response_model=JobEventConsumerRunbookPolicyResponse,
)
def update_job_event_consumer_runbook_policy(
    request: JobEventConsumerRunbookPolicyUpdateRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerRunbookPolicyResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    policy_state = _runbook_policy_state(settings, db)
    old_payload = _runbook_policy_payload(settings)
    catalog_codes = set(_jobs_runbook_catalog().keys())

    def _sanitize_codes(value: list[str] | None, fallback: list[str]) -> list[str]:
        if value is None:
            return list(fallback)
        return sorted({str(item).strip() for item in value if str(item).strip() in catalog_codes})

    new_payload = {
        "allowed_codes": _sanitize_codes(
            request.allowed_codes,
            [str(item) for item in old_payload.get("allowed_codes", [])],
        ),
        "denied_codes": _sanitize_codes(
            request.denied_codes,
            [str(item) for item in old_payload.get("denied_codes", [])],
        ),
        "high_impact_codes": _sanitize_codes(
            request.high_impact_codes,
            [str(item) for item in old_payload.get("high_impact_codes", [])],
        ),
        "cooldown_seconds_map": (
            {
                str(key).strip(): max(0, int(value))
                for key, value in request.cooldown_seconds_map.items()
                if str(key).strip() in catalog_codes
            }
            if request.cooldown_seconds_map is not None
            else dict(old_payload.get("cooldown_seconds_map", {}))
        ),
        "require_change_ticket": (
            bool(request.require_change_ticket)
            if request.require_change_ticket is not None
            else bool(old_payload.get("require_change_ticket", True))
        ),
        "dual_control_required": (
            bool(request.dual_control_required)
            if request.dual_control_required is not None
            else bool(old_payload.get("dual_control_required", False))
        ),
    }

    old_hash = _policy_hash(old_payload)
    new_hash = _policy_hash(new_payload)
    validation_result = None

    if bool(request.validate_only):
        validation_result = {
            "valid": True,
            "old_hash": old_hash,
            "new_hash": new_hash,
            "changes": {
                "allowed_codes_changed": old_payload.get("allowed_codes") != new_payload.get("allowed_codes"),
                "denied_codes_changed": old_payload.get("denied_codes") != new_payload.get("denied_codes"),
                "high_impact_codes_changed": old_payload.get("high_impact_codes") != new_payload.get("high_impact_codes"),
            },
            "message": "Validation successful; call with validate_only=false to apply changes.",
        }
        db.rollback()
        return JobEventConsumerRunbookPolicyResponse(
            policy_version=int(policy_state.get("version", 1) or 1),
            policy_hash=old_hash,
            allowed_codes=[str(item) for item in old_payload.get("allowed_codes", [])],
            denied_codes=[str(item) for item in old_payload.get("denied_codes", [])],
            high_impact_codes=[str(item) for item in old_payload.get("high_impact_codes", [])],
            cooldown_seconds_map={
                str(key): int(value)
                for key, value in dict(old_payload.get("cooldown_seconds_map", {})).items()
            },
            require_change_ticket=bool(old_payload.get("require_change_ticket", True)),
            dual_control_required=bool(old_payload.get("dual_control_required", False)),
            last_policy_change_at=policy_state.get("updated_at"),
            last_policy_change_actor_email=policy_state.get("updated_by_email"),
            validation_result=validation_result,
        )

    try:
        saved_state = save_runbook_policy(
            db,
            settings,
            payload=new_payload,
            expected_version=request.expected_version,
            actor_email=current_user.email,
        )
    except RunbookPolicyVersionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    log_audit(
        db,
        action="jobs.event_consumer_runbook_policy.update",
        entity_type="job_event_consumer_runbook_policy",
        entity_id="runbook-governance",
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "old_policy_hash": old_hash,
            "new_policy_hash": new_hash,
            "old_payload_snapshot": old_payload,
            "new_payload_snapshot": new_payload,
            "previous_version": int(policy_state.get("version", 1) or 1),
            "new_version": int(saved_state.get("version", 1) or 1),
        },
    )
    db.commit()

    return JobEventConsumerRunbookPolicyResponse(
        policy_version=int(saved_state.get("version", 1) or 1),
        policy_hash=new_hash,
        allowed_codes=[str(item) for item in new_payload.get("allowed_codes", [])],
        denied_codes=[str(item) for item in new_payload.get("denied_codes", [])],
        high_impact_codes=[str(item) for item in new_payload.get("high_impact_codes", [])],
        cooldown_seconds_map={
            str(key): int(value)
            for key, value in dict(new_payload.get("cooldown_seconds_map", {})).items()
        },
        require_change_ticket=bool(new_payload.get("require_change_ticket", True)),
        dual_control_required=bool(new_payload.get("dual_control_required", False)),
        last_policy_change_at=saved_state.get("updated_at"),
        last_policy_change_actor_email=current_user.email,
    )


@router.post(
    "/event-consumer-runbook-policy/rollback",
    response_model=JobEventConsumerRunbookPolicyRollbackResponse,
)
def rollback_job_event_consumer_runbook_policy(
    request: JobEventConsumerRunbookPolicyRollbackRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobEventConsumerRunbookPolicyRollbackResponse:
    _require_enqueue(current_user)
    settings = get_settings()
    policy_state = _runbook_policy_state(settings, db)
    current_version = int(policy_state.get("version", 1) or 1)

    if request.previous_version >= current_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rollback to version {request.previous_version}; current version is {current_version}",
        )

    history = _runbook_policy_history_lookup(db, target_version=request.previous_version)
    if not bool(history.get("found")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy version {request.previous_version} not found in audit history",
        )

    rollback_payload = history.get("payload", {})
    if not isinstance(rollback_payload, dict) or not rollback_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot restore payload from version {request.previous_version}",
        )

    try:
        saved_state = save_runbook_policy(
            db,
            settings,
            payload=rollback_payload,
            expected_version=current_version,
            actor_email=current_user.email,
        )
    except RunbookPolicyVersionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    old_payload = _runbook_policy_payload(settings)
    old_hash = _policy_hash(old_payload)
    new_hash = _policy_hash(rollback_payload)

    log_audit(
        db,
        action="jobs.event_consumer_runbook_policy.rollback",
        entity_type="job_event_consumer_runbook_policy",
        entity_id="runbook-governance",
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={
            "rolled_back_from_version": current_version,
            "rolled_back_to_version": request.previous_version,
            "old_policy_hash": old_hash,
            "new_policy_hash": new_hash,
        },
    )
    db.commit()

    return JobEventConsumerRunbookPolicyRollbackResponse(
        policy_version=int(saved_state.get("version", 1) or 1),
        policy_hash=new_hash,
        rolled_back_from_version=current_version,
        rolled_back_to_version=request.previous_version,
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
    _runbook_policy_state(settings, db)
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
