from __future__ import annotations

import json
import uuid

import pytest

from app.core.config import Settings
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.services.custom_fields import (
    compare_schema_compatibility,
    create_field_set,
    create_field_set_draft,
    custom_field_values_response,
    get_entity,
    publish_field_set_version,
    save_custom_field_values,
    update_field_set_draft,
    validate_applicability,
    validate_custom_field_schema,
)


def _tenant(db_session, label: str = "custom-fields") -> Tenant:
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=f"Custom Fields {label}",
        slug=f"{label}-{uuid.uuid4().hex[:10]}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _ticket(db_session, tenant: Tenant) -> Ticket:
    ticket = Ticket(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        ticket_number=f"CF-{uuid.uuid4().hex[:8]}",
        title="Custom fields test",
        requester_email="requester@example.test",
        requester_name="Test Requester",
        department="IT",
        location="HQ",
        category="security",
        priority="high",
        status="open",
    )
    db_session.add(ticket)
    db_session.flush()
    return ticket


def _schema() -> dict:
    return {
        "schema_version": "1.0",
        "title": "Security extension",
        "introduction": "Structured tenant-owned fields.",
        "sections": [
            {
                "id": "details",
                "title": "Details",
                "description": "",
                "order": 10,
            }
        ],
        "fields": [
            {
                "key": "business_service",
                "label": "Business service",
                "type": "text",
                "section_id": "details",
                "required": True,
                "help_text": "",
                "placeholder": "",
                "options": [],
                "validations": {"min_length": 2, "max_length": 100},
                "searchable": True,
                "indexed": True,
                "reportable": True,
                "sensitive": False,
                "immutable_after_set": False,
            },
            {
                "key": "security_reference",
                "label": "Security reference",
                "type": "text",
                "section_id": "details",
                "required": True,
                "help_text": "",
                "placeholder": "",
                "options": [],
                "validations": {"min_length": 4, "max_length": 100},
                "searchable": False,
                "indexed": False,
                "reportable": True,
                "sensitive": True,
                "immutable_after_set": True,
            },
        ],
    }


def _published_field_set(db_session, tenant: Tenant):
    field_set, draft = create_field_set(
        db_session,
        tenant_id=tenant.id,
        code="ticket.security_extension",
        name="Security extension",
        description="Test typed fields",
        entity_type="ticket",
        applicability={"all": [{"field": "category", "operator": "eq", "value": "security"}]},
        actor_id=None,
    )
    outcome = update_field_set_draft(
        db_session,
        draft,
        field_set,
        schema=_schema(),
        expected_revision=1,
        change_summary="Add governed fields",
        actor_id=None,
    )
    assert outcome["validation"]["valid"] is True
    publish_field_set_version(
        db_session,
        field_set,
        draft,
        expected_field_set_revision=1,
        expected_version_revision=2,
        allow_breaking_changes=False,
        actor_id=None,
    )
    return field_set, draft


def test_schema_validation_and_compatibility_are_fail_closed() -> None:
    schema = _schema()
    assert validate_custom_field_schema(schema)["valid"] is True

    unsafe = _schema()
    unsafe["fields"][1]["searchable"] = True
    validation = validate_custom_field_schema(unsafe)
    assert validation["valid"] is False
    assert any("sensitive" in item for item in validation["errors"])

    removed = _schema()
    removed["fields"] = removed["fields"][:1]
    comparison = compare_schema_compatibility(schema, removed)
    assert comparison["compatible"] is False
    assert comparison["breaking"] == [{"field": "security_reference", "reason": "field_removed"}]

    new_required = _schema()
    new_required["fields"].append(
        {
            "key": "regulatory_scope",
            "label": "Regulatory scope",
            "type": "text",
            "section_id": "details",
            "required": True,
            "help_text": "",
            "placeholder": "",
            "options": [],
            "validations": {},
            "searchable": False,
            "indexed": False,
            "reportable": True,
            "sensitive": False,
            "immutable_after_set": False,
        }
    )
    comparison = compare_schema_compatibility(schema, new_required)
    assert comparison["compatible"] is False
    assert any(
        item["reason"] == "required_field_without_default" for item in comparison["breaking"]
    )


def test_applicability_rejects_unsafe_entity_attributes() -> None:
    assert validate_applicability(
        "ticket",
        {"all": [{"field": "password_hash", "operator": "eq", "value": "x"}]},
    )
    assert validate_applicability(
        "ticket",
        {"all": [{"field": "status", "operator": "contains", "value": "open"}]},
    )
    assert (
        validate_applicability(
            "ticket",
            {"all": [{"field": "priority", "operator": "in", "value": ["high"]}]},
        )
        == []
    )


