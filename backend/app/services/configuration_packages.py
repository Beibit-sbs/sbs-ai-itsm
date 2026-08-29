from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.configuration_package import ConfigurationDeployment
from app.models.custom_fields import CustomFieldSet, CustomFieldSetVersion
from app.models.external_system import ExternalSystem
from app.models.integration_mapping import IntegrationMapping
from app.models.notification_template import NotificationTemplate
from app.models.service_catalog import (
    CatalogItem,
    CatalogService,
    ServiceCategory,
    ServiceOffering,
)
from app.models.sla import SlaBusinessCalendar, SlaCalendarException, SlaPolicy
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.workflow_engine import WorkflowDefinition, WorkflowVersion
from app.services.custom_fields import schema_hash, validate_custom_field_schema
from app.services.workflow_engine import validate_workflow_definition


SUPPORTED_COMPONENT_TYPES = (
    "catalog_category",
    "catalog_service",
    "catalog_offering",
    "catalog_item",
    "sla_calendar",
    "sla_policy",
    "notification_template",
    "external_system",
    "integration_mapping",
    "webhook_endpoint",
    "workflow",
    "custom_field_set",
)
_APPLY_ORDER = {name: index for index, name in enumerate(SUPPORTED_COMPONENT_TYPES)}
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|shared[_-]?key|"
    r"private[_-]?key|signing[_-]?key|credential|authorization|bearer)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:bearer\s+\S+|://[^/\s:@]+:[^/\s@]+@|[?&](?:token|key|secret|password)=)",
    re.IGNORECASE,
)


class ConfigurationPackageError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def signing_key(settings: Settings) -> bytes:
    configured = settings.configuration_package_signing_key
    if configured:
        return configured.encode("utf-8")
    if settings.app_env.strip().lower() != "production" and len(settings.jwt_secret_key) >= 16:
        return settings.jwt_secret_key.encode("utf-8")
    raise ConfigurationPackageError("Configuration-package signing key is unavailable")


