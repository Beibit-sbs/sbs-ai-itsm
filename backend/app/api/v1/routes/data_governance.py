from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.data_governance import (
    DataDeletionEvidence,
    DataDeletionRequest,
    DataLegalHold,
    DataRetentionPolicy,
    RETENTION_CATEGORIES,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.data_governance import (
    GLOBAL_MINIMUM_RETENTION_DAYS,
    GovernanceBlockedExternal,
    active_holds,
    build_tenant_export,
    canonical_json,
    category_preview,
    effective_policy,
    execute_category_retention,
    execute_tenant_deletion,
    sha256_json,
    tenant_deletion_preview,
    utcnow,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/data-governance")


class RetentionPolicyUpdate(BaseModel):
    tenant_id: str | None = None
    scope: Literal["GLOBAL", "TENANT"] = "TENANT"
    category: str
    retention_days: int = Field(ge=30, le=3_650)
    archive_before_delete: bool = True
    anonymize_before_delete: bool = True
    is_enabled: bool = True
    expected_revision: int = Field(default=0, ge=0)


class LegalHoldCreate(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=10, max_length=4_000)
    scope_type: Literal["TENANT", "CATEGORY", "ENTITY"]
    category: str | None = None
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=120)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "LegalHoldCreate":
        if self.scope_type == "CATEGORY" and not self.category:
            raise ValueError("Category hold requires category")
        if self.scope_type == "ENTITY" and not (self.entity_type and self.entity_id):
            raise ValueError("Entity hold requires entity_type and entity_id")
        return self


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=4_000)


class DeletionPreviewRequest(BaseModel):
    tenant_id: str | None = None
    request_type: Literal["RETENTION_PURGE", "TENANT_DELETION"]
    category: str | None = None
    reason: str = Field(min_length=10, max_length=4_000)

    @model_validator(mode="after")
    def validate_category(self) -> "DeletionPreviewRequest":
        if self.request_type == "RETENTION_PURGE" and not self.category:
            raise ValueError("Retention purge requires category")
        if self.request_type == "TENANT_DELETION" and self.category:
            raise ValueError("Tenant deletion does not accept category")
        return self


class DeletionDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=10, max_length=4_000)


class DeletionExecuteRequest(BaseModel):
    confirmation: str


def _tenant_scope(
    db: Session,
    user: AuthUserResponse,
    requested: str | None,
) -> str:
    if not is_saas_root(user):
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return user.tenant_id
    if not requested or db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="A valid tenant_id is required")
    return requested


def _audit(
    db: Session,
    request: Request,
    user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str | None,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, user.id),
        actor_email=user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _ensure_category(category: str | None) -> str:
    normalized = (category or "").strip().upper()
    if normalized not in RETENTION_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported retention category")
    return normalized


def _policy_response(item: DataRetentionPolicy) -> dict[str, Any]:
    return {
        "id": item.id,
        "scope": "GLOBAL" if item.scope_key == "GLOBAL" else "TENANT",
        "tenant_id": item.tenant_id,
        "category": item.category,
        "retention_days": item.retention_days,
        "archive_before_delete": item.archive_before_delete,
        "anonymize_before_delete": item.anonymize_before_delete,
        "is_enabled": item.is_enabled,
        "revision": item.revision,
        "updated_at": item.updated_at,
    }


def _hold_response(item: DataLegalHold) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "reason": item.reason,
        "scope_type": item.scope_type,
        "category": item.category,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "status": item.status,
        "starts_at": item.starts_at,
        "expires_at": item.expires_at,
        "released_at": item.released_at,
        "release_reason": item.release_reason,
    }


def _request_response(item: DataDeletionRequest) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "request_type": item.request_type,
        "category": item.category,
        "cutoff_at": item.cutoff_at,
        "status": item.status,
        "reason": item.reason,
        "preview": json.loads(item.preview_json),
        "estimated_rows": item.estimated_rows,
        "plan_sha256": item.plan_sha256,
        "requested_by_id": item.requested_by_id,
        "approved_by_id": item.approved_by_id,
        "approval_reason": item.approval_reason,
        "approved_at": item.approved_at,
        "executed_by_id": item.executed_by_id,
        "executed_at": item.executed_at,
        "failure_reason": item.failure_reason,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "required_execution_confirmation": f"EXECUTE {item.id}",
    }


