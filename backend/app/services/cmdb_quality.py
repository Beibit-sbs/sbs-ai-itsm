from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import struct
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.ci_relationship import ConfigurationItemRelationship
from app.models.cmdb_quality import (
    CMDBQualityFinding,
    CMDBQualitySnapshot,
)
from app.models.cmdb_reconciliation import (
    CIDuplicateCandidate,
    CMDBSource,
    CMDBSourceIdentity,
)
from app.models.user import User
from app.services.cmdb_schema import canonical_json


MAPPED_CLASS_CODES = {
    "BUSINESS_SERVICE",
    "TECHNICAL_SERVICE",
    "APPLICATION",
    "INFRASTRUCTURE",
}
LOGICAL_CLASS_CODES = {
    "BUSINESS_SERVICE",
    "TECHNICAL_SERVICE",
    "APPLICATION",
}
ACTIVE_FINDING_STATUSES = {"OPEN", "IN_PROGRESS"}
DIMENSION_WEIGHTS = {
    "COMPLETENESS": 0.30,
    "CORRECTNESS": 0.20,
    "FRESHNESS": 0.20,
    "DUPLICATE": 0.15,
    "ORPHAN": 0.15,
}
REMEDIATION_DAYS = {
    "LOW": 30,
    "MEDIUM": 14,
    "HIGH": 7,
    "CRITICAL": 2,
}


@dataclass(frozen=True)
class FindingSpec:
    rule_code: str
    dimension: str
    subject_type: str
    subject_id: str
    asset_id: str | None
    title: str
    details: str
    severity: str
    evidence: dict[str, Any]
    owner_user_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return self.rule_code, self.subject_type, self.subject_id


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _lock_quality_scan(db: Session, tenant_id: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"cmdb-quality:{tenant_id}".encode()).digest()[:8]
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": struct.unpack(">q", digest)[0]},
    )


def _json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _is_blank(value: str | None) -> bool:
    return not value or not value.strip() or value.strip().casefold() in {
        "location unknown",
        "unknown",
        "не указано",
        "—",
    }


def _severity(asset: Asset, *, default: str = "MEDIUM") -> str:
    if asset.criticality == "CRITICAL" and asset.environment == "PRODUCTION":
        return "CRITICAL"
    if asset.criticality in {"HIGH", "CRITICAL"}:
        return "HIGH"
    return default


def _asset_evidence(asset: Asset, **extra: Any) -> dict[str, Any]:
    return {
        "asset_tag": asset.asset_tag,
        "name": asset.name,
        "ci_class_code": asset.ci_class_code,
        "lifecycle_status": asset.lifecycle_status,
        "criticality": asset.criticality,
        "environment": asset.environment,
        "ci_version": asset.ci_version,
        **extra,
    }