def sign_manifest(manifest: dict[str, Any], settings: Settings) -> str:
    return hmac.new(
        signing_key(settings),
        canonical_json(manifest).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(manifest: dict[str, Any], signature: str, settings: Settings) -> bool:
    return hmac.compare_digest(sign_manifest(manifest, settings), signature)


def export_artifact(
    manifest: dict[str, Any],
    signature: str,
) -> dict[str, Any]:
    return {
        "artifact_format": "sbs-itsm-configuration-package",
        "artifact_version": "1.0",
        "manifest": manifest,
        "manifest_sha256": digest(manifest),
        "signature_algorithm": "HMAC-SHA256",
        "signature": signature,
    }


def validate_artifact(artifact: dict[str, Any], settings: Settings) -> dict[str, Any]:
    errors: list[str] = []
    if artifact.get("artifact_format") != "sbs-itsm-configuration-package":
        errors.append("Unsupported artifact format")
    if artifact.get("artifact_version") != "1.0":
        errors.append("Unsupported artifact version")
    manifest = artifact.get("manifest")
    if not isinstance(manifest, dict):
        errors.append("Artifact manifest must be an object")
        manifest = {}
    supplied_hash = str(artifact.get("manifest_sha256", ""))
    actual_hash = digest(manifest)
    if not hmac.compare_digest(supplied_hash, actual_hash):
        errors.append("Manifest integrity hash does not match")
    signature = str(artifact.get("signature", ""))
    if not signature or not verify_signature(manifest, signature, settings):
        errors.append("Artifact signature is invalid")
    validation = validate_manifest(manifest, settings)
    errors.extend(str(item) for item in validation["errors"])
    return {
        **validation,
        "valid": not errors,
        "errors": errors,
        "manifest_sha256": actual_hash,
        "signature_valid": bool(signature) and verify_signature(manifest, signature, settings),
    }


def _safe_json(value: str | None) -> dict[str, Any]:
    source = json_object(value)

    def scrub(item: object) -> object:
        if isinstance(item, dict):
            return {
                str(key): scrub(child)
                for key, child in item.items()
                if not _SECRET_KEY.search(str(key))
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if isinstance(item, str) and _SECRET_VALUE.search(item):
            return "[REDACTED]"
        return item

    result = scrub(source)
    return result if isinstance(result, dict) else {}


def _secret_paths(value: object, path: str = "data") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            policy_marker = key in {
                "requires_credential_binding",
                "requires_secret_binding",
                "secret_required",
            } and isinstance(child, bool)
            if _SECRET_KEY.search(key) and not policy_marker:
                hits.append(child_path)
            hits.extend(_secret_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_secret_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        hits.append(path)
    return hits


def _component_data_errors(
    component_type: str,
    key: str,
    data: dict[str, Any],
    dependencies: list[str],
) -> list[str]:
    errors: list[str] = []

    def required_string(field: str, maximum: int = 4000) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            errors.append(f"{key}: {field} must be a non-empty string")
            return ""
        return value.strip()

    def positive_integer(field: str) -> None:
        value = data.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"{key}: {field} must be a positive integer")

    for field in data:
        if field == "id" or field.endswith("_id") or field.endswith("_ids"):
            errors.append(f"{key}: database identifier field is not portable: {field}")
    if component_type.startswith("catalog_") or component_type in {
        "notification_template",
        "external_system",
        "workflow",
        "custom_field_set",
    }:
        code = required_string("code", 120)
        if code and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,119}", code):
            errors.append(f"{key}: code is invalid")
    if component_type == "catalog_category":
        required_string("name", 160)
        if not isinstance(data.get("sort_order"), int):
            errors.append(f"{key}: sort_order must be an integer")
    elif component_type == "catalog_service":
        required_string("name", 180)
        category_code = required_string("category_code", 64)
        if f"catalog_category:{category_code}" not in dependencies:
            errors.append(f"{key}: catalog category dependency is missing")
    elif component_type == "catalog_offering":
        required_string("name", 180)
        service_code = required_string("service_code", 64)
        if f"catalog_service:{service_code}" not in dependencies:
            errors.append(f"{key}: catalog service dependency is missing")
        positive_integer("expected_fulfillment_minutes")
    elif component_type == "catalog_item":
        required_string("name", 200)
        required_string("short_description", 320)
        required_string("description")
        category_code = required_string("category_code", 64)
        service_code = required_string("service_code", 64)
        expected = {
            f"catalog_category:{category_code}",
            f"catalog_service:{service_code}",
        }
        offering_code = data.get("offering_code")
        if offering_code:
            expected.add(f"catalog_offering:{offering_code}")
        if not expected.issubset(dependencies):
            errors.append(f"{key}: catalog hierarchy dependencies are incomplete")
        positive_integer("expected_delivery_minutes")
        if not isinstance(data.get("unit_cost_minor"), int):
            errors.append(f"{key}: unit_cost_minor must be an integer")
    elif component_type == "sla_calendar":
        required_string("name", 200)
        required_string("timezone", 80)
        if not isinstance(data.get("weekly_hours"), dict):
            errors.append(f"{key}: weekly_hours must be an object")
        if not isinstance(data.get("exceptions", []), list):
            errors.append(f"{key}: exceptions must be an array")
    elif component_type == "sla_policy":
        required_string("name", 200)
        required_string("priority", 32)
        positive_integer("target_response_minutes")
        positive_integer("target_resolution_minutes")
        warning = data.get("warning_percent")
        if not isinstance(warning, int) or isinstance(warning, bool) or not 1 <= warning <= 100:
            errors.append(f"{key}: warning_percent must be between 1 and 100")
        calendar_name = data.get("calendar_name")
        if calendar_name and f"sla_calendar:{calendar_name}" not in dependencies:
            errors.append(f"{key}: SLA calendar dependency is missing")
    elif component_type == "notification_template":
        required_string("name", 255)
        required_string("subject_template", 255)
        required_string("body_template", 100_000)
        required_string("locale", 20)
    elif component_type == "external_system":
        required_string("name", 255)
        required_string("system_type", 80)
        base_url = data.get("base_url")
        if base_url is not None and (
            not isinstance(base_url, str)
            or not re.fullmatch(r"https?://[^\s]+", base_url)
        ):
            errors.append(f"{key}: base_url must be an HTTP(S) URL")
        if not isinstance(data.get("safe_config", {}), dict):
            errors.append(f"{key}: safe_config must be an object")
    elif component_type == "integration_mapping":
        required_string("mapping_type", 80)
        required_string("source_entity", 120)
        required_string("target_entity", 120)
        if not isinstance(data.get("mapping"), dict):
            errors.append(f"{key}: mapping must be an object")
        system_code = data.get("system_code")
        if system_code and f"external_system:{system_code}" not in dependencies:
            errors.append(f"{key}: external-system dependency is missing")
    elif component_type == "webhook_endpoint":
        required_string("name", 255)
        path = required_string("path", 255)
        required_string("event_type", 120)
        required_string("target_system", 120)
        if path and not path.startswith("/"):
            errors.append(f"{key}: path must start with /")
        system_code = data.get("system_code")
        if system_code and f"external_system:{system_code}" not in dependencies:
            errors.append(f"{key}: external-system dependency is missing")
    elif component_type == "workflow":
        required_string("name", 200)
        required_string("trigger_type", 120)
        if data.get("concurrency_policy") not in {"ALLOW", "SERIALIZE"}:
            errors.append(f"{key}: concurrency_policy is invalid")
        maximum = data.get("max_active_executions")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 1000:
            errors.append(f"{key}: max_active_executions must be between 1 and 1000")
        definition = data.get("definition")
        if not isinstance(definition, dict):
            errors.append(f"{key}: definition must be an object")
        else:
            validation = validate_workflow_definition(definition)
            errors.extend(f"{key}: {error}" for error in validation["errors"])
            expected = {
                f"workflow:{node.get('config', {}).get('workflow_code')}"
                for node in definition.get("nodes", [])
                if isinstance(node, dict)
                and node.get("type") == "SUBFLOW"
                and isinstance(node.get("config"), dict)
                and node["config"].get("workflow_code")
            }
            if not expected.issubset(dependencies):
                errors.append(f"{key}: subflow dependencies are incomplete")
    elif component_type == "custom_field_set":
        required_string("name", 200)
        if data.get("entity_type") not in {
            "ticket",
            "asset",
            "change",
            "problem",
            "request",
        }:
            errors.append(f"{key}: entity_type is invalid")
        if not isinstance(data.get("applicability"), dict):
            errors.append(f"{key}: applicability must be an object")
        schema = data.get("schema")
        if not isinstance(schema, dict):
            errors.append(f"{key}: schema must be an object")
        else:
            validation = validate_custom_field_schema(schema)
            errors.extend(f"{key}: {error}" for error in validation["errors"])
    return errors


def _component(
    component_type: str,
    key: str,
    data: dict[str, Any],
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    dependencies = sorted(set(dependencies or []))
    return {
        "type": component_type,
        "key": key,
        "data": data,
        "dependencies": dependencies,
        "content_sha256": digest(data),
    }


def _published_workflow_version(db: Session, item: WorkflowDefinition) -> WorkflowVersion | None:
    if item.published_version_number is None:
        return None
    return db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == item.id,
            WorkflowVersion.version_number == item.published_version_number,
            WorkflowVersion.status == "PUBLISHED",
        )
    )


def _published_field_version(
    db: Session,
    item: CustomFieldSet,
) -> CustomFieldSetVersion | None:
    if item.published_version_number is None:
        return None
    return db.scalar(
        select(CustomFieldSetVersion).where(
            CustomFieldSetVersion.field_set_id == item.id,
            CustomFieldSetVersion.version_number == item.published_version_number,
            CustomFieldSetVersion.status == "PUBLISHED",
        )
    )


