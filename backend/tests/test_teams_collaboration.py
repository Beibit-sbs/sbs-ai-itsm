from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.major_incident import MajorIncident
from app.models.teams_collaboration import TeamsConnector, TeamsDelivery
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.user import User
from app.services.teams_collaboration import (
    build_teams_card,
    ensure_major_incident_room,
    process_teams_delivery,
    queue_teams_event,
    validate_workflow_webhook_url,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        credential_encryption_key=(
            "teams-tests-use-a-dedicated-credential-encryption-key-2026"
        ),
        teams_public_base_url="https://itsm.example.test",
        teams_webhook_allowed_hosts=[".logic.azure.com"],
    )


def _tenant(db_session) -> Tenant:
    item = Tenant(
        id=str(uuid.uuid4()),
        name="Teams Test Tenant",
        slug=f"teams-test-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db_session.add(item)
    db_session.flush()
    return item


def _connector(
    db_session,
    tenant: Tenant,
    *,
    purpose: str = "DEFAULT",
) -> TeamsConnector:
    item = TeamsConnector(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=f"{purpose}-{uuid.uuid4().hex[:6]}",
        provider_type="MOCK",
        status="ACTIVE",
        purpose=purpose,
        team_name="IT Operations",
        channel_name="Service Desk",
        channel_url="https://teams.microsoft.com/l/channel/test",
        meeting_url=(
            "https://teams.microsoft.com/l/meetup-join/test"
            if purpose == "MAJOR_INCIDENT"
            else None
        ),
        event_types_json=["ticket_created", "approval_required", "major_incident.declared"],
        minimum_severity="INFO",
        success_count=0,
        failure_count=0,
        version=1,
    )
    db_session.add(item)
    db_session.flush()
    return item


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_workflow_webhook_validation_blocks_ssrf_and_lookalikes() -> None:
    settings = _settings()
    accepted = validate_workflow_webhook_url(
        "https://prod-42.westeurope.logic.azure.com/workflows/id/triggers/manual",
        settings=settings,
    )
    assert accepted.startswith("https://prod-42.westeurope.logic.azure.com/")

    for candidate in (
        "http://prod-42.westeurope.logic.azure.com/workflows/id",
        "https://logic.azure.com/workflows/id",
        "https://logic.azure.com.evil.test/workflows/id",
        "https://127.0.0.1/workflows/id",
        "https://user:password@prod-42.westeurope.logic.azure.com/workflows/id",
    ):
        try:
            validate_workflow_webhook_url(candidate, settings=settings)
        except ValueError:
            continue
        raise AssertionError(f"Unsafe webhook URL was accepted: {candidate}")


def test_adaptive_card_redacts_secrets_and_uses_secure_review_action() -> None:
    payload = build_teams_card(
        event_type="approval_required",
        severity="WARNING",
        title="Approval required",
        message="password=SuperSecret token: abc-123",
        entity_type="approval_request",
        entity_id="approval-1",
        action_url="https://itsm.example.test/automation?approval_id=approval-1",
    )
    serialized = str(payload)
    assert "SuperSecret" not in serialized
    assert "abc-123" not in serialized
    assert "Review and decide securely" in serialized
    assert "Action.Execute" not in serialized


def test_queue_is_tenant_scoped_and_suppresses_immediate_duplicate(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    connector = _connector(db_session, tenant)
    first = queue_teams_event(
        db_session,
        tenant_id=tenant.id,
        event_type="ticket_created",
        title="INC-100 created",
        message="A new ticket needs triage.",
        entity_type="ticket",
        entity_id="ticket-100",
        action_url="/tickets?ticket_id=ticket-100",
        idempotency_source="ticket-100:created",
    )
    db_session.flush()
    duplicate = queue_teams_event(
        db_session,
        tenant_id=tenant.id,
        event_type="ticket_created",
        title="INC-100 created",
        message="A new ticket needs triage.",
        entity_type="ticket",
        entity_id="ticket-100",
        action_url="/tickets?ticket_id=ticket-100",
        idempotency_source="ticket-100:created-again",
    )
    assert len(first) == 1
    assert duplicate == []
    assert first[0].connector_id == connector.id
    assert first[0].tenant_id == tenant.id


def test_mock_delivery_is_simulated_without_transport_success(db_session) -> None:
    tenant = _tenant(db_session)
    connector = _connector(db_session, tenant)
    now = datetime.now(UTC)
    delivery = TeamsDelivery(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        connector_id=connector.id,
        event_type="ticket_created",
        severity="INFO",
        entity_type="ticket",
        entity_id="ticket-1",
        idempotency_key=uuid.uuid4().hex,
        title="Ticket created",
        message="Ticket is ready for triage",
        payload_json={"type": "message"},
        status="QUEUED",
        attempts=0,
        max_attempts=6,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(delivery)
    db_session.flush()

    process_teams_delivery(db_session, delivery, settings=_settings())

    assert delivery.status == "SIMULATED"
    assert delivery.attempts == 0
    assert delivery.provider_status_code is None
    assert delivery.provider_reference is None
    assert delivery.sent_at is None
    assert "no Microsoft Teams webhook" in (delivery.last_error or "")
    assert connector.success_count == 0
    assert connector.last_success_at is None


def test_mock_delivery_fails_closed_outside_demo_mode(db_session) -> None:
    tenant = _tenant(db_session)
    connector = _connector(db_session, tenant)
    now = datetime.now(UTC)
    delivery = TeamsDelivery(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        connector_id=connector.id,
        event_type="ticket_created",
        severity="INFO",
        entity_type="ticket",
        entity_id="ticket-2",
        idempotency_key=uuid.uuid4().hex,
        title="Ticket created",
        message="This mock must not deliver in production mode.",
        payload_json={"type": "message"},
        status="QUEUED",
        attempts=0,
        max_attempts=6,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(delivery)
    db_session.flush()
    production_settings = Settings(
        _env_file=None,
        demo_mode=False,
        credential_encryption_key=(
            "teams-tests-use-a-dedicated-credential-encryption-key-2026"
        ),
        teams_public_base_url="https://itsm.example.test",
        teams_webhook_allowed_hosts=[".logic.azure.com"],
    )

    process_teams_delivery(
        db_session,
        delivery,
        settings=production_settings,
    )

    assert delivery.status == "FAILED"
    assert delivery.attempts == 0
    assert delivery.sent_at is None
    assert "disabled outside demo mode" in (delivery.last_error or "")
    assert connector.success_count == 0


def test_major_incident_room_uses_dedicated_connector(db_session) -> None:
    tenant = _tenant(db_session)
    connector = _connector(db_session, tenant, purpose="MAJOR_INCIDENT")
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        ticket_number=f"INC-{uuid.uuid4().hex[:8]}",
        title="Production outage",
        description="Synthetic test incident",
        status="OPEN",
        priority="CRITICAL",
        requester_name="Test Requester",
        requester_email="requester@example.test",
        department="IT",
        location="HQ",
        category="Infrastructure",
    )
    db_session.add(ticket)
    commander = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=f"commander-{uuid.uuid4().hex[:8]}@example.test",
        full_name="Incident Commander",
        password_hash="not-used-in-this-test",
        is_active=True,
        is_superuser=False,
        is_root=False,
    )
    db_session.add(commander)
    db_session.flush()
    now = datetime.now(UTC)
    incident = MajorIncident(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        ticket_id=ticket.id,
        major_number=f"MI-{uuid.uuid4().hex[:8]}",
        severity="SEV1",
        status="DECLARED",
        title="Production outage",
        executive_summary="Synthetic test",
        impact_statement="Service unavailable",
        affected_service="Customer portal",
        service_status="MAJOR_OUTAGE",
        customer_impact="Synthetic test",
        commander_user_id=commander.id,
        communications_lead_user_id=commander.id,
        declared_at=now,
        next_update_due_at=now + timedelta(minutes=30),
        version=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(incident)
    db_session.flush()

    room = ensure_major_incident_room(
        db_session,
        incident=incident,
        opened_by_id=None,
    )

    assert room is not None
    assert room.connector_id == connector.id
    assert room.meeting_url == connector.meeting_url
    assert incident.war_room_url == connector.meeting_url


def test_admin_can_configure_mock_connector_without_secret_exposure(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local")
        response = client.post(
            "/api/v1/teams/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Local Teams acceptance",
                "provider_type": "MOCK",
                "purpose": "DEFAULT",
                "event_types": ["ticket_created"],
                "minimum_severity": "INFO",
            },
        )
        assert response.status_code == 201, response.text
        connector = response.json()
        assert connector["status"] == "DRAFT"
        assert connector["webhook_configured"] is False
        assert "webhook_url_encrypted" not in connector
        tested = client.post(
            f"/api/v1/teams/connectors/{connector['id']}/test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["ok"] is False
        assert tested.json()["status"] == "SIMULATED"
        refreshed = client.get(
            f"/api/v1/teams/connectors/{connector['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["success_count"] == 0
        assert refreshed.json()["last_success_at"] is None