def _collect_asset_findings(
    db: Session,
    *,
    tenant_id: str,
    assets: list[Asset],
    now: datetime,
) -> tuple[list[FindingSpec], dict[str, int]]:
    findings: list[FindingSpec] = []
    active_assets = [
        asset for asset in assets if asset.lifecycle_status != "DISPOSED"
    ]
    user_ids = {asset.owner_user_id for asset in assets if asset.owner_user_id}
    users = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    connected_ids = set(
        db.scalars(
            select(ConfigurationItemRelationship.source_ci_id).where(
                ConfigurationItemRelationship.tenant_id == tenant_id,
                ConfigurationItemRelationship.status == "ACTIVE",
            )
        ).all()
    )
    connected_ids.update(
        db.scalars(
            select(ConfigurationItemRelationship.target_ci_id).where(
                ConfigurationItemRelationship.tenant_id == tenant_id,
                ConfigurationItemRelationship.status == "ACTIVE",
            )
        ).all()
    )
    last_seen = dict(
        db.execute(
            select(
                CMDBSourceIdentity.asset_id,
                func.max(CMDBSourceIdentity.last_seen_at),
            )
            .where(CMDBSourceIdentity.tenant_id == tenant_id)
            .group_by(CMDBSourceIdentity.asset_id)
        ).all()
    )

    for asset in assets:
        evidence = _asset_evidence(asset)
        if asset.ci_class_id is None or asset.ci_class_version_id is None:
            findings.append(
                FindingSpec(
                    "MISSING_CI_SCHEMA",
                    "CORRECTNESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI is not bound to a governed class version",
                    "Assign a published CI class and immutable schema snapshot.",
                    "HIGH",
                    evidence,
                    asset.owner_user_id,
                )
            )
        disposed_mismatch = (
            asset.lifecycle_status == "DISPOSED" and asset.status != "disposed"
        ) or (
            asset.lifecycle_status != "DISPOSED" and asset.status == "disposed"
        )
        if disposed_mismatch:
            findings.append(
                FindingSpec(
                    "LIFECYCLE_STATUS_MISMATCH",
                    "CORRECTNESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "Lifecycle and asset status disagree",
                    "Align governed lifecycle_status with the operational asset status.",
                    "HIGH",
                    _asset_evidence(asset, status=asset.status),
                    asset.owner_user_id,
                )
            )
        owner = users.get(asset.owner_user_id or "")
        if asset.owner_user_id and (
            owner is None
            or owner.tenant_id != tenant_id
            or not owner.is_active
        ):
            findings.append(
                FindingSpec(
                    "INVALID_CI_OWNER",
                    "CORRECTNESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI owner is unavailable or outside the tenant",
                    "Assign an active owner from the same tenant.",
                    _severity(asset, default="HIGH"),
                    _asset_evidence(asset, owner_user_id=asset.owner_user_id),
                    None,
                )
            )
        if asset.lifecycle_status == "DISPOSED":
            continue
        if asset.owner_user_id is None:
            findings.append(
                FindingSpec(
                    "MISSING_CI_OWNER",
                    "COMPLETENESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI has no accountable owner",
                    "Assign an accountable data or service owner.",
                    _severity(asset),
                    evidence,
                    None,
                )
            )
        if asset.ci_class_code != "LOCATION" and _is_blank(asset.support_group):
            findings.append(
                FindingSpec(
                    "MISSING_SUPPORT_GROUP",
                    "COMPLETENESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI has no support group",
                    "Assign the operational group responsible for this CI.",
                    _severity(asset),
                    evidence,
                    asset.owner_user_id,
                )
            )
        if (
            asset.ci_class_code not in LOGICAL_CLASS_CODES
            and _is_blank(asset.location)
        ):
            findings.append(
                FindingSpec(
                    "MISSING_LOCATION",
                    "COMPLETENESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "Physical CI location is missing",
                    "Record a verified physical or logical location.",
                    _severity(asset, default="LOW"),
                    evidence,
                    asset.owner_user_id,
                )
            )
        observed_at = last_seen.get(asset.id) or asset.updated_at
        if _aware(observed_at) < now - timedelta(days=90):
            age_days = (now - _aware(observed_at)).days
            findings.append(
                FindingSpec(
                    "STALE_CI_OBSERVATION",
                    "FRESHNESS",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI has not been observed recently",
                    "Verify the CI or refresh it from an authoritative source.",
                    _severity(asset),
                    _asset_evidence(
                        asset,
                        last_observed_at=_aware(observed_at).isoformat(),
                        age_days=age_days,
                    ),
                    asset.owner_user_id,
                )
            )
        if (
            asset.ci_class_code in MAPPED_CLASS_CODES
            and asset.id not in connected_ids
        ):
            findings.append(
                FindingSpec(
                    "ORPHAN_SERVICE_MAPPING_CI",
                    "ORPHAN",
                    "CI",
                    asset.id,
                    asset.id,
                    "CI is isolated from the service dependency graph",
                    "Add a valid service relationship or retire the CI.",
                    _severity(asset),
                    evidence,
                    asset.owner_user_id,
                )
            )

    eligible = {
        "COMPLETENESS": len(active_assets),
        "CORRECTNESS": len(assets),
        "FRESHNESS": len(active_assets),
        "DUPLICATE": max(len(assets), 1),
        "ORPHAN": sum(
            asset.lifecycle_status != "DISPOSED"
            and asset.ci_class_code in MAPPED_CLASS_CODES
            for asset in assets
        ),
    }
    return findings, eligible