def collect_manifest(
    db: Session,
    *,
    tenant_id: str,
    package_code: str,
    package_name: str,
    version_number: int,
    source_environment: str,
    component_types: set[str],
) -> dict[str, Any]:
    unsupported = component_types - set(SUPPORTED_COMPONENT_TYPES)
    if unsupported:
        raise ConfigurationPackageError(
            "Unsupported component types: " + ", ".join(sorted(unsupported))
        )
    component_types = set(component_types)
    if "catalog_item" in component_types:
        component_types.update(
            {"catalog_category", "catalog_service", "catalog_offering"}
        )
    if "catalog_offering" in component_types:
        component_types.update({"catalog_category", "catalog_service"})
    if "catalog_service" in component_types:
        component_types.add("catalog_category")
    if "sla_policy" in component_types:
        component_types.add("sla_calendar")
    if {"integration_mapping", "webhook_endpoint"} & component_types:
        component_types.add("external_system")
    components: list[dict[str, Any]] = []
    if "catalog_category" in component_types:
        for item in db.scalars(
            select(ServiceCategory).where(ServiceCategory.tenant_id == tenant_id)
        ).all():
            components.append(
                _component(
                    "catalog_category",
                    f"catalog_category:{item.code}",
                    {
                        "code": item.code,
                        "name": item.name,
                        "description": item.description,
                        "status": item.status,
                        "sort_order": item.sort_order,
                    },
                )
            )
    if "catalog_service" in component_types:
        categories = {
            item.id: item.code
            for item in db.scalars(
                select(ServiceCategory).where(ServiceCategory.tenant_id == tenant_id)
            ).all()
        }
        for item in db.scalars(
            select(CatalogService).where(CatalogService.tenant_id == tenant_id)
        ).all():
            category_code = categories.get(item.category_id)
            if category_code:
                dependency = f"catalog_category:{category_code}"
                components.append(
                    _component(
                        "catalog_service",
                        f"catalog_service:{item.code}",
                        {
                            "code": item.code,
                            "category_code": category_code,
                            "name": item.name,
                            "description": item.description,
                            "support_group": item.support_group,
                            "status": item.status,
                        },
                        [dependency],
                    )
                )
    if "catalog_offering" in component_types:
        services = {
            item.id: item.code
            for item in db.scalars(
                select(CatalogService).where(CatalogService.tenant_id == tenant_id)
            ).all()
        }
        for item in db.scalars(
            select(ServiceOffering).where(ServiceOffering.tenant_id == tenant_id)
        ).all():
            service_code = services.get(item.service_id)
            if service_code:
                components.append(
                    _component(
                        "catalog_offering",
                        f"catalog_offering:{item.code}",
                        {
                            "code": item.code,
                            "service_code": service_code,
                            "name": item.name,
                            "description": item.description,
                            "support_group": item.support_group,
                            "expected_fulfillment_minutes": item.expected_fulfillment_minutes,
                            "status": item.status,
                        },
                        [f"catalog_service:{service_code}"],
                    )
                )
    if "catalog_item" in component_types:
        categories = {
            item.id: item.code
            for item in db.scalars(
                select(ServiceCategory).where(ServiceCategory.tenant_id == tenant_id)
            ).all()
        }
        services = {
            item.id: item.code
            for item in db.scalars(
                select(CatalogService).where(CatalogService.tenant_id == tenant_id)
            ).all()
        }
        offerings = {
            item.id: item.code
            for item in db.scalars(
                select(ServiceOffering).where(ServiceOffering.tenant_id == tenant_id)
            ).all()
        }
        for item in db.scalars(
            select(CatalogItem).where(CatalogItem.tenant_id == tenant_id)
        ).all():
            category_code = categories.get(item.category_id)
            service_code = services.get(item.service_id)
            offering_code = offerings.get(item.offering_id) if item.offering_id else None
            if not category_code or not service_code:
                continue
            dependencies = [
                f"catalog_category:{category_code}",
                f"catalog_service:{service_code}",
            ]
            if offering_code:
                dependencies.append(f"catalog_offering:{offering_code}")
            components.append(
                _component(
                    "catalog_item",
                    f"catalog_item:{item.code}",
                    {
                        "code": item.code,
                        "category_code": category_code,
                        "service_code": service_code,
                        "offering_code": offering_code,
                        "name": item.name,
                        "short_description": item.short_description,
                        "description": item.description,
                        "lifecycle_status": item.lifecycle_status,
                        "support_group": item.support_group,
                        "expected_delivery_minutes": item.expected_delivery_minutes,
                        "approval_required": item.approval_required,
                        "entitlement_rules": json_object(item.entitlement_rules_json),
                        "unit_cost_minor": item.unit_cost_minor,
                        "currency": item.currency,
                        "cost_type": item.cost_type,
                        "risk_level": item.risk_level,
                        "approval_policy": json_object(item.approval_policy_json),
                        "sla_policy": json_object(item.sla_policy_json),
                    },
                    dependencies,
                )
            )
    if "sla_calendar" in component_types:
        for item in db.scalars(
            select(SlaBusinessCalendar).where(SlaBusinessCalendar.tenant_id == tenant_id)
        ).all():
            exceptions = db.scalars(
                select(SlaCalendarException).where(
                    SlaCalendarException.calendar_id == item.id
                )
            ).all()
            components.append(
                _component(
                    "sla_calendar",
                    f"sla_calendar:{item.name}",
                    {
                        "name": item.name,
                        "description": item.description,
                        "timezone": item.timezone,
                        "weekly_hours": item.weekly_hours_json,
                        "is_default": item.is_default,
                        "is_active": item.is_active,
                        "exceptions": [
                            {
                                "date": str(exception.exception_date),
                                "kind": exception.kind,
                                "name": exception.name,
                                "intervals": exception.intervals_json,
                            }
                            for exception in exceptions
                        ],
                    },
                )
            )
    if "sla_policy" in component_types:
        calendars = {
            item.id: item.name
            for item in db.scalars(
                select(SlaBusinessCalendar).where(SlaBusinessCalendar.tenant_id == tenant_id)
            ).all()
        }
        for item in db.scalars(
            select(SlaPolicy).where(SlaPolicy.tenant_id == tenant_id)
        ).all():
            calendar_name = calendars.get(item.calendar_id) if item.calendar_id else None
            dependencies = [f"sla_calendar:{calendar_name}"] if calendar_name else []
            components.append(
                _component(
                    "sla_policy",
                    f"sla_policy:{item.name}:{item.priority}",
                    {
                        "name": item.name,
                        "priority": item.priority,
                        "target_response_minutes": item.target_response_minutes,
                        "target_resolution_minutes": item.target_resolution_minutes,
                        "is_active": item.is_active,
                        "status": item.status,
                        "description": item.description,
                        "calendar_name": calendar_name,
                        "priority_order": item.priority_order,
                        "scope": item.scope_json,
                        "targets": item.targets_json,
                        "pause_statuses": item.pause_statuses_json,
                        "pause_reasons": item.pause_reasons_json,
                        "warning_percent": item.warning_percent,
                        "escalations": item.escalations_json,
                    },
                    dependencies,
                )
            )
    if "notification_template" in component_types:
        for item in db.scalars(
            select(NotificationTemplate).where(NotificationTemplate.tenant_id == tenant_id)
        ).all():
            components.append(
                _component(
                    "notification_template",
                    f"notification_template:{item.code}",
                    {
                        "code": item.code,
                        "key": item.key,
                        "event_type": item.event_type,
                        "locale": item.locale,
                        "channel": item.channel,
                        "name": item.name,
                        "subject_template": item.subject_template,
                        "body_template": item.body_template,
                        "is_active": item.is_active,
                    },
                )
            )
    if "external_system" in component_types:
        for item in db.scalars(
            select(ExternalSystem).where(ExternalSystem.tenant_id == tenant_id)
        ).all():
            components.append(
                _component(
                    "external_system",
                    f"external_system:{item.code}",
                    {
                        "code": item.code,
                        "name": item.name,
                        "system_type": item.system_type,
                        "base_url": item.base_url,
                        "description": item.description,
                        "safe_config": _safe_json(item.config_json),
                        "requires_credential_binding": True,
                    },
                )
            )
    if "integration_mapping" in component_types or "webhook_endpoint" in component_types:
        systems = {
            item.id: item.code
            for item in db.scalars(
                select(ExternalSystem).where(ExternalSystem.tenant_id == tenant_id)
            ).all()
        }
        if "integration_mapping" in component_types:
            for item in db.scalars(
                select(IntegrationMapping).where(IntegrationMapping.tenant_id == tenant_id)
            ).all():
                system_code = systems.get(item.external_system_id) if item.external_system_id else None
                key = (
                    f"integration_mapping:{system_code or 'none'}:"
                    f"{item.source_entity}:{item.target_entity}:{item.mapping_type}"
                )
                dependencies = [f"external_system:{system_code}"] if system_code else []
                components.append(
                    _component(
                        "integration_mapping",
                        key,
                        {
                            "system_code": system_code,
                            "mapping_type": item.mapping_type,
                            "source_field": item.source_field,
                            "target_field": item.target_field,
                            "transform_rule": item.transform_rule,
                            "is_required": item.is_required,
                            "source_entity": item.source_entity,
                            "target_entity": item.target_entity,
                            "mapping": json_object(item.mapping_json),
                        },
                        dependencies,
                    )
                )
        if "webhook_endpoint" in component_types:
            for item in db.scalars(
                select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id)
            ).all():
                system_code = systems.get(item.external_system_id) if item.external_system_id else None
                key = f"webhook_endpoint:{system_code or 'none'}:{item.path}:{item.event_type}"
                dependencies = [f"external_system:{system_code}"] if system_code else []
                components.append(
                    _component(
                        "webhook_endpoint",
                        key,
                        {
                            "system_code": system_code,
                            "name": item.name,
                            "path": item.path,
                            "event_type": item.event_type,
                            "target_system": item.target_system,
                            "secret_required": item.secret_required,
                            "requires_secret_binding": item.secret_required,
                        },
                        dependencies,
                    )
                )
    if "workflow" in component_types:
        for item in db.scalars(
            select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == tenant_id)
        ).all():
            version = _published_workflow_version(db, item)
            if version is None:
                continue
            definition = json_object(version.definition_json)
            dependencies = sorted(
                {
                    f"workflow:{node.get('config', {}).get('workflow_code')}"
                    for node in definition.get("nodes", [])
                    if isinstance(node, dict)
                    and node.get("type") == "SUBFLOW"
                    and isinstance(node.get("config"), dict)
                    and node["config"].get("workflow_code")
                }
            )
            components.append(
                _component(
                    "workflow",
                    f"workflow:{item.code}",
                    {
                        "code": item.code,
                        "name": item.name,
                        "description": item.description,
                        "status": item.status,
                        "trigger_type": item.trigger_type,
                        "concurrency_policy": item.concurrency_policy,
                        "max_active_executions": item.max_active_executions,
                        "publish_approval_required": item.publish_approval_required,
                        "definition": definition,
                    },
                    dependencies,
                )
            )
    if "custom_field_set" in component_types:
        for item in db.scalars(
            select(CustomFieldSet).where(CustomFieldSet.tenant_id == tenant_id)
        ).all():
            version = _published_field_version(db, item)
            if version is None:
                continue
            components.append(
                _component(
                    "custom_field_set",
                    f"custom_field_set:{item.code}",
                    {
                        "code": item.code,
                        "name": item.name,
                        "description": item.description,
                        "entity_type": item.entity_type,
                        "status": item.status,
                        "applicability": json_object(item.applicability_json),
                        "schema": json_object(version.schema_json),
                    },
                )
            )
    components.sort(key=lambda item: (_APPLY_ORDER[str(item["type"])], str(item["key"])))
    return {
        "schema_version": "1.0",
        "package": {
            "code": package_code,
            "name": package_name,
            "version": version_number,
            "source_environment": source_environment,
            "created_at": utcnow().isoformat(),
        },
        "components": components,
    }


