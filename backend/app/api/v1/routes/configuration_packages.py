from __future__ import annotations

from datetime import UTC, datetime
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.configuration_package import (
    ConfigurationDeployment,
    ConfigurationPackage,
    ConfigurationPackageVersion,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import log_audit
from app.services.configuration_packages import (
    SUPPORTED_COMPONENT_TYPES,
    ConfigurationPackageError,
    apply_deployment,
    build_deployment_plan,
    canonical_json,
    collect_manifest,
    digest,
    export_artifact,
    json_object,
    rollback_deployment,
    sign_manifest,
    validate_artifact,
    validate_manifest,
    verify_signature,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/configuration-packages")


class PackageCreate(BaseModel):
    tenant_id: str | None = None
    code: str = Field(min_length=3, max_length=120, pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)


class PackageUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
    reason: str = Field(min_length=3, max_length=2_000)


class VersionBuild(BaseModel):
    expected_package_revision: int = Field(ge=1)
    source_environment: str = Field(
        min_length=2,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]+$",
    )
    component_types: list[str] = Field(min_length=1)
    change_summary: str = Field(min_length=3, max_length=2_000)


class VersionSeal(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class ArtifactImport(BaseModel):
    tenant_id: str | None = None
    artifact: dict[str, Any]
    change_summary: str = Field(min_length=3, max_length=2_000)


class DeploymentCreate(BaseModel):
    tenant_id: str | None = None
    package_version_id: str
    target_environment: Literal["development", "test", "staging", "production"]
    idempotency_key: str = Field(min_length=8, max_length=120)
    reason: str = Field(min_length=3, max_length=2_000)


class RevisionReason(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2_000)


class ReviewDecision(BaseModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]
    comment: str = Field(min_length=3, max_length=2_000)


def _tenant_id(db: Session, current_user: AuthUserResponse, requested: str | None) -> str:
    if not is_saas_root(current_user):
        if not current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return current_user.tenant_id
    if not requested:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required for SaaS Root configuration-package administration",
        )
    if db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="Tenant is unavailable")
    return requested


def _scope(current_user: AuthUserResponse, tenant_id: str) -> None:
    if not is_saas_root(current_user) and current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Configuration resource not found")