def _collect_source_findings(
    db: Session,
    *,
    tenant_id: str,
    now: datetime,
) -> tuple[list[FindingSpec], int]:
    findings: list[FindingSpec] = []
    sources = db.scalars(
        select(CMDBSource).where(
            CMDBSource.tenant_id == tenant_id,
            CMDBSource.status == "ACTIVE",
        )
    ).all()
    for source in sources:
        reference = source.last_success_at or source.created_at
        if _aware(reference) >= now - timedelta(
            hours=source.stale_after_hours
        ):
            continue
        age_hours = int((now - _aware(reference)).total_seconds() // 3600)
        findings.append(
            FindingSpec(
                "STALE_CMDB_SOURCE",
                "FRESHNESS",
                "SOURCE",
                source.id,
                None,
                f"CMDB source {source.name} is stale",
                "Restore ingestion or explicitly deactivate the source.",
                "HIGH",
                {
                    "source_code": source.code,
                    "source_type": source.source_type,
                    "stale_after_hours": source.stale_after_hours,
                    "last_success_at": (
                        source.last_success_at.isoformat()
                        if source.last_success_at
                        else None
                    ),
                    "age_hours": age_hours,
                },
            )
        )
    return findings, len(sources)


def _collect_duplicate_findings(
    db: Session,
    *,
    tenant_id: str,
) -> list[FindingSpec]:
    candidates = db.scalars(
        select(CIDuplicateCandidate).where(
            CIDuplicateCandidate.tenant_id == tenant_id,
            CIDuplicateCandidate.status == "OPEN",
        )
    ).all()
    return [
        FindingSpec(
            "OPEN_DUPLICATE_CANDIDATE",
            "DUPLICATE",
            "DUPLICATE_CANDIDATE",
            candidate.id,
            candidate.primary_ci_id,
            "Potential duplicate CI requires a decision",
            "Review the candidate and merge or dismiss it with evidence.",
            "HIGH" if candidate.confidence >= 0.9 else "MEDIUM",
            {
                "candidate_id": candidate.id,
                "primary_ci_id": candidate.primary_ci_id,
                "duplicate_ci_id": candidate.duplicate_ci_id,
                "confidence": candidate.confidence,
                "reasons": _json_list(candidate.reasons_json),
            },
        )
        for candidate in candidates
    ]


def _dimension_scores(
    specs: list[FindingSpec],
    eligible: dict[str, int],
) -> tuple[dict[str, float], dict[str, int]]:
    affected: dict[str, set[tuple[str, str]]] = {
        dimension: set() for dimension in DIMENSION_WEIGHTS
    }
    for spec in specs:
        if spec.dimension in affected:
            affected[spec.dimension].add(
                (spec.subject_type, spec.subject_id)
            )
    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for dimension in DIMENSION_WEIGHTS:
        denominator = eligible.get(dimension, 0)
        count = len(affected[dimension])
        counts[dimension] = count
        scores[dimension] = (
            100.0
            if denominator <= 0
            else round(
                max(0.0, 100.0 * (1 - min(count, denominator) / denominator)),
                2,
            )
        )
    return scores, counts


def scan_quality(
    db: Session,
    *,
    tenant_id: str,
    actor_user_id: str | None,
) -> CMDBQualitySnapshot:
    _lock_quality_scan(db, tenant_id)
    now = _now()
    assets = db.scalars(
        select(Asset).where(Asset.tenant_id == tenant_id).order_by(Asset.id)
    ).all()
    asset_specs, eligible = _collect_asset_findings(
        db,
        tenant_id=tenant_id,
        assets=assets,
        now=now,
    )
    source_specs, source_count = _collect_source_findings(
        db,
        tenant_id=tenant_id,
        now=now,
    )
    duplicate_specs = _collect_duplicate_findings(db, tenant_id=tenant_id)
    eligible["FRESHNESS"] += source_count
    specs = [*asset_specs, *source_specs, *duplicate_specs]
    scores, affected = _dimension_scores(specs, eligible)
    overall = round(
        sum(scores[item] * weight for item, weight in DIMENSION_WEIGHTS.items()),
        2,
    )
    rule_counts = Counter(spec.rule_code for spec in specs)
    severity_counts = Counter(spec.severity for spec in specs)
    result: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "scores": {
            "overall": overall,
            **{key.casefold(): value for key, value in scores.items()},
        },
        "eligible": {key.casefold(): value for key, value in eligible.items()},
        "affected": {key.casefold(): value for key, value in affected.items()},
        "rule_counts": dict(sorted(rule_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "ci_count": len(assets),
    }
    snapshot = CMDBQualitySnapshot(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        overall_score=overall,
        completeness_score=scores["COMPLETENESS"],
        correctness_score=scores["CORRECTNESS"],
        freshness_score=scores["FRESHNESS"],
        duplicate_score=scores["DUPLICATE"],
        orphan_score=scores["ORPHAN"],
        ci_count=len(assets),
        open_finding_count=len(specs),
        critical_finding_count=severity_counts["CRITICAL"],
        resolved_finding_count=0,
        result_json="{}",
        result_hash="",
        created_by_id=actor_user_id,
        created_at=now,
    )
    db.add(snapshot)
    db.flush()

    existing = {
        (item.rule_code, item.subject_type, item.subject_id): item
        for item in db.scalars(
            select(CMDBQualityFinding).where(
                CMDBQualityFinding.tenant_id == tenant_id,
                CMDBQualityFinding.dimension != "CERTIFICATION",
            )
        ).all()
    }
    active_keys: set[tuple[str, str, str]] = set()
    for spec in specs:
        active_keys.add(spec.key)
        finding = existing.get(spec.key)
        if finding is None:
            finding = CMDBQualityFinding(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                rule_code=spec.rule_code,
                dimension=spec.dimension,
                subject_type=spec.subject_type,
                subject_id=spec.subject_id,
                asset_id=spec.asset_id,
                title=spec.title,
                details=spec.details,
                evidence_json=canonical_json(spec.evidence),
                severity=spec.severity,
                status="OPEN",
                owner_user_id=spec.owner_user_id,
                due_at=now + timedelta(days=REMEDIATION_DAYS[spec.severity]),
                first_detected_at=now,
                last_detected_at=now,
                occurrence_count=1,
                last_snapshot_id=snapshot.id,
                version=1,
                created_at=now,
                updated_at=now,
            )
            db.add(finding)
            continue
        finding.title = spec.title
        finding.details = spec.details
        finding.evidence_json = canonical_json(spec.evidence)
        finding.severity = spec.severity
        finding.asset_id = spec.asset_id
        finding.last_detected_at = now
        finding.last_snapshot_id = snapshot.id
        finding.occurrence_count += 1
        if finding.owner_user_id is None:
            finding.owner_user_id = spec.owner_user_id
        if finding.due_at is None:
            finding.due_at = now + timedelta(
                days=REMEDIATION_DAYS[spec.severity]
            )
        if finding.status == "RESOLVED":
            finding.status = "OPEN"
            finding.resolution_note = None
            finding.resolved_by_id = None
            finding.resolved_at = None
        finding.version += 1
        finding.updated_at = now

    resolved_count = 0
    for key, finding in existing.items():
        if key in active_keys or finding.status not in ACTIVE_FINDING_STATUSES:
            continue
        finding.status = "RESOLVED"
        finding.resolution_note = "Automatically resolved by CMDB quality rescan"
        finding.resolved_at = now
        finding.last_snapshot_id = snapshot.id
        finding.version += 1
        finding.updated_at = now
        resolved_count += 1
    db.flush()

    active_rows = db.scalars(
        select(CMDBQualityFinding).where(
            CMDBQualityFinding.tenant_id == tenant_id,
            CMDBQualityFinding.status.in_(ACTIVE_FINDING_STATUSES),
        )
    ).all()
    snapshot.open_finding_count = len(active_rows)
    snapshot.critical_finding_count = sum(
        item.severity == "CRITICAL" for item in active_rows
    )
    snapshot.resolved_finding_count = resolved_count
    result["queue"] = {
        "open": snapshot.open_finding_count,
        "critical": snapshot.critical_finding_count,
        "auto_resolved": resolved_count,
        "unassigned": sum(item.owner_user_id is None for item in active_rows),
        "overdue": sum(
            item.due_at is not None and _aware(item.due_at) < now
            for item in active_rows
        ),
    }
    result_json = canonical_json(result)
    snapshot.result_json = result_json
    snapshot.result_hash = hashlib.sha256(result_json.encode()).hexdigest()
    db.flush()
    return snapshot


def certification_asset_snapshot(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_tag": asset.asset_tag,
        "name": asset.name,
        "ci_class_id": asset.ci_class_id,
        "ci_class_code": asset.ci_class_code,
        "ci_class_name": asset.ci_class_name,
        "ci_version": asset.ci_version,
        "lifecycle_status": asset.lifecycle_status,
        "owner_user_id": asset.owner_user_id,
        "support_group": asset.support_group,
        "criticality": asset.criticality,
        "environment": asset.environment,
        "location": asset.location,
        "source": asset.source,
        "updated_at": asset.updated_at.isoformat(),
    }


def assets_for_certification_scope(
    db: Session,
    *,
    tenant_id: str,
    scope: dict[str, Any],
) -> list[Asset]:
    statement = select(Asset).where(Asset.tenant_id == tenant_id)
    filters = {
        "asset_ids": (Asset.id, 5_000),
        "ci_class_ids": (Asset.ci_class_id, 500),
        "criticalities": (Asset.criticality, 10),
        "environments": (Asset.environment, 10),
        "lifecycle_statuses": (Asset.lifecycle_status, 20),
    }
    for key, (column, limit) in filters.items():
        raw = scope.get(key, [])
        if raw is None:
            continue
        if not isinstance(raw, list):
            raise ValueError(f"{key} must be a list")
        values = list(
            dict.fromkeys(
                str(item).strip() for item in raw if str(item).strip()
            )
        )
        if len(values) > limit:
            raise ValueError(f"{key} exceeds the allowed limit")
        if values:
            statement = statement.where(column.in_(values))
    if bool(scope.get("only_without_owner")):
        statement = statement.where(Asset.owner_user_id.is_(None))
    assets = db.scalars(statement.order_by(Asset.asset_tag).limit(5_001)).all()
    if len(assets) > 5_000:
        raise ValueError("certification scope exceeds 5000 CIs")
    if not assets:
        raise ValueError("certification scope contains no CIs")
    return list(assets)


def upsert_certification_rejection_finding(
    db: Session,
    *,
    tenant_id: str,
    asset: Asset,
    campaign_id: str,
    item_id: str,
    note: str,
    owner_user_id: str | None,
) -> CMDBQualityFinding:
    now = _now()
    finding = db.scalar(
        select(CMDBQualityFinding).where(
            CMDBQualityFinding.tenant_id == tenant_id,
            CMDBQualityFinding.rule_code == "CERTIFICATION_REJECTED",
            CMDBQualityFinding.subject_type == "CERTIFICATION_ITEM",
            CMDBQualityFinding.subject_id == item_id,
        )
    )
    evidence = {
        "campaign_id": campaign_id,
        "certification_item_id": item_id,
        "asset_tag": asset.asset_tag,
        "ci_version": asset.ci_version,
        "decision_note": note,
    }
    if finding is None:
        finding = CMDBQualityFinding(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rule_code="CERTIFICATION_REJECTED",
            dimension="CERTIFICATION",
            subject_type="CERTIFICATION_ITEM",
            subject_id=item_id,
            asset_id=asset.id,
            title="CI certification was rejected",
            details="Correct the CI data and run a new certification campaign.",
            evidence_json=canonical_json(evidence),
            severity=_severity(asset),
            status="OPEN",
            owner_user_id=asset.owner_user_id or owner_user_id,
            due_at=now + timedelta(
                days=REMEDIATION_DAYS[_severity(asset)]
            ),
            first_detected_at=now,
            last_detected_at=now,
            occurrence_count=1,
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(finding)
    else:
        finding.evidence_json = canonical_json(evidence)
        finding.status = "OPEN"
        finding.resolution_note = None
        finding.resolved_by_id = None
        finding.resolved_at = None
        finding.last_detected_at = now
        finding.occurrence_count += 1
        finding.version += 1
        finding.updated_at = now
    return finding
