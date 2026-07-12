from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.job_run import JobRun
from app.services.jobs import (
    JobQueueUnavailableError,
    UnknownTaskError,
    enqueue_job_id,
    enqueue_task,
    execute_job,
    get_job as service_get_job,
    job_summary,
    list_jobs,
    registered_task_names,
    run_task,
)
from app.services.rbac import has_permission, is_saas_root

router = APIRouter(prefix="/jobs")


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
    retry_base_seconds: float
    retry_max_seconds: float
    worker_required: bool


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
        retry_base_seconds=settings.jobs_retry_base_seconds,
        retry_max_seconds=settings.jobs_retry_max_seconds,
        worker_required=settings.jobs_executor_mode == "redis",
    )


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

    job.status = "queued"
    job.attempts = 0
    job.error_message = None
    job.result_json = None
    job.started_at = None
    job.finished_at = None
    job.duration_ms = None
    db.flush()

    if settings.jobs_executor_mode == "redis":
        try:
            enqueue_job_id(redis_url=settings.redis_url, queue_name=settings.jobs_queue_name, job_id=job.id)
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