def validate_manifest(manifest: dict[str, Any], settings: Settings) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    package = manifest.get("package")
    if not isinstance(package, dict):
        errors.append("package metadata must be an object")
        package = {}
    code = str(package.get("code", ""))
    if not _CODE_PATTERN.fullmatch(code):
        errors.append("package.code is invalid")
    if not str(package.get("name", "")).strip():
        errors.append("package.name is required")
    source_environment = str(package.get("source_environment", ""))
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,79}", source_environment):
        errors.append("package.source_environment is invalid")
    version = package.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("package.version must be a positive integer")
    components = manifest.get("components")
    if not isinstance(components, list):
        errors.append("components must be an array")
        components = []
    if len(components) > settings.configuration_package_max_components:
        errors.append("Component count exceeds configured limit")
    encoded = canonical_json(manifest).encode("utf-8")
    if len(encoded) > settings.configuration_package_max_bytes:
        errors.append("Manifest size exceeds configured limit")
    keys: set[str] = set()
    dependencies: set[str] = set()
    type_counts: dict[str, int] = {}
    for index, item in enumerate(components):
        if not isinstance(item, dict):
            errors.append(f"components[{index}] must be an object")
            continue
        component_type = str(item.get("type", ""))
        key = str(item.get("key", ""))
        data = item.get("data")
        if component_type not in SUPPORTED_COMPONENT_TYPES:
            errors.append(f"components[{index}].type is unsupported")
        if not key.startswith(component_type + ":"):
            errors.append(f"components[{index}].key does not match its type")
        if len(key) > 500 or re.search(r"\s", key):
            errors.append(f"components[{index}].key is invalid")
        if key in keys:
            errors.append(f"Duplicate component key: {key}")
        keys.add(key)
        type_counts[component_type] = type_counts.get(component_type, 0) + 1
        if not isinstance(data, dict):
            errors.append(f"components[{index}].data must be an object")
            data = {}
        if item.get("content_sha256") != digest(data):
            errors.append(f"Component hash does not match: {key}")
        secret_paths = _secret_paths(data)
        if secret_paths:
            errors.append(f"Sensitive configuration keys are forbidden in {key}: {', '.join(secret_paths)}")
        raw_dependencies = item.get("dependencies", [])
        if not isinstance(raw_dependencies, list) or not all(
            isinstance(value, str) for value in raw_dependencies
        ):
            errors.append(f"components[{index}].dependencies must contain strings")
        else:
            dependencies.update(raw_dependencies)
            errors.extend(
                _component_data_errors(
                    component_type,
                    key,
                    data,
                    raw_dependencies,
                )
            )
    missing_dependencies = sorted(dependencies - keys)
    if missing_dependencies:
        errors.append(
            "Package dependencies are missing: " + ", ".join(missing_dependencies)
        )
    if not components:
        warnings.append("Package contains no configuration components")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "component_count": len(components),
        "dependency_count": len(dependencies),
        "type_counts": type_counts,
        "size_bytes": len(encoded),
    }