def test_versioned_values_encrypt_mask_search_and_enforce_immutability(
    db_session,
) -> None:
    tenant = _tenant(db_session)
    ticket = _ticket(db_session, tenant)
    field_set, draft = _published_field_set(db_session, tenant)
    settings = Settings(
        demo_mode=True,
        credential_encryption_key="custom-fields-test-encryption-key-000000000000",
    )

    value, normalized = save_custom_field_values(
        db_session,
        field_set,
        entity=ticket,
        submitted_values={
            "business_service": "Payroll",
            "security_reference": "SEC-741",
        },
        expected_version=None,
        actor_id=None,
        settings=settings,
    )
    assert normalized == {
        "business_service": "Payroll",
        "security_reference": "SEC-741",
    }
    stored = json.loads(value.values_json)
    assert stored["business_service"] == "Payroll"
    assert stored["security_reference"] != "SEC-741"
    assert stored["security_reference"]["__encrypted__"].startswith("v1.")
    assert value.search_text == "payroll"
    assert value.field_set_version_number == draft.version_number

    masked = custom_field_values_response(
        value,
        _schema(),
        can_read_sensitive=False,
    )
    assert masked["values"]["security_reference"] == "••••••"
    assert "__encrypted__" not in str(masked)

    revealed = custom_field_values_response(
        value,
        _schema(),
        can_read_sensitive=True,
        settings=settings,
    )
    assert revealed["values"]["security_reference"] == "SEC-741"

    with pytest.raises(ValueError, match="immutable"):
        save_custom_field_values(
            db_session,
            field_set,
            entity=ticket,
            submitted_values={"security_reference": "SEC-999"},
            expected_version=1,
            actor_id=None,
            settings=settings,
        )

    with pytest.raises(ValueError, match="current version"):
        save_custom_field_values(
            db_session,
            field_set,
            entity=ticket,
            submitted_values={"business_service": "HR"},
            expected_version=0,
            actor_id=None,
            settings=settings,
        )


def test_breaking_publish_requires_explicit_approval_when_values_exist(
    db_session,
) -> None:
    tenant = _tenant(db_session, "breaking")
    ticket = _ticket(db_session, tenant)
    field_set, _ = _published_field_set(db_session, tenant)
    settings = Settings(
        demo_mode=True,
        credential_encryption_key="custom-fields-test-encryption-key-000000000000",
    )
    save_custom_field_values(
        db_session,
        field_set,
        entity=ticket,
        submitted_values={
            "business_service": "Payments",
            "security_reference": "SEC-100",
        },
        expected_version=None,
        actor_id=None,
        settings=settings,
    )
    draft = create_field_set_draft(
        db_session,
        field_set,
        actor_id=None,
        change_summary="Remove security field",
    )
    candidate = _schema()
    candidate["fields"] = candidate["fields"][:1]
    outcome = update_field_set_draft(
        db_session,
        draft,
        field_set,
        schema=candidate,
        expected_revision=1,
        change_summary="Remove security field",
        actor_id=None,
    )
    assert outcome["compatibility"]["compatible"] is False

    with pytest.raises(ValueError, match="explicit approval"):
        publish_field_set_version(
            db_session,
            field_set,
            draft,
            expected_field_set_revision=3,
            expected_version_revision=2,
            allow_breaking_changes=False,
            actor_id=None,
        )
    comparison = publish_field_set_version(
        db_session,
        field_set,
        draft,
        expected_field_set_revision=3,
        expected_version_revision=2,
        allow_breaking_changes=True,
        actor_id=None,
    )
    assert comparison["compatible"] is False
    assert draft.breaking_change is True


def test_entity_resolution_and_integrity_are_tenant_scoped(db_session) -> None:
    tenant = _tenant(db_session, "scope-a")
    other_tenant = _tenant(db_session, "scope-b")
    ticket = _ticket(db_session, tenant)
    field_set, _ = _published_field_set(db_session, tenant)
    settings = Settings(
        demo_mode=True,
        credential_encryption_key="custom-fields-test-encryption-key-000000000000",
    )
    value, _ = save_custom_field_values(
        db_session,
        field_set,
        entity=ticket,
        submitted_values={
            "business_service": "Identity",
            "security_reference": "SEC-500",
        },
        expected_version=None,
        actor_id=None,
        settings=settings,
    )
    with pytest.raises(ValueError, match="not found"):
        get_entity(
            db_session,
            tenant_id=other_tenant.id,
            entity_type="ticket",
            entity_id=ticket.id,
        )

    value.values_json = value.values_json.replace("Identity", "Tampered")
    with pytest.raises(ValueError, match="integrity"):
        custom_field_values_response(
            value,
            _schema(),
            can_read_sensitive=False,
        )
