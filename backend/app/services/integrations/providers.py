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
        return {"status": "mocked", "ticket_payload": ticket_payload}

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "mocked", "payload": payload}

    def receive_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "mocked", "payload": payload}

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
        return {"status": "ok", "message": "Mock LDAP directory reachable.", "checked_at": datetime.now(UTC)}

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
        return {"status": "ok", "message": "Mock Zimbra mailboxes available.", "checked_at": datetime.now(UTC)}

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
        return {"status": "ok", "message": "Mock SMTP gateway accepted test handshake.", "checked_at": datetime.now(UTC)}

    def send_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "logged_only", "message": "Notification was captured by Mock SMTP provider.", "payload": payload}


class MockPlatonusProvider(BaseIntegrationProvider):
    descriptor = ProviderDescriptor(
        code="platonus",
        name="Platonus",
        status="mock",
        capabilities=["health_check", "pull_users", "groups_preview"],
    )

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "message": "Mock Platonus SIS reachable.", "checked_at": datetime.now(UTC)}

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
        return {"status": "ok", "message": "Mock Moodle LMS reachable.", "checked_at": datetime.now(UTC)}

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
        return {"status": "accepted", "message": "Mock webhook event received.", "payload": payload, "received_at": datetime.now(UTC)}

    def push_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "accepted", "message": "Mock webhook event pushed.", "payload": payload, "sent_at": datetime.now(UTC)}


class StaticFutureProvider(BaseIntegrationProvider):
    def __init__(self, descriptor: ProviderDescriptor) -> None:
        self.descriptor = descriptor


_PROVIDER_INSTANCES: dict[str, BaseIntegrationProvider] = {
    "ldap": MockLdapProvider(),
    "zimbra": MockZimbraProvider(),
    "smtp": MockSmtpProvider(),
    "platonus": MockPlatonusProvider(),
    "moodle": MockMoodleProvider(),
    "webhook": MockWebhookProvider(),
    "active_directory": StaticFutureProvider(ProviderDescriptor("active_directory", "Active Directory", "planned", ["health_check", "pull_users"])),
    "telegram": StaticFutureProvider(ProviderDescriptor("telegram", "Telegram", "future", ["send_notification", "bot_events"])),
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