@router.get("/dashboard")
def data_governance_dashboard(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.retention.read")
    scope = _tenant_scope(db, user, tenant_id)
    policies = [
        effective_policy(db, tenant_id=scope, category=category)
        for category in RETENTION_CATEGORIES
    ]
    holds = active_holds(db, tenant_id=scope)
    requests = db.scalars(
        select(DataDeletionRequest)
        .where(DataDeletionRequest.tenant_id == scope)
        .order_by(DataDeletionRequest.created_at.desc())
        .limit(50)
    ).all()
    return {
        "tenant_id": scope,
        "policies": policies,
        "active_holds": [_hold_response(item) for item in holds],
        "recent_requests": [_request_response(item) for item in requests],
        "safety": {
            "preview_required": True,
            "four_eyes_approval": True,
            "legal_hold_fail_closed": True,
            "explicit_execution_phrase": True,
            "audit_chain_retirement": "BLOCKED_EXTERNAL_WORM",
        },
    }


@router.get("/policies")
def list_retention_policies(
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "data.retention.read")
    scope = _tenant_scope(db, user, tenant_id)
    items = db.scalars(
        select(DataRetentionPolicy)
        .where(
            (DataRetentionPolicy.scope_key == "GLOBAL")
            | (DataRetentionPolicy.scope_key == f"TENANT:{scope}")
        )
        .order_by(DataRetentionPolicy.scope_key, DataRetentionPolicy.category)
    ).all()
    return [_policy_response(item) for item in items]


@router.put("/policies")
def update_retention_policy(
    payload: RetentionPolicyUpdate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.retention.manage")
    category = _ensure_category(payload.category)
    if payload.scope == "GLOBAL":
        if not is_saas_root(user):
            raise HTTPException(status_code=403, detail="Global policy requires SaaS Root")
        hard_minimum = GLOBAL_MINIMUM_RETENTION_DAYS[category]
        if payload.retention_days < hard_minimum:
            raise HTTPException(
                status_code=422,
                detail=f"Global retention cannot be below {hard_minimum} days",
            )
        scope_key = "GLOBAL"
        tenant_id = None
    else:
        tenant_id = _tenant_scope(db, user, payload.tenant_id)
        scope_key = f"TENANT:{tenant_id}"
        minimum = int(
            effective_policy(db, tenant_id=tenant_id, category=category)[
                "global_minimum_days"
            ]
        )
        if payload.retention_days < minimum:
            raise HTTPException(
                status_code=422,
                detail=f"Tenant retention cannot be below global minimum {minimum} days",
            )
    item = db.scalar(
        select(DataRetentionPolicy).where(
            DataRetentionPolicy.scope_key == scope_key,
            DataRetentionPolicy.category == category,
        )
    )
    if item is None:
        if payload.expected_revision != 0:
            raise HTTPException(status_code=409, detail="Policy revision conflict")
        item = DataRetentionPolicy(
            id=str(uuid.uuid4()),
            scope_key=scope_key,
            tenant_id=tenant_id,
            category=category,
            retention_days=payload.retention_days,
            revision=1,
        )
        db.add(item)
    elif item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Policy revision conflict")
    else:
        item.revision += 1
    item.retention_days = payload.retention_days
    item.archive_before_delete = payload.archive_before_delete
    item.anonymize_before_delete = payload.anonymize_before_delete
    item.is_enabled = payload.is_enabled
    item.updated_by_id = user.id
    _audit(
        db,
        request,
        user,
        action="data_retention_policy_updated",
        entity_type="data_retention_policy",
        entity_id=item.id,
        tenant_id=tenant_id,
        metadata={
            "scope": payload.scope,
            "category": category,
            "retention_days": payload.retention_days,
            "revision": item.revision,
        },
    )
    db.commit()
    db.refresh(item)
    return _policy_response(item)


@router.get("/legal-holds")
def list_legal_holds(
    tenant_id: str | None = Query(default=None),
    include_released: bool = Query(default=True),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "data.legal_hold.read")
    scope = _tenant_scope(db, user, tenant_id)
    statement = select(DataLegalHold).where(DataLegalHold.tenant_id == scope)
    if not include_released:
        statement = statement.where(DataLegalHold.status == "ACTIVE")
    return [
        _hold_response(item)
        for item in db.scalars(
            statement.order_by(DataLegalHold.created_at.desc())
        ).all()
    ]


@router.post("/legal-holds", status_code=201)
def create_legal_hold(
    payload: LegalHoldCreate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.legal_hold.manage")
    scope = _tenant_scope(db, user, payload.tenant_id)
    category = _ensure_category(payload.category) if payload.category else None
    if payload.expires_at and payload.expires_at <= utcnow():
        raise HTTPException(status_code=422, detail="Legal hold expiry must be future")
    item = DataLegalHold(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        name=payload.name.strip(),
        reason=payload.reason.strip(),
        scope_type=payload.scope_type,
        category=category,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        status="ACTIVE",
        starts_at=utcnow(),
        expires_at=payload.expires_at,
        created_by_id=user.id,
    )
    db.add(item)
    _audit(
        db,
        request,
        user,
        action="data_legal_hold_created",
        entity_type="data_legal_hold",
        entity_id=item.id,
        tenant_id=scope,
        metadata={"scope_type": item.scope_type, "category": item.category},
    )
    db.commit()
    db.refresh(item)
    return _hold_response(item)


@router.post("/legal-holds/{hold_id}/release")
def release_legal_hold(
    hold_id: str,
    payload: ReasonRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.legal_hold.manage")
    item = db.get(DataLegalHold, hold_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Legal hold not found")
    _tenant_scope(db, user, item.tenant_id)
    if item.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Legal hold is not active")
    if item.created_by_id == user.id:
        raise HTTPException(
            status_code=409,
            detail="Legal hold release requires a different operator",
        )
    item.status = "RELEASED"
    item.released_by_id = user.id
    item.released_at = utcnow()
    item.release_reason = payload.reason.strip()
    _audit(
        db,
        request,
        user,
        action="data_legal_hold_released",
        entity_type="data_legal_hold",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": item.release_reason},
    )
    db.commit()
    db.refresh(item)
    return _hold_response(item)


@router.post("/deletion-requests/preview", status_code=201)
def preview_deletion(
    payload: DeletionPreviewRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.deletion.request")
    scope = _tenant_scope(db, user, payload.tenant_id)
    if payload.request_type == "TENANT_DELETION":
        if not is_saas_root(user):
            raise HTTPException(status_code=403, detail="Tenant deletion requires SaaS Root")
        if user.tenant_id == scope:
            raise HTTPException(status_code=409, detail="Cannot delete the operator tenant")
        category = None
        preview = tenant_deletion_preview(db, tenant_id=scope)
        cutoff = None
    else:
        category = _ensure_category(payload.category)
        preview = category_preview(db, tenant_id=scope, category=category)
        cutoff = preview["cutoff_at"]
    item = DataDeletionRequest(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        request_type=payload.request_type,
        category=category,
        cutoff_at=cutoff,
        status="PREVIEWED",
        reason=payload.reason.strip(),
        preview_json=canonical_json(preview),
        estimated_rows=int(preview["estimated_rows"]),
        plan_sha256=str(preview["plan_sha256"]),
        requested_by_id=user.id,
    )
    db.add(item)
    _audit(
        db,
        request,
        user,
        action="data_deletion_preview_created",
        entity_type="data_deletion_request",
        entity_id=item.id,
        tenant_id=scope,
        metadata={
            "request_type": item.request_type,
            "category": item.category,
            "estimated_rows": item.estimated_rows,
            "plan_sha256": item.plan_sha256,
        },
    )
    db.commit()
    db.refresh(item)
    return _request_response(item)


@router.post("/deletion-requests/{request_id}/submit")
def submit_deletion_request(
    request_id: str,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.deletion.request")
    item = db.get(DataDeletionRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    _tenant_scope(db, user, item.tenant_id)
    if item.requested_by_id != user.id and not is_saas_root(user):
        raise HTTPException(status_code=403, detail="Only requester may submit")
    if item.status != "PREVIEWED":
        raise HTTPException(status_code=409, detail="Request is not in preview state")
    preview = json.loads(item.preview_json)
    if preview.get("blocked_by_legal_hold"):
        raise HTTPException(status_code=409, detail="Active legal hold blocks deletion")
    item.status = "PENDING_APPROVAL"
    _audit(
        db,
        request,
        user,
        action="data_deletion_requested",
        entity_type="data_deletion_request",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"plan_sha256": item.plan_sha256},
    )
    db.commit()
    db.refresh(item)
    return _request_response(item)


@router.post("/deletion-requests/{request_id}/decision")
def decide_deletion_request(
    request_id: str,
    payload: DeletionDecisionRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.deletion.approve")
    item = db.get(DataDeletionRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    _tenant_scope(db, user, item.tenant_id)
    if item.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Request is not awaiting approval")
    if item.requested_by_id == user.id:
        raise HTTPException(
            status_code=409,
            detail="Four-eyes control forbids requester self-approval",
        )
    if payload.decision == "APPROVE" and active_holds(
        db, tenant_id=item.tenant_id, category=item.category
    ):
        raise HTTPException(status_code=409, detail="Active legal hold blocks approval")
    item.status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    item.approved_by_id = user.id
    item.approved_at = utcnow()
    item.approval_reason = payload.reason.strip()
    _audit(
        db,
        request,
        user,
        action=f"data_deletion_{payload.decision.lower()}",
        entity_type="data_deletion_request",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": item.approval_reason, "plan_sha256": item.plan_sha256},
    )
    db.commit()
    db.refresh(item)
    return _request_response(item)


@router.post("/deletion-requests/{request_id}/execute")
def execute_deletion_request(
    request_id: str,
    payload: DeletionExecuteRequest,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.deletion.execute")
    item = db.get(DataDeletionRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    _tenant_scope(db, user, item.tenant_id)
    if item.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Request is not approved")
    if payload.confirmation != f"EXECUTE {item.id}":
        raise HTTPException(status_code=422, detail="Exact execution phrase is required")
    if active_holds(db, tenant_id=item.tenant_id, category=item.category):
        raise HTTPException(status_code=409, detail="Active legal hold blocks execution")
    if item.request_type == "RETENTION_PURGE":
        if item.category is None or item.cutoff_at is None:
            raise HTTPException(status_code=409, detail="Retention plan is incomplete")
        current = category_preview(
            db,
            tenant_id=item.tenant_id,
            category=item.category,
            cutoff_override=item.cutoff_at,
        )
    else:
        current = tenant_deletion_preview(db, tenant_id=item.tenant_id)
    if current["plan_sha256"] != item.plan_sha256:
        raise HTTPException(
            status_code=409,
            detail="Deletion plan changed; create and approve a new preview",
        )
    item.status = "EXECUTING"
    db.flush()
    try:
        if item.request_type == "RETENTION_PURGE":
            result = execute_category_retention(
                db,
                tenant_id=item.tenant_id,
                category=item.category or "",
                cutoff=item.cutoff_at,
            )
        else:
            result = execute_tenant_deletion(db, tenant_id=item.tenant_id)
    except GovernanceBlockedExternal as exc:
        item.status = "BLOCKED_EXTERNAL"
        item.failure_reason = str(exc)
        item.executed_by_id = user.id
        item.executed_at = utcnow()
        _audit(
            db,
            request,
            user,
            action="data_deletion_blocked_external",
            entity_type="data_deletion_request",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={"reason": str(exc), "plan_sha256": item.plan_sha256},
        )
        db.commit()
        db.refresh(item)
        return _request_response(item)
    item.status = "COMPLETED"
    item.executed_by_id = user.id
    item.executed_at = utcnow()
    result_payload = {
        "request_id": item.id,
        "tenant_id": item.tenant_id,
        "request_type": item.request_type,
        "plan_sha256": item.plan_sha256,
        "executed_at": item.executed_at,
        "result": result,
    }
    result_json = canonical_json(result_payload)
    evidence = DataDeletionEvidence(
        id=str(uuid.uuid4()),
        deletion_request_id=item.id,
        tenant_id=item.tenant_id,
        result_json=result_json,
        result_sha256=hashlib.sha256(result_json.encode("utf-8")).hexdigest(),
        archive_manifest_sha256=sha256_json(current),
    )
    db.add(evidence)
    _audit(
        db,
        request,
        user,
        action="data_deletion_completed",
        entity_type="data_deletion_request",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "result_sha256": evidence.result_sha256,
            "archive_manifest_sha256": evidence.archive_manifest_sha256,
        },
    )
    db.commit()
    db.refresh(item)
    return _request_response(item) | {
        "evidence": {
            "id": evidence.id,
            "result_sha256": evidence.result_sha256,
            "archive_manifest_sha256": evidence.archive_manifest_sha256,
        }
    }


@router.get("/deletion-requests")
def list_deletion_requests(
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "data.retention.read")
    scope = _tenant_scope(db, user, tenant_id)
    return [
        _request_response(item)
        for item in db.scalars(
            select(DataDeletionRequest)
            .where(DataDeletionRequest.tenant_id == scope)
            .order_by(DataDeletionRequest.created_at.desc())
            .limit(limit)
        ).all()
    ]


@router.get("/deletion-requests/{request_id}/evidence")
def get_deletion_evidence(
    request_id: str,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "data.retention.read")
    item = db.get(DataDeletionRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    _tenant_scope(db, user, item.tenant_id)
    evidence = db.scalar(
        select(DataDeletionEvidence).where(
            DataDeletionEvidence.deletion_request_id == item.id
        )
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Deletion evidence not found")
    return {
        "id": evidence.id,
        "deletion_request_id": item.id,
        "tenant_id": evidence.tenant_id,
        "result": json.loads(evidence.result_json),
        "result_sha256": evidence.result_sha256,
        "archive_manifest_sha256": evidence.archive_manifest_sha256,
        "created_at": evidence.created_at,
    }


@router.get("/tenant-export")
def export_tenant_data(
    request: Request,
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    require_permissions(user, "data.export")
    scope = _tenant_scope(db, user, tenant_id)
    payload, manifest = build_tenant_export(db, tenant_id=scope)
    _audit(
        db,
        request,
        user,
        action="tenant_data_exported",
        entity_type="tenant",
        entity_id=scope,
        tenant_id=scope,
        metadata={
            "archive_sha256": manifest["archive_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
            "table_count": manifest["table_count"],
            "row_count": manifest["row_count"],
            "secrets_included": False,
        },
    )
    db.commit()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="tenant-{scope}-export.zip"',
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Export-SHA256": str(manifest["archive_sha256"]),
        },
    )
