from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.release_governance import (
    ReleaseChangeLink,
    ReleaseDependency,
    ReleaseDeployment,
    ReleaseEnvironment,
    ReleaseGate,
    ReleasePackage,
    ReleaseRecord,
    ReleaseTimeline,
)


ELIGIBLE_CHANGE_STATUSES = {
    "APPROVED",
    "SCHEDULED",
    "IMPLEMENTING",
    "REVIEW",
    "COMPLETED",
}
AUTOMATED_GATE_TYPES = {
    "CHANGES",
    "PACKAGES",
    "DEPENDENCIES",
    "WINDOW",
    "ROLLBACK",
}
ACTIVE_DEPLOYMENT_STATUSES = {"IN_PROGRESS", "VALIDATING"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def add_timeline(
    db: Session,
    release: ReleaseRecord,
    *,
    event_type: str,
    message: str,
    actor_id: str | None,
    actor_name: str,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ReleaseTimeline:
    event = ReleaseTimeline(
        id=str(uuid.uuid4()),
        tenant_id=release.tenant_id,
        release_id=release.id,
        event_type=event_type,
        message=message,
        from_status=from_status,
        to_status=to_status,
        metadata_json=metadata or {},
        actor_id=actor_id,
        actor_name=actor_name,
    )
    db.add(event)
    return event


def default_gates(release: ReleaseRecord) -> list[ReleaseGate]:
    definitions = (
        ("CHANGE_SCOPE", "Linked changes approved", "CHANGES"),
        ("PACKAGE_INTEGRITY", "Packages verified", "PACKAGES"),
        ("DEPENDENCY_READY", "Release dependencies ready", "DEPENDENCIES"),
        ("WINDOW_APPROVED", "Deployment window approved", "WINDOW"),
        ("ROLLBACK_READY", "Rollback plan ready", "ROLLBACK"),
        ("TEST_EVIDENCE", "Test evidence accepted", "TEST"),
        ("SECURITY_REVIEW", "Security review accepted", "SECURITY"),
        ("BUSINESS_SIGNOFF", "Business owner sign-off", "BUSINESS"),
    )
    return [
        ReleaseGate(
            id=str(uuid.uuid4()),
            tenant_id=release.tenant_id,
            release_id=release.id,
            code=code,
            name=name,
            gate_type=gate_type,
            is_mandatory=True,
            status="PENDING",
            version=1,
        )
        for code, name, gate_type in definitions
    ]


def dependency_would_cycle(
    db: Session,
    *,
    release_id: str,
    dependency_release_id: str,
) -> bool:
    if release_id == dependency_release_id:
        return True
    adjacency: dict[str, set[str]] = {}
    for source, target in db.execute(
        select(
            ReleaseDependency.release_id,
            ReleaseDependency.dependency_release_id,
        )
    ).all():
        adjacency.setdefault(source, set()).add(target)
    adjacency.setdefault(release_id, set()).add(dependency_release_id)
    stack = [dependency_release_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == release_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, set()))
    return False


def _readiness_facts(db: Session, release: ReleaseRecord) -> dict[str, Any]:
    change_rows = db.execute(
        select(ReleaseChangeLink, ChangeRequest)
        .join(ChangeRequest, ChangeRequest.id == ReleaseChangeLink.change_id)
        .where(ReleaseChangeLink.release_id == release.id)
        .order_by(ReleaseChangeLink.sequence)
    ).all()
    packages = list(
        db.scalars(
            select(ReleasePackage).where(ReleasePackage.release_id == release.id)
        ).all()
    )
    dependencies = db.execute(
        select(ReleaseDependency, ReleaseRecord)
        .join(
            ReleaseRecord,
            ReleaseRecord.id == ReleaseDependency.dependency_release_id,
        )
        .where(ReleaseDependency.release_id == release.id)
    ).all()
    environments = list(
        db.scalars(
            select(ReleaseEnvironment).where(
                ReleaseEnvironment.tenant_id == release.tenant_id,
                ReleaseEnvironment.is_active.is_(True),
            )
        ).all()
    )
    return {
        "change_rows": change_rows,
        "packages": packages,
        "dependencies": dependencies,
        "environments": environments,
    }


def release_readiness(db: Session, release: ReleaseRecord) -> dict[str, Any]:
    facts = _readiness_facts(db, release)
    change_rows = facts["change_rows"]
    packages = facts["packages"]
    dependencies = facts["dependencies"]
    environments = facts["environments"]
    changes_ready = bool(change_rows) and all(
        (not link.is_mandatory) or change.status in ELIGIBLE_CHANGE_STATUSES
        for link, change in change_rows
    )
    packages_ready = bool(packages) and all(
        item.verification_status == "VERIFIED" for item in packages
    )
    dependencies_ready = all(
        dependency.status == "RELEASED"
        for _, dependency in dependencies
    )
    window_ready = bool(
        release.window_start_at
        and release.window_end_at
        and aware(release.window_end_at) > aware(release.window_start_at)
    )
    rollback_ready = len(release.rollback_plan.strip()) >= 10
    facts_by_gate = {
        "CHANGES": (
            changes_ready,
            f"{sum(1 for _, item in change_rows if item.status in ELIGIBLE_CHANGE_STATUSES)}/{len(change_rows)} linked changes eligible",
        ),
        "PACKAGES": (
            packages_ready,
            f"{sum(1 for item in packages if item.verification_status == 'VERIFIED')}/{len(packages)} packages verified",
        ),
        "DEPENDENCIES": (
            dependencies_ready,
            f"{sum(1 for _, item in dependencies if item.status == 'RELEASED')}/{len(dependencies)} dependencies released",
        ),
        "WINDOW": (
            window_ready,
            "Deployment window is valid" if window_ready else "Deployment window is missing",
        ),
        "ROLLBACK": (
            rollback_ready,
            "Rollback plan is documented",
        ),
    }
    stored_gates = list(
        db.scalars(
            select(ReleaseGate)
            .where(ReleaseGate.release_id == release.id)
            .order_by(ReleaseGate.created_at, ReleaseGate.code)
        ).all()
    )
    gates: list[dict[str, Any]] = []
    for gate in stored_gates:
        if gate.gate_type in AUTOMATED_GATE_TYPES:
            passed, evidence = facts_by_gate[gate.gate_type]
            effective_status = "PASSED" if passed else "FAILED"
            effective_evidence = evidence
        else:
            effective_status = gate.status
            effective_evidence = gate.evidence
        gates.append(
            {
                "id": gate.id,
                "code": gate.code,
                "name": gate.name,
                "gate_type": gate.gate_type,
                "is_mandatory": gate.is_mandatory,
                "stored_status": gate.status,
                "status": effective_status,
                "evidence": effective_evidence,
                "decision_comment": gate.decision_comment,
                "decided_by_name": gate.decided_by_name,
                "decided_at": gate.decided_at,
                "version": gate.version,
            }
        )
    blocking = [
        item
        for item in gates
        if item["is_mandatory"] and item["status"] not in {"PASSED", "WAIVED"}
    ]
    checks = [
        {
            "code": "ENVIRONMENTS",
            "label": "At least one active deployment environment",
            "passed": bool(environments),
        },
        {
            "code": "VALIDATION_PLAN",
            "label": "Validation plan documented",
            "passed": len(release.validation_plan.strip()) >= 10,
        },
        {
            "code": "COMMUNICATION_PLAN",
            "label": "Communication plan documented",
            "passed": len(release.communication_plan.strip()) >= 10,
        },
    ]
    return {
        "ready": not blocking and all(item["passed"] for item in checks),
        "score_percent": round(
            100
            * (
                sum(item["status"] in {"PASSED", "WAIVED"} for item in gates)
                + sum(item["passed"] for item in checks)
            )
            / max(1, len(gates) + len(checks))
        ),
        "checks": checks,
        "gates": gates,
        "blocking_gate_codes": [item["code"] for item in blocking],
        "change_count": len(change_rows),
        "package_count": len(packages),
        "dependency_count": len(dependencies),
        "environment_count": len(environments),
    }


def previous_environment_ready(
    db: Session,
    release: ReleaseRecord,
    environment: ReleaseEnvironment,
) -> tuple[bool, str | None]:
    previous_row = db.execute(
        select(ReleaseDeployment, ReleaseEnvironment)
        .join(
            ReleaseEnvironment,
            ReleaseEnvironment.id == ReleaseDeployment.environment_id,
        )
        .where(
            ReleaseDeployment.release_id == release.id,
            ReleaseEnvironment.promotion_order < environment.promotion_order,
            ReleaseDeployment.status != "CANCELLED",
        )
        .order_by(ReleaseEnvironment.promotion_order.desc())
        .limit(1)
    ).first()
    if previous_row is None:
        if environment.is_production:
            return False, "a lower non-production target"
        return True, None
    deployment, previous = previous_row
    if deployment.status == "SUCCEEDED":
        return True, None
    return False, previous.name


def release_metrics(
    db: Session,
    tenant_id: str | None,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    release_query = select(ReleaseRecord).where(
        ReleaseRecord.created_at >= starts_at,
        ReleaseRecord.created_at < ends_at,
    )
    deployment_query = select(ReleaseDeployment).where(
        ReleaseDeployment.created_at >= starts_at,
        ReleaseDeployment.created_at < ends_at,
    )
    if tenant_id:
        release_query = release_query.where(ReleaseRecord.tenant_id == tenant_id)
        deployment_query = deployment_query.where(
            ReleaseDeployment.tenant_id == tenant_id
        )
    releases = list(db.scalars(release_query).all())
    deployments = list(db.scalars(deployment_query).all())
    completed = [item for item in releases if item.status == "RELEASED"]
    failed = [
        item for item in releases if item.status in {"FAILED", "ROLLED_BACK"}
    ]
    successful_deployments = [
        item for item in deployments if item.status == "SUCCEEDED"
    ]
    failed_deployments = [
        item for item in deployments if item.status in {"FAILED", "ROLLED_BACK"}
    ]
    terminal_deployments = successful_deployments + failed_deployments
    lead_hours = [
        (aware(item.actual_released_at) - aware(item.created_at)).total_seconds()
        / 3600
        for item in completed
        if item.actual_released_at
    ]
    durations = [
        (aware(item.completed_at) - aware(item.started_at)).total_seconds() / 60
        for item in deployments
        if item.started_at and item.completed_at
    ]
    production_environment_ids = set(
        db.scalars(
            select(ReleaseEnvironment.id).where(
                ReleaseEnvironment.is_production.is_(True),
                *(
                    [ReleaseEnvironment.tenant_id == tenant_id]
                    if tenant_id
                    else []
                ),
            )
        ).all()
    )
    production_deployments = [
        item
        for item in successful_deployments
        if item.environment_id in production_environment_ids
    ]
    return {
        "period_start": starts_at,
        "period_end": ends_at,
        "total_releases": len(releases),
        "released": len(completed),
        "failed_or_rolled_back": len(failed),
        "release_success_rate_percent": round(
            len(completed) * 100 / max(1, len(completed) + len(failed)),
            1,
        ),
        "total_deployments": len(deployments),
        "production_deployments": len(production_deployments),
        "deployment_frequency_per_week": round(
            len(production_deployments)
            / max(1.0, (ends_at - starts_at).total_seconds() / 604_800),
            2,
        ),
        "deployment_failure_rate_percent": round(
            len(failed_deployments) * 100 / max(1, len(terminal_deployments)),
            1,
        ),
        "rollback_rate_percent": round(
            sum(item.status == "ROLLED_BACK" for item in deployments)
            * 100
            / max(1, len(terminal_deployments)),
            1,
        ),
        "average_release_lead_time_hours": round(
            sum(lead_hours) / max(1, len(lead_hours)),
            1,
        ),
        "average_deployment_minutes": round(
            sum(durations) / max(1, len(durations)),
            1,
        ),
        "active_deployments": int(
            db.scalar(
                select(func.count(ReleaseDeployment.id)).where(
                    ReleaseDeployment.status.in_(ACTIVE_DEPLOYMENT_STATUSES),
                    *(
                        [ReleaseDeployment.tenant_id == tenant_id]
                        if tenant_id
                        else []
                    ),
                )
            )
            or 0
        ),
    }
