from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_governance import (
    ChangeImplementationTask,
    ChangePostImplementationReview,
    ChangeWindow,
    StandardChangeModel,
)
from app.models.change_link import ChangeAssetLink
from app.models.change_request import ChangeRequest
from app.models.user import User


ACTIVE_CHANGE_STATUSES = {"SCHEDULED", "IMPLEMENTING"}
TERMINAL_CHANGE_STATUSES = {
    "COMPLETED",
    "FAILED",
    "ROLLED_BACK",
    "CANCELLED",
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalized(values: list[str] | None) -> set[str]:
    return {
        str(item).strip().casefold()
        for item in (values or [])
        if str(item).strip()
    }


def _scope_applies(
    window: ChangeWindow,
    change: ChangeRequest,
    asset_ids: set[str],
) -> bool:
    services = _normalized(window.services_json)
    environments = _normalized(window.environments_json)
    scoped_assets = set(window.asset_ids_json or [])
    service_match = (
        not services
        or (change.service_name or "").strip().casefold() in services
    )
    environment_match = (
        not environments
        or change.environment.strip().casefold() in environments
    )
    asset_match = not scoped_assets or bool(scoped_assets & asset_ids)
    return service_match and environment_match and asset_match


def assess_change_window(
    db: Session,
    change: ChangeRequest,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> dict[str, Any]:
    start = starts_at or change.planned_start_at
    end = ends_at or change.planned_end_at
    if start is None or end is None:
        return {
            "maintenance_coverage": [],
            "blackouts": [],
            "change_conflicts": [],
            "blocking_count": 0,
        }
    start = aware(start)
    end = aware(end)
    asset_ids = set(
        db.scalars(
            select(ChangeAssetLink.asset_id).where(
                ChangeAssetLink.change_id == change.id
            )
        ).all()
    )

    windows = db.scalars(
        select(ChangeWindow)
        .where(
            ChangeWindow.tenant_id == change.tenant_id,
            ChangeWindow.is_active.is_(True),
            ChangeWindow.starts_at < end,
            ChangeWindow.ends_at > start,
        )
        .order_by(ChangeWindow.starts_at)
    ).all()
    maintenance: list[dict[str, Any]] = []
    blackouts: list[dict[str, Any]] = []
    for window in windows:
        if not _scope_applies(window, change, asset_ids):
            continue
        payload = {
            "id": window.id,
            "name": window.name,
            "window_type": window.window_type,
            "starts_at": window.starts_at,
            "ends_at": window.ends_at,
            "services": window.services_json,
            "environments": window.environments_json,
        }
        if window.window_type == "BLACKOUT":
            payload["blocking"] = True
            blackouts.append(payload)
        else:
            payload["fully_covered"] = (
                aware(window.starts_at) <= start
                and aware(window.ends_at) >= end
            )
            maintenance.append(payload)

    overlapping = db.scalars(
        select(ChangeRequest).where(
            ChangeRequest.id != change.id,
            ChangeRequest.tenant_id == change.tenant_id,
            ChangeRequest.status.in_(ACTIVE_CHANGE_STATUSES),
            ChangeRequest.planned_start_at < end,
            ChangeRequest.planned_end_at > start,
        )
    ).all()
    conflicts: list[dict[str, Any]] = []
    for other in overlapping:
        other_assets = set(
            db.scalars(
                select(ChangeAssetLink.asset_id).where(
                    ChangeAssetLink.change_id == other.id
                )
            ).all()
        )
        shared_assets = sorted(asset_ids & other_assets)
        same_service = bool(
            change.service_name
            and other.service_name
            and change.service_name.casefold() == other.service_name.casefold()
        )
        same_environment = (
            change.environment.casefold() == other.environment.casefold()
        )
        if not shared_assets and not (same_service and same_environment):
            continue
        conflicts.append(
            {
                "id": other.id,
                "change_number": other.change_number,
                "title": other.title,
                "starts_at": other.planned_start_at,
                "ends_at": other.planned_end_at,
                "risk_level": other.risk_level,
                "shared_asset_ids": shared_assets,
                "same_service": same_service,
                "same_environment": same_environment,
                "blocking": True,
            }
        )
    return {
        "maintenance_coverage": maintenance,
        "blackouts": blackouts,
        "change_conflicts": conflicts,
        "blocking_count": len(blackouts) + len(conflicts),
    }


def readiness_assessment(
    db: Session,
    change: ChangeRequest,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(code: str, label: str, passed: bool, blocking: bool = True) -> None:
        checks.append(
            {
                "code": code,
                "label": label,
                "passed": passed,
                "blocking": blocking,
            }
        )

    add("business_justification", "Business justification", bool(change.business_justification))
    add("implementation_plan", "Implementation plan", bool(change.implementation_plan))
    add("test_plan", "Test plan", bool(change.test_plan))
    add("rollback_plan", "Rollback plan", bool(change.rollback_plan))
    add("validation_plan", "Validation plan", bool(change.validation_plan))
    add(
        "owner",
        "Accountable change owner",
        bool(change.owner_id or change.owner_name),
    )
    add(
        "window",
        "Implementation window",
        bool(change.planned_start_at and change.planned_end_at),
    )
    add(
        "approval",
        "Required approval",
        not change.cab_required or change.approval_status == "APPROVED",
    )
    tasks = db.scalars(
        select(ChangeImplementationTask).where(
            ChangeImplementationTask.change_id == change.id
        )
    ).all()
    required_implementation = [
        item
        for item in tasks
        if item.task_type == "IMPLEMENTATION" and item.is_required
    ]
    add(
        "implementation_tasks",
        "Required implementation tasks defined",
        bool(required_implementation),
        blocking=False,
    )
    assessment = assess_change_window(db, change)
    add(
        "collision_free",
        "No change collision",
        not assessment["change_conflicts"],
    )
    blackout_overridden = bool(
        change.change_type == "EMERGENCY"
        and change.blackout_override_reason
        and change.blackout_override_by_id
    )
    add(
        "blackout",
        "No active blackout or approved emergency override",
        not assessment["blackouts"] or blackout_overridden,
    )
    blocking_checks = [item for item in checks if item["blocking"]]
    passed = sum(1 for item in checks if item["passed"])
    return {
        "score_percent": round(passed * 100 / max(1, len(checks))),
        "ready": all(item["passed"] for item in blocking_checks),
        "checks": checks,
        "window_assessment": assessment,
    }


def create_tasks_from_standard_model(
    db: Session,
    change: ChangeRequest,
    model: StandardChangeModel,
) -> list[ChangeImplementationTask]:
    created: list[ChangeImplementationTask] = []
    sequences: dict[str, int] = {
        "IMPLEMENTATION": 0,
        "VALIDATION": 0,
        "ROLLBACK": 0,
    }
    for raw in model.task_templates_json:
        task_type = str(raw.get("type") or "IMPLEMENTATION").upper()
        if task_type not in sequences:
            continue
        sequences[task_type] += 1
        task = ChangeImplementationTask(
            id=str(uuid.uuid4()),
            tenant_id=change.tenant_id,
            change_id=change.id,
            task_type=task_type,
            sequence=sequences[task_type],
            title=str(raw.get("title") or f"{task_type.title()} step")[:255],
            description=(
                str(raw["description"]) if raw.get("description") else None
            ),
            status="PENDING",
            is_required=bool(raw.get("required", True)),
            owner_id=change.owner_id,
            owner_name=change.owner_name,
            version=1,
        )
        db.add(task)
        created.append(task)
    return created


def required_tasks_complete(
    db: Session,
    change_id: str,
    task_type: str,
) -> bool:
    tasks = db.scalars(
        select(ChangeImplementationTask).where(
            ChangeImplementationTask.change_id == change_id,
            ChangeImplementationTask.task_type == task_type,
            ChangeImplementationTask.is_required.is_(True),
        )
    ).all()
    return not tasks or all(item.status == "COMPLETED" for item in tasks)


def change_metrics(
    db: Session,
    tenant_id: str | None,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    statement = select(ChangeRequest).where(
        ChangeRequest.created_at >= starts_at,
        ChangeRequest.created_at < ends_at,
    )
    if tenant_id:
        statement = statement.where(ChangeRequest.tenant_id == tenant_id)
    changes = list(db.scalars(statement).all())
    total = len(changes)
    completed = [item for item in changes if item.status == "COMPLETED"]
    failed = [item for item in changes if item.status == "FAILED"]
    rolled_back = [item for item in changes if item.status == "ROLLED_BACK"]
    emergency = [item for item in changes if item.change_type == "EMERGENCY"]
    successful = [
        item
        for item in completed
        if item.outcome in {None, "SUCCESS"}
    ]
    lead_times = [
        (aware(item.actual_start_at) - aware(item.created_at)).total_seconds()
        / 3600
        for item in changes
        if item.actual_start_at
    ]
    durations = [
        (aware(item.actual_end_at) - aware(item.actual_start_at)).total_seconds()
        / 60
        for item in changes
        if item.actual_start_at and item.actual_end_at
    ]
    return {
        "period_start": starts_at,
        "period_end": ends_at,
        "total_changes": total,
        "completed_changes": len(completed),
        "successful_changes": len(successful),
        "failed_changes": len(failed),
        "rolled_back_changes": len(rolled_back),
        "emergency_changes": len(emergency),
        "success_rate_percent": round(
            len(successful) * 100 / max(1, len(completed)),
            1,
        ),
        "change_failure_rate_percent": round(
            (len(failed) + len(rolled_back)) * 100 / max(1, total),
            1,
        ),
        "emergency_rate_percent": round(
            len(emergency) * 100 / max(1, total),
            1,
        ),
        "average_lead_time_hours": round(
            sum(lead_times) / max(1, len(lead_times)),
            1,
        ),
        "average_implementation_minutes": round(
            sum(durations) / max(1, len(durations)),
            1,
        ),
    }


def update_standard_model_outcome(
    db: Session,
    change: ChangeRequest,
    outcome: str,
) -> None:
    if not change.standard_model_id:
        return
    model = db.get(StandardChangeModel, change.standard_model_id)
    if model is None:
        return
    if outcome == "SUCCESS":
        model.success_count += 1
    elif outcome in {"FAILED", "ROLLED_BACK"}:
        model.failure_count += 1


def pir_for_change(
    db: Session,
    change_id: str,
) -> ChangePostImplementationReview | None:
    return db.scalar(
        select(ChangePostImplementationReview).where(
            ChangePostImplementationReview.change_id == change_id
        )
    )


def validate_user(
    db: Session,
    user_id: str | None,
    tenant_id: str,
) -> User | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        raise ValueError("Selected user is unavailable")
    return user


def count_open_tasks(db: Session, change_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(ChangeImplementationTask.id)).where(
                ChangeImplementationTask.change_id == change_id,
                ChangeImplementationTask.status.in_(["PENDING", "IN_PROGRESS"]),
            )
        )
        or 0
    )
