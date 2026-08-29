from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.models.configuration_package import ConfigurationDeployment
from app.models.service_catalog import ServiceCategory
from app.models.tenant import Tenant
from app.services.configuration_packages import (
    ConfigurationPackageError,
    apply_deployment,
    build_deployment_plan,
    digest,
    export_artifact,
    rollback_deployment,
    sign_manifest,
    validate_artifact,
    validate_manifest,
)


def _settings() -> Settings:
    return Settings(
        app_env="development",
        demo_mode=True,
        configuration_package_signing_key=(
            "configuration-package-tests-signing-key-000000000000"
        ),
    )


def _component(
    component_type: str,
    key: str,
    data: dict,
    dependencies: list[str] | None = None,
) -> dict:
    return {
        "type": component_type,
        "key": key,
        "data": data,
        "dependencies": dependencies or [],
        "content_sha256": digest(data),
    }


def _manifest(components: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "package": {
            "code": "core.platform",
            "name": "Core platform",
            "version": 1,
            "source_environment": "local",
            "created_at": "2026-07-29T12:00:00+00:00",
        },
        "components": components,
    }


def _tenant(db_session) -> Tenant:
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Configuration Package Tests",
        slug=f"cfg-package-{uuid.uuid4().hex[:10]}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def test_signed_artifact_rejects_tampering_missing_dependencies_and_secrets() -> None:
    settings = _settings()
    category = _component(
        "catalog_category",
        "catalog_category:end-user",
        {
            "code": "end-user",
            "name": "End user",
            "description": None,
            "status": "ACTIVE",
            "sort_order": 100,
        },
    )
    service_data = {
        "code": "workplace",
        "category_code": "end-user",
        "name": "Workplace",
        "description": None,
        "support_group": "Service Desk",
        "status": "ACTIVE",
    }
    service = _component(
        "catalog_service",
        "catalog_service:workplace",
        service_data,
        ["catalog_category:end-user"],
    )
    manifest = _manifest([category, service])
    assert validate_manifest(manifest, settings)["valid"] is True

    signature = sign_manifest(manifest, settings)
    artifact = export_artifact(manifest, signature)
    validated = validate_artifact(artifact, settings)
    assert validated["valid"] is True
    assert validated["signature_valid"] is True

    artifact["manifest"]["components"][1]["data"]["name"] = "Tampered"
    tampered = validate_artifact(artifact, settings)
    assert tampered["valid"] is False
    assert tampered["signature_valid"] is False
    assert any("hash" in error.lower() for error in tampered["errors"])

    missing = _manifest([service])
    validation = validate_manifest(missing, settings)
    assert validation["valid"] is False
    assert any("dependencies are missing" in error for error in validation["errors"])

    unsafe_data = {**service_data, "api_token": "must-never-leave-source"}
    unsafe = _manifest(
        [
            category,
            _component(
                "catalog_service",
                "catalog_service:workplace",
                unsafe_data,
                ["catalog_category:end-user"],
            ),
        ]
    )
    validation = validate_manifest(unsafe, settings)
    assert validation["valid"] is False
    assert any("Sensitive configuration keys" in error for error in validation["errors"])


def test_apply_is_drift_safe_and_rollback_restores_previous_configuration(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    category = ServiceCategory(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        code="end-user",
        name="Old name",
        description="Old description",
        status="ACTIVE",
        sort_order=100,
    )
    db_session.add(category)
    db_session.flush()

    desired = _component(
        "catalog_category",
        "catalog_category:end-user",
        {
            "code": "end-user",
            "name": "New name",
            "description": "Promoted description",
            "status": "ACTIVE",
            "sort_order": 10,
        },
    )
    manifest = _manifest([desired])
    settings = _settings()
    plan = build_deployment_plan(
        db_session,
        tenant_id=tenant.id,
        manifest=manifest,
        settings=settings,
    )
    assert plan["valid"] is True
    assert plan["summary"]["UPDATE"] == 1

    deployment = ConfigurationDeployment(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        package_version_id=str(uuid.uuid4()),
        target_environment="staging",
        status="VALIDATED",
        idempotency_key=f"test-{uuid.uuid4()}",
        plan_json="{}",
        target_fingerprint_sha256=plan["target_fingerprint_sha256"],
        result_json="{}",
        reason="Test promotion",
    )
    applied = apply_deployment(
        db_session,
        deployment=deployment,
        manifest=manifest,
        actor_id=str(uuid.uuid4()),
        settings=settings,
    )
    assert category.name == "New name"
    assert applied["result"]["counts"]["UPDATE"] == 1

    deployment.snapshot_before_json = __import__("json").dumps(
        applied["snapshot"],
        ensure_ascii=False,
    )
    rollback = rollback_deployment(
        db_session,
        deployment=deployment,
        actor_id=str(uuid.uuid4()),
    )
    assert rollback["operations"] == [
        {"key": "catalog_category:end-user", "result": "RESTORED"}
    ]
    assert category.name == "Old name"
    assert category.description == "Old description"


def test_apply_refuses_target_drift_after_dry_run(db_session) -> None:
    tenant = _tenant(db_session)
    category = ServiceCategory(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        code="end-user",
        name="Initial",
        description=None,
        status="ACTIVE",
        sort_order=100,
    )
    db_session.add(category)
    db_session.flush()
    desired = _component(
        "catalog_category",
        "catalog_category:end-user",
        {
            "code": "end-user",
            "name": "Desired",
            "description": None,
            "status": "ACTIVE",
            "sort_order": 100,
        },
    )
    manifest = _manifest([desired])
    settings = _settings()
    plan = build_deployment_plan(
        db_session,
        tenant_id=tenant.id,
        manifest=manifest,
        settings=settings,
    )
    category.name = "Concurrent edit"
    db_session.flush()
    deployment = ConfigurationDeployment(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        package_version_id=str(uuid.uuid4()),
        target_environment="production",
        status="APPROVED",
        idempotency_key=f"test-{uuid.uuid4()}",
        plan_json="{}",
        target_fingerprint_sha256=plan["target_fingerprint_sha256"],
        result_json="{}",
        reason="Test drift",
    )
    with pytest.raises(ConfigurationPackageError, match="drifted"):
        apply_deployment(
            db_session,
            deployment=deployment,
            manifest=manifest,
            actor_id=str(uuid.uuid4()),
            settings=settings,
        )
    assert category.name == "Concurrent edit"