def _select_by_code(db: Session, model: type[Any], tenant_id: str, code: str) -> Any | None:
    return db.scalar(select(model).where(model.tenant_id == tenant_id, model.code == code))


def build_deployment_plan(
    db: Session,
    *,
    tenant_id: str,
    manifest: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    validation = validate_manifest(manifest, settings)
    operations: list[dict[str, Any]] = []
    if validation["valid"]:
        component_types = {
            str(component["type"])
            for component in manifest["components"]
            if isinstance(component, dict)
        }
        current_manifest = collect_manifest(
            db,
            tenant_id=tenant_id,
            package_code="snapshot.package",
            package_name="snapshot",
            version_number=1,
            source_environment="snapshot",
            component_types=component_types,
        )
        current_by_key = {
            str(component["key"]): component
            for component in current_manifest["components"]
        }
        for component in manifest["components"]:
            current = current_by_key.get(str(component["key"]))
            if current is None:
                action = "CREATE"
            elif current["content_sha256"] == component["content_sha256"]:
                action = "NOOP"
            else:
                action = "UPDATE"
            operations.append(
                {
                    "component_type": component["type"],
                    "component_key": component["key"],
                    "action": action,
                    "current_sha256": current["content_sha256"] if current else None,
                    "desired_sha256": component["content_sha256"],
                    "before": current,
                }
            )
    fingerprint = digest(
        [
            {
                "key": operation["component_key"],
                "sha256": operation["current_sha256"],
            }
            for operation in operations
        ]
    )
    summary = {
        action: sum(operation["action"] == action for operation in operations)
        for action in ("CREATE", "UPDATE", "NOOP", "BLOCK")
    }
    return {
        "valid": validation["valid"],
        "validation": validation,
        "operations": operations,
        "summary": summary,
        "target_fingerprint_sha256": fingerprint,
    }


def _require_dependency(
    db: Session,
    model: type[Any],
    tenant_id: str,
    code_or_name: str,
    label: str,
) -> Any:
    field = model.name if model is SlaBusinessCalendar else model.code
    item = db.scalar(select(model).where(model.tenant_id == tenant_id, field == code_or_name))
    if item is None:
        raise ConfigurationPackageError(f"Required {label} is unavailable: {code_or_name}")
    return item


def _upsert_component(
    db: Session,
    *,
    tenant_id: str,
    component: dict[str, Any],
    actor_id: str,
) -> str:
    component_type = str(component["type"])
    data: dict[str, Any] = component["data"]
    now = utcnow()
    if component_type == "catalog_category":
        item = _select_by_code(db, ServiceCategory, tenant_id, data["code"])
        if item is None:
            item = ServiceCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"])
            db.add(item)
        for field in ("name", "description", "status", "sort_order"):
            setattr(item, field, data.get(field))
    elif component_type == "catalog_service":
        category = _require_dependency(
            db, ServiceCategory, tenant_id, data["category_code"], "catalog category"
        )
        item = _select_by_code(db, CatalogService, tenant_id, data["code"])
        if item is None:
            item = CatalogService(id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"])
            db.add(item)
        item.category_id = category.id
        for field in ("name", "description", "support_group", "status"):
            setattr(item, field, data.get(field))
    elif component_type == "catalog_offering":
        service = _require_dependency(
            db, CatalogService, tenant_id, data["service_code"], "catalog service"
        )
        item = _select_by_code(db, ServiceOffering, tenant_id, data["code"])
        if item is None:
            item = ServiceOffering(id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"])
            db.add(item)
        item.service_id = service.id
        for field in (
            "name",
            "description",
            "support_group",
            "expected_fulfillment_minutes",
            "status",
        ):
            setattr(item, field, data.get(field))
    elif component_type == "catalog_item":
        category = _require_dependency(
            db, ServiceCategory, tenant_id, data["category_code"], "catalog category"
        )
        service = _require_dependency(
            db, CatalogService, tenant_id, data["service_code"], "catalog service"
        )
        offering = (
            _require_dependency(
                db, ServiceOffering, tenant_id, data["offering_code"], "catalog offering"
            )
            if data.get("offering_code")
            else None
        )
        item = _select_by_code(db, CatalogItem, tenant_id, data["code"])
        if item is None:
            item = CatalogItem(id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"])
            db.add(item)
        item.category_id = category.id
        item.service_id = service.id
        item.offering_id = offering.id if offering else None
        for field in (
            "name",
            "short_description",
            "description",
            "lifecycle_status",
            "support_group",
            "expected_delivery_minutes",
            "approval_required",
            "unit_cost_minor",
            "currency",
            "cost_type",
            "risk_level",
        ):
            setattr(item, field, data.get(field))
        item.entitlement_rules_json = canonical_json(data.get("entitlement_rules", {}))
        item.approval_policy_json = canonical_json(data.get("approval_policy", {}))
        item.sla_policy_json = canonical_json(data.get("sla_policy", {}))
        item.updated_by_id = actor_id
    elif component_type == "sla_calendar":
        item = db.scalar(
            select(SlaBusinessCalendar).where(
                SlaBusinessCalendar.tenant_id == tenant_id,
                SlaBusinessCalendar.name == data["name"],
            )
        )
        if item is None:
            item = SlaBusinessCalendar(id=str(uuid.uuid4()), tenant_id=tenant_id, name=data["name"])
            db.add(item)
            db.flush()
        for field in ("description", "timezone", "is_default", "is_active"):
            setattr(item, field, data.get(field))
        item.weekly_hours_json = data.get("weekly_hours", {})
        item.version = (item.version or 0) + 1
        if item.is_default:
            for other in db.scalars(
                select(SlaBusinessCalendar).where(
                    SlaBusinessCalendar.tenant_id == tenant_id,
                    SlaBusinessCalendar.id != item.id,
                    SlaBusinessCalendar.is_default.is_(True),
                )
            ).all():
                other.is_default = False
        existing = {
            str(exception.exception_date): exception
            for exception in db.scalars(
                select(SlaCalendarException).where(SlaCalendarException.calendar_id == item.id)
            ).all()
        }
        from datetime import date

        desired_dates: set[str] = set()
        for raw in data.get("exceptions", []):
            raw_date = str(raw["date"])
            desired_dates.add(raw_date)
            exception = existing.get(raw_date)
            if exception is None:
                exception = SlaCalendarException(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    calendar_id=item.id,
                    exception_date=date.fromisoformat(raw_date),
                    created_by_id=actor_id,
                )
                db.add(exception)
            exception.kind = raw["kind"]
            exception.name = raw["name"]
            exception.intervals_json = raw.get("intervals", [])
        for raw_date, exception in existing.items():
            if raw_date not in desired_dates:
                db.delete(exception)
    elif component_type == "sla_policy":
        item = db.scalar(
            select(SlaPolicy).where(
                SlaPolicy.tenant_id == tenant_id,
                SlaPolicy.name == data["name"],
                SlaPolicy.priority == data["priority"],
            )
        )
        if item is None:
            item = SlaPolicy(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=data["name"],
                priority=data["priority"],
            )
            db.add(item)
        calendar = (
            _require_dependency(
                db, SlaBusinessCalendar, tenant_id, data["calendar_name"], "SLA calendar"
            )
            if data.get("calendar_name")
            else None
        )
        item.calendar_id = calendar.id if calendar else None
        for field in (
            "target_response_minutes",
            "target_resolution_minutes",
            "is_active",
            "status",
            "description",
            "priority_order",
            "warning_percent",
        ):
            setattr(item, field, data.get(field))
        item.response_minutes = data["target_response_minutes"]
        item.resolution_minutes = data["target_resolution_minutes"]
        item.scope_json = data.get("scope", {})
        item.targets_json = data.get("targets", [])
        item.pause_statuses_json = data.get("pause_statuses", [])
        item.pause_reasons_json = data.get("pause_reasons", [])
        item.escalations_json = data.get("escalations", [])
        item.version = (item.version or 0) + 1
    elif component_type == "notification_template":
        item = db.scalar(select(NotificationTemplate).where(NotificationTemplate.code == data["code"]))
        if item is not None and item.tenant_id != tenant_id:
            raise ConfigurationPackageError(
                f"Notification code belongs to another tenant: {data['code']}"
            )
        if item is None:
            item = NotificationTemplate(
                id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"]
            )
            db.add(item)
        for field in (
            "key",
            "event_type",
            "locale",
            "channel",
            "name",
            "subject_template",
            "body_template",
            "is_active",
        ):
            setattr(item, field, data.get(field))
    elif component_type == "external_system":
        item = db.scalar(select(ExternalSystem).where(ExternalSystem.code == data["code"]))
        if item is not None and item.tenant_id != tenant_id:
            raise ConfigurationPackageError(
                f"External-system code belongs to another tenant: {data['code']}"
            )
        if item is None:
            item = ExternalSystem(id=str(uuid.uuid4()), tenant_id=tenant_id, code=data["code"])
            db.add(item)
        item.name = data["name"]
        item.system_type = data["system_type"]
        item.base_url = data.get("base_url")
        item.description = data.get("description")
        item.config_json = canonical_json(data.get("safe_config", {}))
        item.is_enabled = False
        item.is_mock = False
        item.status = "requires_binding"
        item.health_status = "unknown"
        item.created_by_id = item.created_by_id or actor_id
    elif component_type == "integration_mapping":
        system = (
            _require_dependency(
                db, ExternalSystem, tenant_id, data["system_code"], "external system"
            )
            if data.get("system_code")
            else None
        )
        item = db.scalar(
            select(IntegrationMapping).where(
                IntegrationMapping.tenant_id == tenant_id,
                IntegrationMapping.external_system_id == (system.id if system else None),
                IntegrationMapping.source_entity == data["source_entity"],
                IntegrationMapping.target_entity == data["target_entity"],
                IntegrationMapping.mapping_type == data["mapping_type"],
            )
        )
        if item is None:
            item = IntegrationMapping(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                external_system_id=system.id if system else None,
                source_entity=data["source_entity"],
                target_entity=data["target_entity"],
                mapping_type=data["mapping_type"],
            )
            db.add(item)
        for field in ("source_field", "target_field", "transform_rule", "is_required"):
            setattr(item, field, data.get(field))
        item.mapping_json = canonical_json(data.get("mapping", {}))
        item.is_active = False
    elif component_type == "webhook_endpoint":
        system = (
            _require_dependency(
                db, ExternalSystem, tenant_id, data["system_code"], "external system"
            )
            if data.get("system_code")
            else None
        )
        item = db.scalar(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.external_system_id == (system.id if system else None),
                WebhookEndpoint.path == data["path"],
                WebhookEndpoint.event_type == data["event_type"],
            )
        )
        if item is None:
            item = WebhookEndpoint(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                external_system_id=system.id if system else None,
                path=data["path"],
                event_type=data["event_type"],
            )
            db.add(item)
        item.name = data["name"]
        item.target_system = data["target_system"]
        item.secret_required = data.get("secret_required", False)
        item.secret_ref = None
        item.is_active = False
    elif component_type == "workflow":
        validation = validate_workflow_definition(data["definition"])
        if not validation["valid"]:
            raise ConfigurationPackageError(f"Workflow is invalid: {component['key']}")
        item = _select_by_code(db, WorkflowDefinition, tenant_id, data["code"])
        if item is None:
            item = WorkflowDefinition(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                code=data["code"],
                latest_version_number=0,
            )
            db.add(item)
        elif item.draft_version_number is not None:
            raise ConfigurationPackageError(
                f"Workflow has an unresolved local draft: {data['code']}"
            )
        for field in (
            "name",
            "description",
            "status",
            "trigger_type",
            "concurrency_policy",
            "max_active_executions",
            "publish_approval_required",
        ):
            setattr(item, field, data.get(field))
        if item.published_version_number:
            previous = db.scalar(
                select(WorkflowVersion).where(
                    WorkflowVersion.workflow_id == item.id,
                    WorkflowVersion.version_number == item.published_version_number,
                )
            )
            if previous:
                previous.status = "RETIRED"
        number = item.latest_version_number + 1
        version = WorkflowVersion(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workflow_id=item.id,
            version_number=number,
            status="PUBLISHED",
            definition_json=canonical_json(data["definition"]),
            definition_sha256=digest(data["definition"]),
            validation_status="VALID",
            validation_json=canonical_json(validation),
            revision=1,
            based_on_version_number=item.published_version_number,
            change_summary="Configuration package promotion",
            review_status="APPROVED",
            reviewed_by_id=actor_id,
            published_by_id=actor_id,
            reviewed_at=now,
            published_at=now,
            created_by_id=actor_id,
            updated_by_id=actor_id,
        )
        db.add(version)
        item.latest_version_number = number
        item.published_version_number = number
        item.updated_by_id = actor_id
        item.revision += 1
    elif component_type == "custom_field_set":
        validation = validate_custom_field_schema(data["schema"])
        if not validation["valid"]:
            raise ConfigurationPackageError(f"Custom-field schema is invalid: {component['key']}")
        item = _select_by_code(db, CustomFieldSet, tenant_id, data["code"])
        if item is None:
            item = CustomFieldSet(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                code=data["code"],
                latest_version_number=0,
            )
            db.add(item)
        elif item.draft_version_number is not None:
            raise ConfigurationPackageError(
                f"Custom-field set has an unresolved local draft: {data['code']}"
            )
        for field in ("name", "description", "entity_type", "status"):
            setattr(item, field, data.get(field))
        item.applicability_json = canonical_json(data.get("applicability", {}))
        if item.published_version_number:
            previous = db.scalar(
                select(CustomFieldSetVersion).where(
                    CustomFieldSetVersion.field_set_id == item.id,
                    CustomFieldSetVersion.version_number == item.published_version_number,
                )
            )
            if previous:
                previous.status = "RETIRED"
        number = item.latest_version_number + 1
        version = CustomFieldSetVersion(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            field_set_id=item.id,
            version_number=number,
            status="PUBLISHED",
            schema_json=canonical_json(data["schema"]),
            schema_sha256=schema_hash(data["schema"]),
            validation_status="VALID",
            validation_json=canonical_json(validation),
            revision=1,
            based_on_version_number=item.published_version_number,
            change_summary="Configuration package promotion",
            breaking_change=False,
            created_by_id=actor_id,
            updated_by_id=actor_id,
            published_by_id=actor_id,
            published_at=now,
        )
        db.add(version)
        item.latest_version_number = number
        item.published_version_number = number
        item.updated_by_id = actor_id
        item.revision += 1
    else:
        raise ConfigurationPackageError(f"Unsupported component type: {component_type}")
    db.flush()
    return component["key"]


def _disable_new_component(
    db: Session,
    *,
    tenant_id: str,
    component: dict[str, Any],
) -> None:
    component_type = str(component["type"])
    data = component["data"]
    if component_type == "workflow":
        item = _select_by_code(db, WorkflowDefinition, tenant_id, data["code"])
        if item:
            item.status = "ARCHIVED"
    elif component_type == "custom_field_set":
        item = _select_by_code(db, CustomFieldSet, tenant_id, data["code"])
        if item:
            item.status = "ARCHIVED"
    elif component_type == "catalog_item":
        item = _select_by_code(db, CatalogItem, tenant_id, data["code"])
        if item:
            item.lifecycle_status = "RETIRED"
    elif component_type in {"catalog_category", "catalog_service", "catalog_offering"}:
        model = {
            "catalog_category": ServiceCategory,
            "catalog_service": CatalogService,
            "catalog_offering": ServiceOffering,
        }[component_type]
        item = _select_by_code(db, model, tenant_id, data["code"])
        if item:
            item.status = "INACTIVE"
    elif component_type == "sla_calendar":
        item = db.scalar(
            select(SlaBusinessCalendar).where(
                SlaBusinessCalendar.tenant_id == tenant_id,
                SlaBusinessCalendar.name == data["name"],
            )
        )
        if item:
            item.is_active = False
            item.is_default = False
    elif component_type == "sla_policy":
        item = db.scalar(
            select(SlaPolicy).where(
                SlaPolicy.tenant_id == tenant_id,
                SlaPolicy.name == data["name"],
                SlaPolicy.priority == data["priority"],
            )
        )
        if item:
            item.is_active = False
            item.status = "inactive"
    elif component_type == "notification_template":
        item = db.scalar(select(NotificationTemplate).where(NotificationTemplate.code == data["code"]))
        if item and item.tenant_id == tenant_id:
            item.is_active = False
    elif component_type == "external_system":
        item = db.scalar(select(ExternalSystem).where(ExternalSystem.code == data["code"]))
        if item and item.tenant_id == tenant_id:
            item.is_enabled = False
            item.status = "retired"
    elif component_type == "integration_mapping":
        system = (
            _select_by_code(db, ExternalSystem, tenant_id, data["system_code"])
            if data.get("system_code")
            else None
        )
        item = db.scalar(
            select(IntegrationMapping).where(
                IntegrationMapping.tenant_id == tenant_id,
                IntegrationMapping.external_system_id == (system.id if system else None),
                IntegrationMapping.source_entity == data["source_entity"],
                IntegrationMapping.target_entity == data["target_entity"],
                IntegrationMapping.mapping_type == data["mapping_type"],
            )
        )
        if item:
            item.is_active = False
    elif component_type == "webhook_endpoint":
        system = (
            _select_by_code(db, ExternalSystem, tenant_id, data["system_code"])
            if data.get("system_code")
            else None
        )
        item = db.scalar(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.external_system_id == (system.id if system else None),
                WebhookEndpoint.path == data["path"],
                WebhookEndpoint.event_type == data["event_type"],
            )
        )
        if item:
            item.is_active = False


def apply_deployment(
    db: Session,
    *,
    deployment: ConfigurationDeployment,
    manifest: dict[str, Any],
    actor_id: str,
    settings: Settings,
) -> dict[str, Any]:
    current_plan = build_deployment_plan(
        db,
        tenant_id=deployment.tenant_id,
        manifest=manifest,
        settings=settings,
    )
    if not current_plan["valid"]:
        raise ConfigurationPackageError("Package is no longer valid")
    if current_plan["target_fingerprint_sha256"] != deployment.target_fingerprint_sha256:
        raise ConfigurationPackageError(
            "Target configuration drifted after validation; create a new deployment plan"
        )
    snapshot = {
        "schema_version": "1.0",
        "deployment_id": deployment.id,
        "captured_at": utcnow().isoformat(),
        "components": [
            {
                "desired": component,
                "before": operation["before"],
            }
            for component, operation in zip(
                manifest["components"],
                current_plan["operations"],
                strict=True,
            )
            if operation["action"] != "NOOP"
        ],
    }
    results: list[dict[str, str]] = []
    for component, operation in zip(
        manifest["components"],
        current_plan["operations"],
        strict=True,
    ):
        if operation["action"] == "NOOP":
            results.append({"key": component["key"], "result": "NOOP"})
            continue
        _upsert_component(db, tenant_id=deployment.tenant_id, component=component, actor_id=actor_id)
        results.append({"key": component["key"], "result": operation["action"]})
    return {
        "snapshot": snapshot,
        "result": {
            "applied_at": utcnow().isoformat(),
            "operations": results,
            "counts": current_plan["summary"],
        },
    }


def rollback_deployment(
    db: Session,
    *,
    deployment: ConfigurationDeployment,
    actor_id: str,
) -> dict[str, Any]:
    snapshot = json_object(deployment.snapshot_before_json)
    components = snapshot.get("components", [])
    if not isinstance(components, list):
        raise ConfigurationPackageError("Deployment rollback snapshot is invalid")
    restored: list[dict[str, str]] = []
    for entry in reversed(components):
        desired = entry.get("desired")
        before = entry.get("before")
        if not isinstance(desired, dict):
            raise ConfigurationPackageError("Deployment rollback snapshot is incomplete")
        if isinstance(before, dict):
            _upsert_component(db, tenant_id=deployment.tenant_id, component=before, actor_id=actor_id)
            restored.append({"key": str(desired["key"]), "result": "RESTORED"})
        else:
            _disable_new_component(db, tenant_id=deployment.tenant_id, component=desired)
            restored.append({"key": str(desired["key"]), "result": "SAFELY_DISABLED"})
    return {
        "rolled_back_at": utcnow().isoformat(),
        "operations": restored,
    }
