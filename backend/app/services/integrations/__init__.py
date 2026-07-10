from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.external_system import ExternalSystem
from app.models.import_job import ImportJob
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_mapping import IntegrationMapping
from app.models.user import User
from app.models.webhook_endpoint import WebhookEndpoint
from app.services.audit import log_audit
from app.services.notifications import create_domain_event_notification
from app.services.integrations.providers import (
    BaseIntegrationProvider,
    MockFileImportProvider,
    MockLDAPProvider,
    MockMoodleProvider,
    MockOneCProvider,
    MockPlatonusProvider,
    MockTelegramProvider,
    MockWebhookProvider,
    MockZimbraProvider,
    create_integration_event,
    get_provider,
    list_provider_descriptors,
    list_provider_metadata,
    should_simulate_failure,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _now() -> datetime:
    return datetime.now(UTC)


def _user_email(current_user: User | None) -> str:
    if current_user is None:
        return "integration-engine@sbs.local"
    return current_user.email


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _trigger_automation(
    db: Session,
    tenant_id: str | None,
    trigger_type: str,
    context: dict[str, Any],
    actor_email: str,
) -> None:
    from app.services.automation import trigger_automation_event

    trigger_automation_event(
        db,
        tenant_id=tenant_id,
        trigger_type=trigger_type,
        context=context,
        actor_email=actor_email,
    )


def _find_system(db: Session, system_id: str) -> ExternalSystem:
    system = db.get(ExternalSystem, system_id)
    if system is None:
        raise ValueError("Integration system not found")
    return system


def check_system_health(db: Session, system_id: str, current_user: User | None = None) -> dict[str, Any]:
    system = _find_system(db, system_id)
    provider = get_provider(system.system_type)
    config = _parse_json(system.config_json)
    failed = should_simulate_failure(config, "health_check")
    now = _now()
    if failed:
        result = {"status": "down", "message": "Mock health check failure simulated."}
        system.health_status = "down"
        system.status = "error"
        system.last_error_at = now
        system.last_error_message = str(result["message"])
    else:
        result = provider.health_check()
        raw_status = str(result.get("status", "unknown"))
        system.health_status = "healthy" if raw_status in {"ok", "healthy", "accepted"} else raw_status
        system.status = "active" if system.is_enabled else system.status
        system.last_success_at = now
        system.last_error_message = None
    system.last_health_check_at = now
    system.last_health_status = system.health_status
    system.last_health_checked_at = now
    event = create_event_log(
        db,
        direction="outbound",
        event_type="integration_health_check",
        payload={"system_id": system.id, "system_type": system.system_type},
        external_system_id=system.id,
        status="failed" if failed else "success",
        response_payload=result,
        error_message=system.last_error_message,
    )
    log_audit(
        db,
        action="integration_health_checked",
        entity_type="external_system",
        entity_id=system.id,
        actor_user=current_user,
        actor_email=_user_email(current_user),
        tenant_id=system.tenant_id,
        metadata={"status": system.health_status, "event_id": event.id},
    )
    if system.health_status in {"down", "degraded"}:
        create_domain_event_notification(
            db,
            tenant_id=system.tenant_id,
            event_type="integration_health_down",
            title=f"Integration health: {system.name}",
            message=f"Система {system.name} имеет статус {system.health_status}.",
            recipient_name=current_user.full_name if current_user else "Integration Operator",
            recipient_email=_user_email(current_user),
            recipient_user_id=current_user.id if current_user else None,
            severity="warning",
            entity_type="external_system",
            entity_id=system.id,
            action_url="/integrations",
            metadata={"system_type": system.system_type, "health_status": system.health_status},
        )
        _trigger_automation(
            db,
            tenant_id=system.tenant_id,
            trigger_type="integration_health_down",
            context={"entity_type": "external_system", "entity_id": system.id, "system": {"id": system.id, "name": system.name, "health_status": system.health_status}},
            actor_email=_user_email(current_user),
        )
    return {"system_id": system.id, "health_status": system.health_status, "result": result, "event_id": event.id}


def create_event_log(
    db: Session,
    direction: str,
    event_type: str,
    payload: dict[str, Any] | None,
    *,
    external_system_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    status: str = "queued",
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    attempt_count: int = 0,
    next_retry_at: datetime | None = None,
    processed_at: datetime | None = None,
) -> IntegrationEventLog:
    system = db.get(ExternalSystem, external_system_id) if external_system_id else None
    event = create_integration_event(
        db,
        tenant_id=system.tenant_id if system else None,
        external_system_id=external_system_id,
        direction=direction,
        event_type=event_type,
        status=status,
        request_summary=payload or {},
        response_summary=response_payload or {},
        error_message=error_message,
    )
    event.entity_type = entity_type
    event.entity_id = entity_id
    event.payload_json = _json(payload or {})
    event.response_payload_json = _json(response_payload or {})
    event.attempt_count = attempt_count
    event.next_retry_at = next_retry_at
    event.processed_at = processed_at
    return event


def process_inbound_webhook(db: Session, endpoint: WebhookEndpoint, payload: dict[str, Any], current_user: User | None = None) -> IntegrationEventLog:
    now = _now()
    status = "success"
    error_message = None
    try:
        endpoint.last_received_at = now
        endpoint.success_count += 1
    except Exception as exc:  # noqa: BLE001
        endpoint.failure_count += 1
        status = "failed"
        error_message = str(exc)
    event = create_event_log(
        db,
        direction="inbound",
        event_type=endpoint.event_type,
        payload=payload,
        external_system_id=endpoint.external_system_id,
        entity_type="webhook_endpoint",
        entity_id=endpoint.id,
        status=status,
        error_message=error_message,
        processed_at=now,
    )
    log_audit(
        db,
        action="integration_webhook_received",
        entity_type="webhook_endpoint",
        entity_id=endpoint.id,
        actor_user=current_user,
        actor_email=_user_email(current_user),
        tenant_id=endpoint.tenant_id,
        metadata={"event_type": endpoint.event_type, "status": status, "event_id": event.id},
    )
    create_domain_event_notification(
        db,
        tenant_id=endpoint.tenant_id,
        event_type="webhook_received",
        title=f"Webhook received: {endpoint.name}",
        message=f"Получено событие {endpoint.event_type} через {endpoint.path}",
        recipient_name=current_user.full_name if current_user else "Integration Operator",
        recipient_email=_user_email(current_user),
        recipient_user_id=current_user.id if current_user else None,
        severity="info",
        entity_type="webhook_endpoint",
        entity_id=endpoint.id,
        action_url="/integrations",
        metadata={"event_id": event.id, "path": endpoint.path},
    )
    _trigger_automation(
        db,
        tenant_id=endpoint.tenant_id,
        trigger_type="webhook_received",
        context={"entity_type": "webhook_endpoint", "entity_id": endpoint.id, "webhook": {"id": endpoint.id, "path": endpoint.path, "event_type": endpoint.event_type}},
        actor_email=_user_email(current_user),
    )
    return event


def queue_outbound_event(
    db: Session,
    system_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    current_user: User | None = None,
) -> IntegrationEventLog:
    system = _find_system(db, system_id)
    event = create_event_log(
        db,
        direction="outbound",
        event_type=event_type,
        payload=payload,
        external_system_id=system.id,
        entity_type=entity_type,
        entity_id=entity_id,
        status="queued",
    )
    log_audit(
        db,
        action="integration_event_queued",
        entity_type="integration_event",
        entity_id=event.id,
        actor_user=current_user,
        actor_email=_user_email(current_user),
        tenant_id=system.tenant_id,
        metadata={"system_id": system.id, "event_type": event_type},
    )
    return event


def retry_integration_event(db: Session, event_id: str, current_user: User) -> IntegrationEventLog:
    event = db.get(IntegrationEventLog, event_id)
    if event is None:
        raise ValueError("Integration event not found")
    if event.status not in {"failed", "retrying"}:
        raise ValueError("Only failed/retrying events can be retried")
    system = db.get(ExternalSystem, event.external_system_id) if event.external_system_id else None
    provider = get_provider(system.system_type if system else "webhook")
    payload = _parse_json(event.payload_json)
    config = _parse_json(system.config_json) if system else {}
    event.attempt_count = int(event.attempt_count or 0) + 1
    event.status = "retrying"
    now = _now()
    if should_simulate_failure(config, event.event_type):
        event.status = "failed"
        event.error_message = "Mock failure simulated by system config"
        event.next_retry_at = now + timedelta(minutes=5)
        create_domain_event_notification(
            db,
            tenant_id=system.tenant_id if system else None,
            event_type="integration_event_failed",
            title="Integration event retry failed",
            message=f"Event {event.event_type} retry failed.",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="warning",
            entity_type="integration_event",
            entity_id=event.id,
            action_url="/integrations",
            metadata={"attempt_count": event.attempt_count},
        )
        _trigger_automation(
            db,
            tenant_id=system.tenant_id if system else None,
            trigger_type="integration_event_failed",
            context={"entity_type": "integration_event", "entity_id": event.id, "event": {"event_type": event.event_type, "status": event.status}},
            actor_email=current_user.email,
        )
    else:
        response = provider.send_notification(payload) if hasattr(provider, "send_notification") else {"status": "success"}
        event.status = "success"
        event.response_payload_json = _json(response)
        event.response_summary = _json(response)
        event.error_message = None
        event.next_retry_at = None
        event.processed_at = now

    log_audit(
        db,
        action="integration_event_retried",
        entity_type="integration_event",
        entity_id=event.id,
        actor_user=current_user,
        actor_email=current_user.email,
        tenant_id=system.tenant_id if system else None,
        metadata={"status": event.status, "attempt_count": event.attempt_count},
    )
    return event


def run_import_job(db: Session, job_id: str, dry_run: bool = False, current_user: User | None = None) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise ValueError("Import job not found")
    system = db.get(ExternalSystem, job.external_system_id) if job.external_system_id else None
    provider = get_provider(system.system_type if system else "file_import")
    now = _now()
    job.started_at = now
    job.status = "dry_run" if dry_run else "running"
    payload: dict[str, Any]
    if job.job_type == "assets":
        payload = provider.pull_assets()
    else:
        payload = provider.pull_users()
    total_rows = int(payload.get("records_total", 0))
    failed_rows = 0
    success_rows = total_rows
    if should_simulate_failure(_parse_json(system.config_json) if system else {}, f"import_{job.job_type}"):
        failed_rows = max(1, total_rows // 2) if total_rows else 1
        success_rows = max(0, total_rows - failed_rows)
    job.total_rows = total_rows
    job.success_rows = success_rows
    job.failed_rows = failed_rows
    job.records_total = total_rows
    job.records_success = success_rows
    job.records_failed = failed_rows
    job.dry_run = dry_run
    job.finished_at = _now()
    job.status = "dry_run" if dry_run else ("completed_with_errors" if failed_rows else "completed")
    job.error_report_json = _json({"failed_rows": failed_rows, "errors": ["mock_failure"] if failed_rows else []})
    job.error_message = "Mock import failure" if failed_rows else None

    create_event_log(
        db,
        direction="inbound",
        event_type="import_job_run",
        payload={"job_id": job.id, "job_type": job.job_type, "dry_run": dry_run},
        external_system_id=job.external_system_id,
        entity_type="import_job",
        entity_id=job.id,
        status="failed" if failed_rows else "success",
        response_payload={"total_rows": total_rows, "success_rows": success_rows, "failed_rows": failed_rows},
        error_message=job.error_message,
        processed_at=job.finished_at,
    )
    action = "integration_import_job_dry_run" if dry_run else "integration_import_job_run"
    log_audit(
        db,
        action=action,
        entity_type="import_job",
        entity_id=job.id,
        actor_user=current_user,
        actor_email=_user_email(current_user),
        tenant_id=job.tenant_id,
        metadata={"status": job.status, "total_rows": total_rows},
    )
    if failed_rows:
        create_domain_event_notification(
            db,
            tenant_id=job.tenant_id,
            event_type="integration_event_failed",
            title="Import job failed",
            message=f"Import job {job.job_type} completed with errors.",
            recipient_name=current_user.full_name if current_user else "Integration Operator",
            recipient_email=_user_email(current_user),
            recipient_user_id=current_user.id if current_user else None,
            severity="warning",
            entity_type="import_job",
            entity_id=job.id,
            action_url="/integrations",
            metadata={"failed_rows": failed_rows},
        )
    else:
        create_domain_event_notification(
            db,
            tenant_id=job.tenant_id,
            event_type="import_job_completed",
            title="Import job completed",
            message=f"Import job {job.job_type} completed successfully.",
            recipient_name=current_user.full_name if current_user else "Integration Operator",
            recipient_email=_user_email(current_user),
            recipient_user_id=current_user.id if current_user else None,
            severity="info",
            entity_type="import_job",
            entity_id=job.id,
            action_url="/integrations",
            metadata={"total_rows": total_rows, "dry_run": dry_run},
        )
        _trigger_automation(
            db,
            tenant_id=job.tenant_id,
            trigger_type="import_job_completed",
            context={"entity_type": "import_job", "entity_id": job.id, "job": {"id": job.id, "job_type": job.job_type, "status": job.status}},
            actor_email=_user_email(current_user),
        )
    return job


def create_mock_external_system(db: Session, system_type: str, name: str, current_user: User) -> ExternalSystem:
    now = _now()
    item = ExternalSystem(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        code=f"{system_type}_{uuid.uuid4().hex[:8]}",
        name=name,
        system_type=system_type,
        base_url=None,
        status="mock",
        health_status="unknown",
        is_mock=True,
        created_by_id=current_user.id,
        is_enabled=True,
        last_health_status="unknown",
        description="Created by integration production workflow.",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    log_audit(
        db,
        action="integration_system_created",
        entity_type="external_system",
        entity_id=item.id,
        actor_user=current_user,
        actor_email=current_user.email,
        tenant_id=current_user.tenant_id,
        metadata={"system_type": system_type, "is_mock": True},
    )
    return item


def apply_mapping(mapping: IntegrationMapping, source_payload: dict[str, Any]) -> dict[str, Any]:
    if mapping.source_field and mapping.target_field:
        value = source_payload.get(mapping.source_field)
        if mapping.transform_rule == "upper" and isinstance(value, str):
            value = value.upper()
        if mapping.transform_rule == "lower" and isinstance(value, str):
            value = value.lower()
        return {mapping.target_field: value}
    mapping_payload = _parse_json(mapping.mapping_json)
    output: dict[str, Any] = {}
    for source_key, target_key in mapping_payload.items():
        output[str(target_key)] = source_payload.get(str(source_key))
    return output


def validate_mapping(mapping: IntegrationMapping, payload: dict[str, Any]) -> tuple[bool, str | None]:
    if mapping.is_required and mapping.source_field and mapping.source_field not in payload:
        return False, f"Missing required source field: {mapping.source_field}"
    if mapping.source_field and mapping.target_field:
        return True, None
    mapping_payload = _parse_json(mapping.mapping_json)
    if mapping.is_required and mapping_payload:
        for source_key in mapping_payload.keys():
            if str(source_key) not in payload:
                return False, f"Missing required source field: {source_key}"
    return True, None


def export_entity_mock(db: Session, system_id: str, entity_type: str, entity_id: str, current_user: User) -> dict[str, Any]:
    system = _find_system(db, system_id)
    provider = get_provider(system.system_type)
    payload = {"entity_type": entity_type, "entity_id": entity_id, "dry_run": True, "system_code": system.code}
    response = provider.export_entity(payload)
    event = create_event_log(
        db,
        direction="outbound",
        event_type="export_entity",
        payload=payload,
        external_system_id=system.id,
        entity_type=entity_type,
        entity_id=entity_id,
        status="success",
        response_payload=response,
        processed_at=_now(),
    )
    create_domain_event_notification(
        db,
        tenant_id=system.tenant_id,
        event_type="export_completed",
        title="Integration export completed",
        message=f"Export {entity_type}:{entity_id} completed (mock-safe).",
        recipient_name=current_user.full_name,
        recipient_email=current_user.email,
        recipient_user_id=current_user.id,
        severity="info",
        entity_type=entity_type,
        entity_id=entity_id,
        action_url="/integrations",
        metadata={"event_id": event.id, "external_system_id": system.id},
    )
    log_audit(
        db,
        action="integration_export_requested",
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user=current_user,
        actor_email=current_user.email,
        tenant_id=system.tenant_id,
        metadata={"external_system_id": system.id, "event_id": event.id, "dry_run": True},
    )
    return {"event_id": event.id, "status": "success", "response": response}


__all__ = [
    "BaseIntegrationProvider",
    "MockFileImportProvider",
    "MockLDAPProvider",
    "MockMoodleProvider",
    "MockOneCProvider",
    "MockPlatonusProvider",
    "MockTelegramProvider",
    "MockWebhookProvider",
    "MockZimbraProvider",
    "apply_mapping",
    "check_system_health",
    "create_event_log",
    "create_mock_external_system",
    "export_entity_mock",
    "get_provider",
    "list_provider_descriptors",
    "list_provider_metadata",
    "process_inbound_webhook",
    "queue_outbound_event",
    "retry_integration_event",
    "run_import_job",
    "validate_mapping",
]