def _package(
    db: Session,
    package_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationPackage:
    statement = select(ConfigurationPackage).where(ConfigurationPackage.id == package_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Configuration package not found")
    _scope(current_user, item.tenant_id)
    return item


def _version(
    db: Session,
    version_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationPackageVersion:
    statement = select(ConfigurationPackageVersion).where(
        ConfigurationPackageVersion.id == version_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Configuration package version not found")
    _scope(current_user, item.tenant_id)
    return item


def _deployment(
    db: Session,
    deployment_id: str,
    current_user: AuthUserResponse,
    *,
    lock: bool = False,
) -> ConfigurationDeployment:
    statement = select(ConfigurationDeployment).where(
        ConfigurationDeployment.id == deployment_id
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Configuration deployment not found")
    _scope(current_user, item.tenant_id)
    return item


def _audit(
    db: Session,
    request: Request,
    current_user: AuthUserResponse,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=db.get(User, current_user.id),
        actor_email=current_user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _package_response(item: ConfigurationPackage) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "latest_version_number": item.latest_version_number,
        "revision": item.revision,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _version_response(
    item: ConfigurationPackageVersion,
    *,
    include_manifest: bool = False,
) -> dict[str, object]:
    manifest = json_object(item.manifest_json)
    result: dict[str, object] = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "package_id": item.package_id,
        "version_number": item.version_number,
        "status": item.status,
        "source_environment": item.source_environment,
        "manifest_sha256": item.manifest_sha256,
        "integrity_valid": digest(manifest) == item.manifest_sha256,
        "signed": bool(item.signature_hmac_sha256),
        "validation_status": item.validation_status,
        "validation": json_object(item.validation_json),
        "component_count": item.component_count,
        "dependency_count": item.dependency_count,
        "change_summary": item.change_summary,
        "revision": item.revision,
        "imported_from_artifact": item.imported_from_artifact,
        "created_by_id": item.created_by_id,
        "updated_by_id": item.updated_by_id,
        "sealed_by_id": item.sealed_by_id,
        "sealed_at": item.sealed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if include_manifest:
        result["manifest"] = manifest
    return result


def _deployment_response(item: ConfigurationDeployment) -> dict[str, object]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "package_version_id": item.package_version_id,
        "target_environment": item.target_environment,
        "status": item.status,
        "idempotency_key": item.idempotency_key,
        "plan": json_object(item.plan_json),
        "plan_sha256": item.plan_sha256,
        "target_fingerprint_sha256": item.target_fingerprint_sha256,
        "snapshot_before_sha256": item.snapshot_before_sha256,
        "result": json_object(item.result_json),
        "result_sha256": item.result_sha256,
        "revision": item.revision,
        "reason": item.reason,
        "review_comment": item.review_comment,
        "error_message": item.error_message,
        "requested_by_id": item.requested_by_id,
        "reviewed_by_id": item.reviewed_by_id,
        "applied_by_id": item.applied_by_id,
        "rolled_back_by_id": item.rolled_back_by_id,
        "requested_at": item.requested_at,
        "reviewed_at": item.reviewed_at,
        "applied_at": item.applied_at,
        "rolled_back_at": item.rolled_back_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/meta")
def configuration_package_meta(
    current_user: AuthUserResponse = Depends(get_current_user),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.read")
    settings = get_settings()
    return {
        "artifact_format": "sbs-itsm-configuration-package",
        "schema_version": "1.0",
        "supported_component_types": SUPPORTED_COMPONENT_TYPES,
        "max_components": settings.configuration_package_max_components,
        "max_bytes": settings.configuration_package_max_bytes,
        "production_requires_independent_approval": True,
        "secrets_exported": False,
    }


@router.get("")
def list_configuration_packages(
    tenant_id: str | None = Query(default=None),
    status_filter: Literal["ACTIVE", "ARCHIVED"] | None = Query(default=None, alias="status"),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.read")
    scope = _tenant_id(db, current_user, tenant_id)
    statement = select(ConfigurationPackage).where(ConfigurationPackage.tenant_id == scope)
    if status_filter:
        statement = statement.where(ConfigurationPackage.status == status_filter)
    items = db.scalars(statement.order_by(ConfigurationPackage.updated_at.desc())).all()
    return {"items": [_package_response(item) for item in items], "count": len(items)}


@router.get("/dashboard")
def get_configuration_dashboard(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.read")
    scope = _tenant_id(db, current_user, tenant_id)
    package_count = db.scalar(
        select(func.count(ConfigurationPackage.id)).where(
            ConfigurationPackage.tenant_id == scope,
            ConfigurationPackage.status == "ACTIVE",
        )
    ) or 0
    version_count = db.scalar(
        select(func.count(ConfigurationPackageVersion.id)).where(
            ConfigurationPackageVersion.tenant_id == scope,
            ConfigurationPackageVersion.status == "SEALED",
        )
    ) or 0
    deployments = db.scalars(
        select(ConfigurationDeployment).where(ConfigurationDeployment.tenant_id == scope)
    ).all()
    return {
        "active_packages": package_count,
        "sealed_versions": version_count,
        "pending_approvals": sum(item.status == "PENDING_APPROVAL" for item in deployments),
        "applied_deployments": sum(item.status == "APPLIED" for item in deployments),
        "failed_deployments": sum(item.status == "FAILED" for item in deployments),
        "rolled_back_deployments": sum(item.status == "ROLLED_BACK" for item in deployments),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_configuration_package(
    payload: PackageCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.build")
    scope = _tenant_id(db, current_user, payload.tenant_id)
    item = ConfigurationPackage(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        status="ACTIVE",
        latest_version_number=0,
        revision=1,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Configuration package code already exists") from exc
    _audit(
        db,
        request,
        current_user,
        action="configuration_package.created",
        entity_type="configuration_package",
        entity_id=item.id,
        tenant_id=scope,
        metadata={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return _package_response(item)


@router.patch("/{package_id}")
def update_configuration_package(
    package_id: str,
    payload: PackageUpdate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.build")
    item = _package(db, package_id, current_user, lock=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration package revision conflict")
    changes: list[str] = []
    for field in ("name", "description", "status"):
        value = getattr(payload, field)
        if value is not None and value != getattr(item, field):
            setattr(item, field, value)
            changes.append(field)
    if not changes:
        raise HTTPException(status_code=422, detail="No configuration package changes supplied")
    item.revision += 1
    item.updated_by_id = current_user.id
    _audit(
        db,
        request,
        current_user,
        action="configuration_package.updated",
        entity_type="configuration_package",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"fields": changes, "reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _package_response(item)


@router.get("/{package_id}/versions")
def list_configuration_package_versions(
    package_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.read")
    item = _package(db, package_id, current_user)
    versions = db.scalars(
        select(ConfigurationPackageVersion)
        .where(ConfigurationPackageVersion.package_id == item.id)
        .order_by(ConfigurationPackageVersion.version_number.desc())
    ).all()
    return {"items": [_version_response(version) for version in versions], "count": len(versions)}


@router.post("/{package_id}/versions", status_code=status.HTTP_201_CREATED)
def build_configuration_package_version(
    package_id: str,
    payload: VersionBuild,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.build")
    item = _package(db, package_id, current_user, lock=True)
    if item.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Configuration package is archived")
    if item.revision != payload.expected_package_revision:
        raise HTTPException(status_code=409, detail="Configuration package revision conflict")
    number = item.latest_version_number + 1
    try:
        manifest = collect_manifest(
            db,
            tenant_id=item.tenant_id,
            package_code=item.code,
            package_name=item.name,
            version_number=number,
            source_environment=payload.source_environment,
            component_types=set(payload.component_types),
        )
    except ConfigurationPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings = get_settings()
    validation = validate_manifest(manifest, settings)
    version = ConfigurationPackageVersion(
        id=str(uuid.uuid4()),
        tenant_id=item.tenant_id,
        package_id=item.id,
        version_number=number,
        status="DRAFT",
        source_environment=payload.source_environment,
        manifest_json=canonical_json(manifest),
        manifest_sha256=digest(manifest),
        validation_status="VALID" if validation["valid"] else "INVALID",
        validation_json=canonical_json(validation),
        component_count=int(validation["component_count"]),
        dependency_count=int(validation["dependency_count"]),
        change_summary=payload.change_summary,
        revision=1,
        imported_from_artifact=False,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(version)
    item.latest_version_number = number
    item.revision += 1
    item.updated_by_id = current_user.id
    _audit(
        db,
        request,
        current_user,
        action="configuration_package.version_built",
        entity_type="configuration_package_version",
        entity_id=version.id,
        tenant_id=item.tenant_id,
        metadata={
            "package_id": item.id,
            "version_number": number,
            "component_count": version.component_count,
            "validation_status": version.validation_status,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version, include_manifest=True)


@router.post("/versions/{version_id}/seal")
def seal_configuration_package_version(
    version_id: str,
    payload: VersionSeal,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.seal")
    item = _version(db, version_id, current_user, lock=True)
    if item.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only a draft version can be sealed")
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration package version revision conflict")
    manifest = json_object(item.manifest_json)
    settings = get_settings()
    validation = validate_manifest(manifest, settings)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={"message": "Package is invalid", **validation})
    if digest(manifest) != item.manifest_sha256:
        raise HTTPException(status_code=409, detail="Package manifest integrity check failed")
    item.status = "SEALED"
    item.validation_status = "VALID"
    item.validation_json = canonical_json(validation)
    item.signature_hmac_sha256 = sign_manifest(manifest, settings)
    item.sealed_by_id = current_user.id
    item.sealed_at = datetime.now(UTC)
    item.revision += 1
    _audit(
        db,
        request,
        current_user,
        action="configuration_package.version_sealed",
        entity_type="configuration_package_version",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "version_number": item.version_number,
            "manifest_sha256": item.manifest_sha256,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(item)
    return _version_response(item)


@router.get("/versions/{version_id}/export")
def export_configuration_package_version(
    version_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(current_user, "configuration.packages.export")
    item = _version(db, version_id, current_user)
    if item.status != "SEALED" or not item.signature_hmac_sha256:
        raise HTTPException(status_code=409, detail="Only a sealed package version can be exported")
    manifest = json_object(item.manifest_json)
    if digest(manifest) != item.manifest_sha256:
        raise HTTPException(status_code=409, detail="Package manifest integrity check failed")
    return export_artifact(manifest, item.signature_hmac_sha256)


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_configuration_package(
    payload: ArtifactImport,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.import")
    scope = _tenant_id(db, current_user, payload.tenant_id)
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.configuration_package_max_bytes + 1_048_576:
                raise HTTPException(status_code=413, detail="Configuration artifact is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    validation = validate_artifact(payload.artifact, settings)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={"message": "Artifact rejected", **validation})
    manifest: dict[str, Any] = payload.artifact["manifest"]
    metadata: dict[str, Any] = manifest["package"]
    code = str(metadata["code"])
    package_statement = select(ConfigurationPackage).where(
            ConfigurationPackage.tenant_id == scope,
            ConfigurationPackage.code == code,
        )
    if db.get_bind().dialect.name == "postgresql":
        package_statement = package_statement.with_for_update()
    item = db.scalar(package_statement)
    if item is None:
        item = ConfigurationPackage(
            id=str(uuid.uuid4()),
            tenant_id=scope,
            code=code,
            name=str(metadata.get("name") or code),
            status="ACTIVE",
            latest_version_number=0,
            revision=1,
            created_by_id=current_user.id,
            updated_by_id=current_user.id,
        )
        db.add(item)
        db.flush()
    number = item.latest_version_number + 1
    version = ConfigurationPackageVersion(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        package_id=item.id,
        version_number=number,
        status="SEALED",
        source_environment=str(metadata.get("source_environment", "import")),
        manifest_json=canonical_json(manifest),
        manifest_sha256=str(payload.artifact["manifest_sha256"]),
        signature_hmac_sha256=str(payload.artifact["signature"]),
        validation_status="VALID",
        validation_json=canonical_json(validation),
        component_count=int(validation["component_count"]),
        dependency_count=int(validation["dependency_count"]),
        change_summary=payload.change_summary,
        revision=1,
        imported_from_artifact=True,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        sealed_by_id=current_user.id,
        sealed_at=datetime.now(UTC),
    )
    db.add(version)
    item.latest_version_number = number
    item.revision += 1
    item.updated_by_id = current_user.id
    _audit(
        db,
        request,
        current_user,
        action="configuration_package.imported",
        entity_type="configuration_package_version",
        entity_id=version.id,
        tenant_id=scope,
        metadata={
            "source_package_version": metadata.get("version"),
            "local_version_number": number,
            "manifest_sha256": version.manifest_sha256,
        },
    )
    db.commit()
    db.refresh(version)
    return _version_response(version, include_manifest=True)


@router.get("/versions/{source_version_id}/compare/{target_version_id}")
def compare_configuration_package_versions(
    source_version_id: str,
    target_version_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.packages.read")
    source = _version(db, source_version_id, current_user)
    target = _version(db, target_version_id, current_user)
    if source.tenant_id != target.tenant_id:
        raise HTTPException(status_code=404, detail="Configuration package version not found")
    source_components = {
        item["key"]: item
        for item in json_object(source.manifest_json).get("components", [])
        if isinstance(item, dict) and item.get("key")
    }
    target_components = {
        item["key"]: item
        for item in json_object(target.manifest_json).get("components", [])
        if isinstance(item, dict) and item.get("key")
    }
    keys = sorted(set(source_components) | set(target_components))
    changes = []
    for key in keys:
        before = source_components.get(key)
        after = target_components.get(key)
        change = (
            "ADDED"
            if before is None
            else "REMOVED"
            if after is None
            else "UNCHANGED"
            if before.get("content_sha256") == after.get("content_sha256")
            else "CHANGED"
        )
        changes.append(
            {
                "key": key,
                "change": change,
                "source_sha256": before.get("content_sha256") if before else None,
                "target_sha256": after.get("content_sha256") if after else None,
            }
        )
    return {
        "source_version_id": source.id,
        "target_version_id": target.id,
        "changes": changes,
        "summary": {
            change: sum(item["change"] == change for item in changes)
            for change in ("ADDED", "REMOVED", "CHANGED", "UNCHANGED")
        },
    }


@router.get("/deployments")
def list_configuration_deployments(
    tenant_id: str | None = Query(default=None),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.read")
    scope = _tenant_id(db, current_user, tenant_id)
    items = db.scalars(
        select(ConfigurationDeployment)
        .where(ConfigurationDeployment.tenant_id == scope)
        .order_by(ConfigurationDeployment.created_at.desc())
    ).all()
    return {"items": [_deployment_response(item) for item in items], "count": len(items)}


@router.post("/deployments", status_code=status.HTTP_201_CREATED)
def create_configuration_deployment(
    payload: DeploymentCreate,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.plan")
    scope = _tenant_id(db, current_user, payload.tenant_id)
    existing = db.scalar(
        select(ConfigurationDeployment).where(
            ConfigurationDeployment.tenant_id == scope,
            ConfigurationDeployment.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if (
            existing.package_version_id != payload.package_version_id
            or existing.target_environment != payload.target_environment
            or existing.reason != payload.reason
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used for a different deployment request",
            )
        return _deployment_response(existing)
    version = db.get(ConfigurationPackageVersion, payload.package_version_id)
    if version is None or version.tenant_id != scope:
        raise HTTPException(status_code=404, detail="Configuration package version not found")
    if version.status != "SEALED" or not version.signature_hmac_sha256:
        raise HTTPException(status_code=409, detail="Deployment requires a sealed package version")
    manifest = json_object(version.manifest_json)
    settings = get_settings()
    if digest(manifest) != version.manifest_sha256 or not verify_signature(
        manifest, version.signature_hmac_sha256, settings
    ):
        raise HTTPException(status_code=409, detail="Package integrity or signature check failed")
    plan = build_deployment_plan(db, tenant_id=scope, manifest=manifest, settings=settings)
    item = ConfigurationDeployment(
        id=str(uuid.uuid4()),
        tenant_id=scope,
        package_version_id=version.id,
        target_environment=payload.target_environment.strip().lower(),
        status="VALIDATED" if plan["valid"] else "DRAFT",
        idempotency_key=payload.idempotency_key,
        plan_json=canonical_json(plan),
        plan_sha256=digest(plan),
        target_fingerprint_sha256=str(plan["target_fingerprint_sha256"]),
        result_json="{}",
        revision=1,
        reason=payload.reason,
        requested_by_id=current_user.id,
        requested_at=datetime.now(UTC),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ConfigurationDeployment).where(
                ConfigurationDeployment.tenant_id == scope,
                ConfigurationDeployment.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.package_version_id != payload.package_version_id
                or existing.target_environment != payload.target_environment
                or existing.reason != payload.reason
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Idempotency key was already used for a different "
                        "deployment request"
                    ),
                )
            return _deployment_response(existing)
        raise
    _audit(
        db,
        request,
        current_user,
        action="configuration_deployment.planned",
        entity_type="configuration_deployment",
        entity_id=item.id,
        tenant_id=scope,
        metadata={
            "package_version_id": version.id,
            "target_environment": item.target_environment,
            "valid": plan["valid"],
            "summary": plan["summary"],
        },
    )
    db.commit()
    db.refresh(item)
    return _deployment_response(item)


@router.post("/deployments/{deployment_id}/request-approval")
def request_configuration_deployment_approval(
    deployment_id: str,
    payload: RevisionReason,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.plan")
    item = _deployment(db, deployment_id, current_user, lock=True)
    if item.status != "VALIDATED":
        raise HTTPException(status_code=409, detail="Only a validated deployment can be submitted")
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration deployment revision conflict")
    item.status = "PENDING_APPROVAL"
    item.reason = payload.reason
    item.requested_by_id = current_user.id
    item.requested_at = datetime.now(UTC)
    item.revision += 1
    _audit(
        db,
        request,
        current_user,
        action="configuration_deployment.approval_requested",
        entity_type="configuration_deployment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"target_environment": item.target_environment, "reason": payload.reason},
    )
    db.commit()
    db.refresh(item)
    return _deployment_response(item)


@router.post("/deployments/{deployment_id}/decision")
def decide_configuration_deployment(
    deployment_id: str,
    payload: ReviewDecision,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.approve")
    item = _deployment(db, deployment_id, current_user, lock=True)
    if item.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Deployment is not pending approval")
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration deployment revision conflict")
    if item.requested_by_id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="The requester cannot approve their own configuration deployment",
        )
    item.status = payload.decision
    item.reviewed_by_id = current_user.id
    item.reviewed_at = datetime.now(UTC)
    item.review_comment = payload.comment
    item.revision += 1
    _audit(
        db,
        request,
        current_user,
        action=f"configuration_deployment.{payload.decision.lower()}",
        entity_type="configuration_deployment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"comment": payload.comment},
    )
    db.commit()
    db.refresh(item)
    return _deployment_response(item)


@router.post("/deployments/{deployment_id}/apply")
def apply_configuration_deployment(
    deployment_id: str,
    payload: RevisionReason,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.apply")
    item = _deployment(db, deployment_id, current_user, lock=True)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration deployment revision conflict")
    production = item.target_environment == "production"
    allowed = {"APPROVED"} if production else {"VALIDATED", "APPROVED"}
    if item.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail="Production requires independent approval; non-production requires validation",
        )
    version = db.get(ConfigurationPackageVersion, item.package_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="Package version is unavailable")
    manifest = json_object(version.manifest_json)
    settings = get_settings()
    try:
        with db.begin_nested():
            applied = apply_deployment(
                db,
                deployment=item,
                manifest=manifest,
                actor_id=current_user.id,
                settings=settings,
            )
    except ConfigurationPackageError as exc:
        item.status = "FAILED"
        item.error_message = str(exc)
        item.result_json = canonical_json(
            {"failed_at": datetime.now(UTC).isoformat(), "error": str(exc)}
        )
        item.result_sha256 = digest(json_object(item.result_json))
        item.revision += 1
        _audit(
            db,
            request,
            current_user,
            action="configuration_deployment.failed",
            entity_type="configuration_deployment",
            entity_id=item.id,
            tenant_id=item.tenant_id,
            metadata={"error": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = applied["snapshot"]
    result = applied["result"]
    item.snapshot_before_json = canonical_json(snapshot)
    item.snapshot_before_sha256 = digest(snapshot)
    item.result_json = canonical_json(result)
    item.result_sha256 = digest(result)
    item.status = "APPLIED"
    item.applied_by_id = current_user.id
    item.applied_at = datetime.now(UTC)
    item.error_message = None
    item.reason = payload.reason
    item.revision += 1
    _audit(
        db,
        request,
        current_user,
        action="configuration_deployment.applied",
        entity_type="configuration_deployment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={
            "target_environment": item.target_environment,
            "snapshot_sha256": item.snapshot_before_sha256,
            "result_sha256": item.result_sha256,
        },
    )
    db.commit()
    db.refresh(item)
    return _deployment_response(item)


@router.post("/deployments/{deployment_id}/rollback")
def rollback_configuration_deployment(
    deployment_id: str,
    payload: RevisionReason,
    request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_permissions(current_user, "configuration.deployments.rollback")
    item = _deployment(db, deployment_id, current_user, lock=True)
    if item.status != "APPLIED":
        raise HTTPException(status_code=409, detail="Only an applied deployment can be rolled back")
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration deployment revision conflict")
    if not item.snapshot_before_json or digest(json_object(item.snapshot_before_json)) != item.snapshot_before_sha256:
        raise HTTPException(status_code=409, detail="Rollback snapshot integrity check failed")
    try:
        with db.begin_nested():
            result = rollback_deployment(db, deployment=item, actor_id=current_user.id)
    except ConfigurationPackageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    item.status = "ROLLED_BACK"
    item.rolled_back_by_id = current_user.id
    item.rolled_back_at = datetime.now(UTC)
    item.result_json = canonical_json(
        {
            "original_apply": json_object(item.result_json),
            "rollback": result,
            "reason": payload.reason,
        }
    )
    item.result_sha256 = digest(json_object(item.result_json))
    item.revision += 1
    _audit(
        db,
        request,
        current_user,
        action="configuration_deployment.rolled_back",
        entity_type="configuration_deployment",
        entity_id=item.id,
        tenant_id=item.tenant_id,
        metadata={"reason": payload.reason, "result_sha256": item.result_sha256},
    )
    db.commit()
    db.refresh(item)
    return _deployment_response(item)
