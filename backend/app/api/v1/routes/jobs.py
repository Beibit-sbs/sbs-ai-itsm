from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.audit_log import AuditLog
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
    canary_mode: bool | None = None
    canary_limit_per_cycle: int | None = Field(default=None, ge=1, le=200)
    suppression_windows_utc: list[str] | None = None
    error_denylist: list[str] | None = None


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
    for item in consumers:
        if not isinstance(item, dict):
            continue
        consumer_name = str(item.get("consumer_name") or "")
        effective_policy = _effective_autoremediation_policy(settings, consumer_name)
        item["effective_policy_hash"] = _policy_hash(effective_policy)
        item["policy_version"] = int(policy_state.get("version", 1) or 1)
        item["policy_canary_mode"] = bool(effective_policy.get("canary_mode", False))
        policy_change = policy_changes.get(consumer_name, {})
        item["last_policy_change_at"] = policy_change.get("created_at")
        item["last_policy_change_actor_email"] = policy_change.get("actor_email")
    data["policy_version"] = int(policy_state.get("version", 1) or 1)
    data["policy_rollouts_24h"] = int(rollouts_24h)
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
        effective_policy_hash=new_hash,
        last_policy_change_at=saved_state.get("updated_at"),
        last_policy_change_actor_email=current_user.email,
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
