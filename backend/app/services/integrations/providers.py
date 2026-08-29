from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.integration_event_log import IntegrationEventLog


@dataclass(frozen=True)
class ProviderDescriptor:
    code: str
    name: str
    status: str
    capabilities: list[str]


class BaseIntegrationProvider:
    descriptor: ProviderDescriptor

    def health_check(self) -> dict[str, Any]:
        return {"status": "not_configured", "message": f"{self.descriptor.name} provider is not configured.", "checked_at": datetime.now(UTC)}

    def test_connection(self) -> dict[str, Any]:
        return {"status": "not_supported", "message": f"{self.descriptor.name} test connection is not available.", "checked_at": datetime.now(UTC)}

    def pull_users(self) -> dict[str, Any]:
        return {"preview": True, "users": []}

    def pull_mailboxes(self) -> dict[str, Any]:
        return {"preview": True, "mailboxes": []}

    def pull_assets(self) -> dict[str, Any]:
        return {"preview": True, "assets": []}

    def push_ticket(self, ticket_payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_supported", "ticket_payload": ticket_payload}

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_supported", "payload": payload}

    def receive_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_supported", "payload": payload}

    def export_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_supported", "payload": payload, "exported": False}

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "code": self.descriptor.code,
            "name": self.descriptor.name,
            "status": self.descriptor.status,
            "capabilities": self.descriptor.capabilities,
        }


class MockLdapProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="ldap",
        name="LDAP",
        status="mock",
        capabilities=["health_check", "pull_users", "preview_sync", "import_job_preview"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "LDAP demo data is available; no directory was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def pull_users(self) -> dict[str, Any]:
        users = [
            {"email": "rector@university.local", "full_name": "Rector", "department": "Executive"},
            {"email": "admin@university.local", "full_name": "Directory Admin", "department": "IT"},
            {"email": "it.manager@university.local", "full_name": "IT Manager", "department": "IT"},
            {"email": "teacher.one@university.local", "full_name": "Teacher One", "department": "Faculty"},
            {"email": "student.one@university.local", "full_name": "Student One", "department": "Students"},
        ]
        return {"preview": True, "records_total": len(users), "users": users}


class MockZimbraProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="zimbra",
        name="Zimbra",
        status="mock",
        capabilities=["health_check", "pull_mailboxes", "mailbox_health_preview", "push_ticket"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Zimbra demo data is available; no mail server was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def pull_mailboxes(self) -> dict[str, Any]:
        mailboxes = [
            {"email": "rector@university.kz", "quota_status": "ok", "mailbox_health": "healthy"},
            {"email": "it@university.kz", "quota_status": "warning", "mailbox_health": "degraded"},
            {"email": "support@university.kz", "quota_status": "ok", "mailbox_health": "healthy"},
            {"email": "security@university.kz", "quota_status": "ok", "mailbox_health": "healthy"},
        ]
        return {"preview": True, "records_total": len(mailboxes), "mailboxes": mailboxes}


class MockSmtpProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="smtp",
        name="SMTP",
        status="mock",
        capabilities=["test_connection", "send_notification", "event_logging_only"],
    )

    def test_connection(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "SMTP demo handshake only; no gateway was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Notification was captured by the SMTP demo provider.",
            "payload": payload,
        }


class MockPlatonusProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="platonus",
        name="Platonus",
        status="mock",
        capabilities=["health_check", "pull_users", "groups_preview"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Platonus demo data is available; no SIS was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def pull_users(self) -> dict[str, Any]:
        users = [
            {"email": "dean@university.local", "group": "Academic Leadership", "department": "Academic Office"},
            {"email": "registrar@university.local", "group": "Registry", "department": "Student Office"},
            {"email": "teacher.one@university.local", "group": "Faculty", "department": "Mathematics"},
            {"email": "student.one@university.local", "group": "Students", "department": "Computer Science"},
        ]
        return {"preview": True, "records_total": len(users), "users": users, "groups": ["Academic Leadership", "Registry", "Faculty", "Students"]}


class MockMoodleProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="moodle",
        name="Moodle",
        status="mock",
        capabilities=["health_check", "pull_users", "courses_preview", "user_course_mapping_preview"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Moodle demo data is available; no LMS was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def pull_users(self) -> dict[str, Any]:
        users = [
            {"email": "teacher.one@university.local", "courses": ["Math 101", "Data Literacy"]},
            {"email": "student.one@university.local", "courses": ["Math 101", "Intro to ITSM"]},
            {"email": "student.two@university.local", "courses": ["Intro to ITSM"]},
        ]
        return {"preview": True, "records_total": len(users), "users": users, "courses": ["Math 101", "Data Literacy", "Intro to ITSM"]}


class MockWebhookProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="webhook",
        name="Webhook",
        status="mock",
        capabilities=["receive_event", "push_event", "simulate_event"],
    )

    def receive_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Webhook event was captured by the demo provider.",
            "payload": payload,
            "received_at": datetime.now(UTC),
        }

    def push_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Webhook event was captured locally; nothing was sent.",
            "payload": payload,
            "sent_at": None,
        }


class MockOneCProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="one_c",
        name="1C",
        status="mock",
        capabilities=["health_check", "pull_assets", "export_entity", "import_job_preview"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "1C demo data is available; no 1C instance was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def pull_assets(self) -> dict[str, Any]:
        assets = [
            {"inventory_number": "1C-1001", "name": "Mock Laptop 1", "status": "active"},
            {"inventory_number": "1C-1002", "name": "Mock Laptop 2", "status": "active"},
        ]
        return {"preview": True, "records_total": len(assets), "assets": assets}

    def export_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "exported": False,
            "preview": payload,
            "message": "1C export preview generated; nothing was exported.",
        }


class MockTelegramProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="telegram",
        name="Telegram",
        status="mock",
        capabilities=["health_check", "send_notification", "push_event"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Telegram demo provider is enabled; no bot API was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Telegram message was captured locally; nothing was sent.",
            "payload": payload,
        }


class MockEmailProviderAdapter(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="email",
        name="Email Adapter",
        status="mock",
        capabilities=["health_check", "send_notification", "event_logging_only"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Email demo adapter is enabled; no provider was contacted.",
            "checked_at": datetime.now(UTC),
        }

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "Email payload was captured locally; nothing was sent.",
            "payload": payload,
        }


class MockLDAPProvider(MockLdapProvider):
    descriptor = ProviderDescriptor(
        code="ldap",
        name="LDAP",
        status="mock",
        capabilities=["health_check", "pull_users", "preview_sync", "import_job_preview", "bind_mock"],
    )


class MockFileImportProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="file_import",
        name="File Import",
        status="mock",
        capabilities=["health_check", "import_job_preview", "import_job_run"],
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "simulated",
            "message": "File import demo provider is ready; no file was imported.",
            "checked_at": datetime.now(UTC),
        }


def should_simulate_failure(config: dict[str, Any] | None, event_type: str | None = None) -> bool:
    if not isinstance(config, dict):
        return False
    if bool(config.get("force_failure")):
        return True
    failed_events = config.get("fail_events")
    if event_type and isinstance(failed_events, list):
        return event_type in {str(item) for item in failed_events}
    return False


class StaticFutureProvider(BaseIntegrationProvider):
    def __init__(self, descriptor: ProviderDescriptor) -> None:
        self.descriptor = descriptor


_PROVIDER_INSTANCES: dict[str, BaseIntegrationProvider] = {
    "one_c": MockOneCProvider(),
    "ldap": MockLDAPProvider(),
    "zimbra": MockZimbraProvider(),
    "email": MockEmailProviderAdapter(),
    "smtp": MockSmtpProvider(),
    "telegram": MockTelegramProvider(),
    "platonus": MockPlatonusProvider(),
    "moodle": MockMoodleProvider(),
    "webhook": MockWebhookProvider(),
    "file_import": MockFileImportProvider(),
    "active_directory": StaticFutureProvider(ProviderDescriptor("active_directory", "Active Directory", "planned", ["health_check", "pull_users"])),
    "whatsapp": StaticFutureProvider(ProviderDescriptor("whatsapp", "WhatsApp", "future", ["send_notification", "message_events"])),
    "custom_api": StaticFutureProvider(ProviderDescriptor("custom_api", "Custom API", "future", ["pull_assets", "push_ticket", "webhooks"])),
}


def get_provider(provider_code: str) -> BaseIntegrationProvider:
    provider = _PROVIDER_INSTANCES.get(provider_code)
    if provider is None:
        return StaticFutureProvider(ProviderDescriptor(provider_code, provider_code.replace("_", " ").title(), "future", []))
    return provider


def list_provider_descriptors() -> list[ProviderDescriptor]:
    return [provider.descriptor for provider in _PROVIDER_INSTANCES.values()]


def list_provider_metadata() -> list[dict[str, Any]]:
    return [provider.get_capabilities() for provider in _PROVIDER_INSTANCES.values()]


def create_integration_event(
    db: Session,
    *,
    tenant_id: str | None,
    external_system_id: str | None,
    direction: str,
    event_type: str,
    status: str,
    request_summary: dict[str, Any] | None = None,
    response_summary: dict[str, Any] | None = None,
    error_message: str | None = None,
    correlation_id: str | None = None,
) -> IntegrationEventLog:
    payload = IntegrationEventLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        external_system_id=external_system_id,
        direction=direction,
        event_type=event_type,
        status=status,
        request_summary=json.dumps(request_summary or {}, ensure_ascii=False, default=str),
        response_summary=json.dumps(response_summary or {}, ensure_ascii=False, default=str),
        error_message=error_message,
        correlation_id=correlation_id or str(uuid.uuid4()),
        created_at=datetime.now(UTC),
    )
    db.add(payload)
    return payload
