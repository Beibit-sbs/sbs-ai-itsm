from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.identity_provisioning import (
    IdentityProvisioningConnector,
    IdentityProvisioningEvent,
    ProvisionedGroup,
    ProvisionedGroupMember,
    ProvisionedIdentity,
)
from app.models.user import User
from app.services.audit import log_audit
from app.services.identity_lifecycle import (
    IdentityLifecycleError,
    apply_identity_roles,
    deactivate_provisioned_user,
    resolve_identity_manager,
    resolve_pending_reports,
    synchronize_user_display_references,
    utcnow,
)


SCIM_CORE_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE_USER = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)
SCIM_CORE_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

DEFAULT_ATTRIBUTE_MAPPING: dict[str, str] = {
    "email": "userName",
    "full_name": "displayName",
    "position": "title",
    "department": f"{SCIM_ENTERPRISE_USER}.department",
    "location": "addresses.0.locality",
    "cost_center": f"{SCIM_ENTERPRISE_USER}.costCenter",
    "employee_number": f"{SCIM_ENTERPRISE_USER}.employeeNumber",
    "phone": "phoneNumbers.0.value",
    "manager_external_id": f"{SCIM_ENTERPRISE_USER}.manager.value",
}
SUPPORTED_USER_TARGETS = frozenset(DEFAULT_ATTRIBUTE_MAPPING)
SUPPORTED_FILTER_RE = re.compile(
    r'^\s*(userName|externalId|id|active)\s+eq\s+(?:"([^"]*)"|(true|false))\s*$',
    re.IGNORECASE,
)
GROUP_MEMBER_FILTER_RE = re.compile(
    r'^\s*members\s*\[\s*value\s+eq\s+"([^"]+)"\s*\]\s*$',
    re.IGNORECASE,
)


class ScimProvisioningError(ValueError):
    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        scim_type: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.scim_type = scim_type
        self.retryable = retryable


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _path_get(payload: object, dotted_path: str) -> object | None:
    current: object = payload
    enterprise_prefix = f"{SCIM_ENTERPRISE_USER}."
    if dotted_path.startswith(enterprise_prefix):
        if not isinstance(current, dict):
            return None
        current = current.get(SCIM_ENTERPRISE_USER)
        parts = dotted_path[len(enterprise_prefix) :].split(".")
    else:
        parts = dotted_path.split(".")
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
        if current is None:
            return None
    return current


def _text(value: object | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:max_length] or None


def mapped_user_attributes(
    connector: IdentityProvisioningConnector,
    payload: dict[str, Any],
) -> dict[str, str | None]:
    configured = connector.attribute_mapping_json or {}
    mapping = {
        target: str(configured.get(target) or source)
        for target, source in DEFAULT_ATTRIBUTE_MAPPING.items()
    }
    values = {
        target: _path_get(payload, source)
        for target, source in mapping.items()
        if target in SUPPORTED_USER_TARGETS
    }
    email = _text(values.get("email"), max_length=255)
    if not email:
        emails = payload.get("emails")
        if isinstance(emails, list):
            primary = next(
                (
                    item
                    for item in emails
                    if isinstance(item, dict) and item.get("primary") is True
                ),
                None,
            )
            candidate = primary or next(
                (item for item in emails if isinstance(item, dict)),
                None,
            )
            email = _text(
                candidate.get("value") if isinstance(candidate, dict) else None,
                max_length=255,
            )
    name = payload.get("name")
    full_name = _text(values.get("full_name"), max_length=200)
    if not full_name and isinstance(name, dict):
        full_name = _text(name.get("formatted"), max_length=200)
        if not full_name:
            full_name = " ".join(
                item
                for item in (
                    _text(name.get("givenName"), max_length=100),
                    _text(name.get("familyName"), max_length=100),
                )
                if item
            )
    return {
        "email": email.lower() if email else None,
        "full_name": full_name or email or "Provisioned user",
        "position": _text(values.get("position"), max_length=200),
        "department": _text(values.get("department"), max_length=200),
        "location": _text(values.get("location"), max_length=200),
        "cost_center": _text(values.get("cost_center"), max_length=100),
        "employee_number": _text(values.get("employee_number"), max_length=120),
        "phone": _text(values.get("phone"), max_length=64),
        "manager_external_id": _text(
            values.get("manager_external_id"),
            max_length=255,
        ),
    }


def _user_location(base_url: str, identity_id: str) -> str:
    return f"{base_url.rstrip('/')}/Users/{identity_id}"


def _group_location(base_url: str, group_id: str) -> str:
    return f"{base_url.rstrip('/')}/Groups/{group_id}"


def scim_user_resource(
    db: Session,
    identity: ProvisionedIdentity,
    *,
    base_url: str,
) -> dict[str, Any]:
    user = db.get(User, identity.user_id)
    if user is None:
        raise ScimProvisioningError(404, "Provisioned user no longer exists")
    manager_value = identity.manager_external_id
    manager_display = None
    if user.manager_id:
        manager = db.get(User, user.manager_id)
        manager_display = manager.full_name if manager else None
        manager_identity = db.scalar(
            select(ProvisionedIdentity).where(
                ProvisionedIdentity.connector_id == identity.connector_id,
                ProvisionedIdentity.user_id == user.manager_id,
            )
        )
        if manager_identity:
            manager_value = manager_identity.id
    enterprise: dict[str, Any] = {
        "employeeNumber": user.employee_number,
        "costCenter": user.cost_center,
        "department": user.department,
    }
    if manager_value:
        enterprise["manager"] = {
            "value": manager_value,
            "displayName": manager_display,
        }
    return {
        "schemas": [SCIM_CORE_USER, SCIM_ENTERPRISE_USER],
        "id": identity.id,
        "externalId": identity.external_id,
        "userName": user.email,
        "displayName": user.full_name,
        "name": {"formatted": user.full_name},
        "title": user.position,
        "active": user.is_active and identity.lifecycle_state == "ACTIVE",
        "emails": [{"value": user.email, "type": "work", "primary": True}],
        "phoneNumbers": (
            [{"value": user.phone, "type": "work"}] if user.phone else []
        ),
        "addresses": (
            [{"locality": user.location, "type": "work"}] if user.location else []
        ),
        SCIM_ENTERPRISE_USER: enterprise,
        "meta": {
            "resourceType": "User",
            "created": identity.created_at,
            "lastModified": identity.updated_at,
            "location": _user_location(base_url, identity.id),
            "version": f'W/"{identity.scim_version}"',
        },
    }


def scim_group_resource(
    db: Session,
    group: ProvisionedGroup,
    *,
    base_url: str,
) -> dict[str, Any]:
    members = db.execute(
        select(ProvisionedIdentity.id, User.full_name)
        .join(
            ProvisionedGroupMember,
            ProvisionedGroupMember.identity_id == ProvisionedIdentity.id,
        )
        .join(User, User.id == ProvisionedIdentity.user_id)
        .where(ProvisionedGroupMember.group_id == group.id)
        .order_by(User.full_name.asc())
    ).all()
    return {
        "schemas": [SCIM_CORE_GROUP],
        "id": group.id,
        "externalId": group.external_id,
        "displayName": group.display_name,
        "members": [
            {
                "value": identity_id,
                "display": full_name,
                "$ref": f"{base_url.rstrip('/')}/Users/{identity_id}",
            }
            for identity_id, full_name in members
        ],
        "meta": {
            "resourceType": "Group",
            "created": group.created_at,
            "lastModified": group.updated_at,
            "location": _group_location(base_url, group.id),
            "version": f'W/"{group.scim_version}"',
        },
    }


def parse_scim_filter(filter_value: str | None) -> tuple[str, str | bool] | None:
    if not filter_value:
        return None
    match = SUPPORTED_FILTER_RE.match(filter_value)
    if not match:
        raise ScimProvisioningError(
            400,
            "Supported filters are id, externalId, userName, or active with eq",
            scim_type="invalidFilter",
        )
    attribute = match.group(1)
    raw_string = match.group(2)
    raw_bool = match.group(3)
    if raw_bool is not None:
        return attribute, raw_bool.lower() == "true"
    return attribute, raw_string or ""


def _validate_external_id(payload: dict[str, Any]) -> str:
    external_id = _text(payload.get("externalId"), max_length=255)
    if not external_id:
        raise ScimProvisioningError(
            400,
            "externalId is required and must be immutable",
            scim_type="invalidValue",
        )
    return external_id


def _validate_email(email: str | None) -> str:
    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ScimProvisioningError(
            400,
            "userName must contain a valid email address",
            scim_type="invalidValue",
        )
    return email


def _ensure_email_available(
    db: Session,
    *,
    email: str,
    current_user_id: str | None,
) -> None:
    existing = db.scalar(select(User).where(func_lower(User.email) == email.lower()))
    if existing is not None and existing.id != current_user_id:
        raise ScimProvisioningError(
            409,
            "userName is already assigned to another platform user",
            scim_type="uniqueness",
        )


def func_lower(column: object) -> object:
    from sqlalchemy import func

    return func.lower(column)


def _activate_identity(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    identity: ProvisionedIdentity,
    user: User,
) -> None:
    now = utcnow()
    user.is_active = True
    user.identity_source = connector.provider_type
    user.provisioning_state = "ACTIVE"
    user.deactivated_at = None
    user.updated_at = now
    identity.lifecycle_state = "ACTIVE"
    identity.deprovisioned_at = None
    apply_identity_roles(db, connector=connector, identity=identity)


def upsert_scim_user(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    payload: dict[str, Any],
    base_url: str,
    replace: bool,
    provisioning_event_id: str | None = None,
) -> tuple[ProvisionedIdentity, dict[str, Any], bool]:
    external_id = _validate_external_id(payload)
    attributes = mapped_user_attributes(connector, payload)
    email = _validate_email(attributes["email"])
    identity = db.scalar(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.connector_id == connector.id,
            ProvisionedIdentity.external_id == external_id,
        )
    )
    created = identity is None
    now = utcnow()
    if identity is None:
        _ensure_email_available(db, email=email, current_user_id=None)
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=connector.tenant_id,
            role_id=None,
            manager_id=None,
            email=email,
            full_name=attributes["full_name"] or email,
            position=attributes["position"],
            department=attributes["department"],
            location=attributes["location"],
            cost_center=attributes["cost_center"],
            phone=attributes["phone"],
            employee_number=attributes["employee_number"],
            identity_source=connector.provider_type,
            provisioning_state="ACTIVE",
            password_hash=hash_password(secrets.token_urlsafe(64)),
            is_active=True,
            is_superuser=False,
            is_root=False,
            deactivated_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()
        identity = ProvisionedIdentity(
            id=str(uuid.uuid4()),
            tenant_id=connector.tenant_id,
            connector_id=connector.id,
            user_id=user.id,
            external_id=external_id,
            user_name=email,
            lifecycle_state="ACTIVE",
            manager_external_id=attributes["manager_external_id"],
            attributes_json=payload,
            scim_version=1,
            last_synced_at=now,
            deprovisioned_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(identity)
        db.flush()
        apply_identity_roles(db, connector=connector, identity=identity)
        log_audit(
            db,
            action="identity_joiner_provisioned",
            entity_type="provisioned_identity",
            entity_id=identity.id,
            actor_email="scim@sbs.local",
            tenant_id=connector.tenant_id,
            metadata={
                "connector_id": connector.id,
                "external_id": external_id,
                "user_id": user.id,
                "provisioning_event_id": provisioning_event_id,
            },
        )
    else:
        user = db.get(User, identity.user_id)
        if user is None:
            raise ScimProvisioningError(
                409,
                "Provisioned identity points to a missing user",
                scim_type="mutability",
            )
        _ensure_email_available(db, email=email, current_user_id=user.id)
        previous_email = user.email
        user.email = email
        user.full_name = attributes["full_name"] or user.full_name
        fields = (
            "position",
            "department",
            "location",
            "cost_center",
            "phone",
            "employee_number",
        )
        for field_name in fields:
            value = attributes[field_name]
            if replace or value is not None:
                setattr(user, field_name, value)
        user.updated_at = now
        identity.user_name = email
        identity.manager_external_id = attributes["manager_external_id"]
        identity.attributes_json = payload
        identity.last_synced_at = now
        identity.updated_at = now
        identity.scim_version += 1
        synchronized_references = synchronize_user_display_references(
            db,
            user=user,
            previous_email=previous_email,
        )
        log_audit(
            db,
            action="identity_mover_updated",
            entity_type="provisioned_identity",
            entity_id=identity.id,
            actor_email="scim@sbs.local",
            tenant_id=connector.tenant_id,
            metadata={
                "connector_id": connector.id,
                "external_id": external_id,
                "user_id": user.id,
                "synchronized_references": synchronized_references,
                "provisioning_event_id": provisioning_event_id,
            },
        )

    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise ScimProvisioningError(
            400,
            "active must be a boolean",
            scim_type="invalidValue",
        )
    if active:
        _activate_identity(
            db,
            connector=connector,
            identity=identity,
            user=user,
        )
        resolve_identity_manager(db, connector=connector, identity=identity)
        resolve_pending_reports(
            db,
            connector=connector,
            manager_identity=identity,
        )
    elif identity.lifecycle_state != "DEPROVISIONED":
        try:
            deactivate_provisioned_user(
                db,
                connector=connector,
                identity=identity,
                reason="SCIM active=false",
                provisioning_event_id=provisioning_event_id,
            )
        except IdentityLifecycleError as exc:
            raise ScimProvisioningError(
                409,
                exc.message,
                scim_type="invalidValue",
            ) from exc
    db.flush()
    return identity, scim_user_resource(db, identity, base_url=base_url), created


def deactivate_scim_user(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    identity: ProvisionedIdentity,
    provisioning_event_id: str | None = None,
) -> None:
    if identity.lifecycle_state == "DEPROVISIONED":
        return
    try:
        deactivate_provisioned_user(
            db,
            connector=connector,
            identity=identity,
            reason="SCIM DELETE",
            provisioning_event_id=provisioning_event_id,
        )
    except IdentityLifecycleError as exc:
        raise ScimProvisioningError(
            409,
            exc.message,
            scim_type="invalidValue",
        ) from exc
    db.flush()


def apply_user_patch(
    current: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = json.loads(json.dumps(current, default=str))
    for operation in operations:
        op_name = str(operation.get("op") or "").lower()
        path = str(operation.get("path") or "").strip()
        value = operation.get("value")
        if op_name not in {"add", "replace", "remove"}:
            raise ScimProvisioningError(400, "Unsupported PATCH operation", scim_type="invalidSyntax")
        if not path and isinstance(value, dict) and op_name in {"add", "replace"}:
            payload.update(value)
            continue
        normalized = path.lower()
        if normalized in {"active", "username", "displayname", "title", "externalid"}:
            canonical = {
                "active": "active",
                "username": "userName",
                "displayname": "displayName",
                "title": "title",
                "externalid": "externalId",
            }[normalized]
            if canonical == "externalId" and op_name == "remove":
                raise ScimProvisioningError(
                    400,
                    "externalId is immutable",
                    scim_type="mutability",
                )
            payload[canonical] = None if op_name == "remove" else value
            continue
        enterprise_prefix = f"{SCIM_ENTERPRISE_USER.lower()}:"
        if normalized.startswith(enterprise_prefix):
            subpath = path[len(SCIM_ENTERPRISE_USER) + 1 :]
            enterprise = payload.setdefault(SCIM_ENTERPRISE_USER, {})
            if not isinstance(enterprise, dict):
                enterprise = {}
                payload[SCIM_ENTERPRISE_USER] = enterprise
            if subpath.lower() == "manager":
                subpath = "manager.value"
            target = enterprise
            pieces = subpath.split(".")
            for piece in pieces[:-1]:
                child = target.setdefault(piece, {})
                if not isinstance(child, dict):
                    child = {}
                    target[piece] = child
                target = child
            if op_name == "remove":
                target.pop(pieces[-1], None)
            else:
                target[pieces[-1]] = value
            continue
        if normalized in {"name", "emails", "phonenumbers", "addresses"}:
            if op_name == "remove":
                payload.pop(path, None)
            else:
                payload[path] = value
            continue
        raise ScimProvisioningError(
            400,
            f"Unsupported PATCH path: {path}",
            scim_type="invalidPath",
        )
    return payload


def _identity_from_member_value(
    db: Session,
    *,
    connector_id: str,
    value: str,
) -> ProvisionedIdentity | None:
    return db.scalar(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.connector_id == connector_id,
            or_(
                ProvisionedIdentity.id == value,
                ProvisionedIdentity.external_id == value,
            ),
        )
    )


def replace_group_members(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    group: ProvisionedGroup,
    members: object,
) -> list[ProvisionedIdentity]:
    if members is None:
        members = []
    if not isinstance(members, list):
        raise ScimProvisioningError(
            400,
            "members must be an array",
            scim_type="invalidValue",
        )
    identities: list[ProvisionedIdentity] = []
    seen: set[str] = set()
    for item in members:
        if not isinstance(item, dict):
            raise ScimProvisioningError(
                400,
                "Each group member must be an object",
                scim_type="invalidValue",
            )
        value = _text(item.get("value"), max_length=255)
        identity = (
            _identity_from_member_value(
                db,
                connector_id=connector.id,
                value=value,
            )
            if value
            else None
        )
        if identity is None:
            raise ScimProvisioningError(
                400,
                f"Unknown group member: {value or '<empty>'}",
                scim_type="invalidValue",
            )
        if identity.id not in seen:
            identities.append(identity)
            seen.add(identity.id)

    previous = db.scalars(
        select(ProvisionedGroupMember).where(
            ProvisionedGroupMember.group_id == group.id
        )
    ).all()
    affected_ids = {item.identity_id for item in previous} | seen
    for item in previous:
        db.delete(item)
    db.flush()
    for identity in identities:
        db.add(
            ProvisionedGroupMember(
                id=str(uuid.uuid4()),
                tenant_id=connector.tenant_id,
                group_id=group.id,
                identity_id=identity.id,
                created_at=utcnow(),
            )
        )
    db.flush()
    affected = db.scalars(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.id.in_(affected_ids)
        )
    ).all() if affected_ids else []
    for identity in affected:
        if identity.lifecycle_state == "ACTIVE":
            apply_identity_roles(db, connector=connector, identity=identity)
    return identities


def upsert_scim_group(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    payload: dict[str, Any],
    base_url: str,
    replace: bool,
    provisioning_event_id: str | None = None,
) -> tuple[ProvisionedGroup, dict[str, Any], bool]:
    external_id = _validate_external_id(payload)
    display_name = _text(payload.get("displayName"), max_length=255)
    if not display_name:
        raise ScimProvisioningError(
            400,
            "displayName is required",
            scim_type="invalidValue",
        )
    group = db.scalar(
        select(ProvisionedGroup).where(
            ProvisionedGroup.connector_id == connector.id,
            ProvisionedGroup.external_id == external_id,
        )
    )
    now = utcnow()
    created = group is None
    if group is None:
        group = ProvisionedGroup(
            id=str(uuid.uuid4()),
            tenant_id=connector.tenant_id,
            connector_id=connector.id,
            external_id=external_id,
            display_name=display_name,
            mapped_role_id=None,
            is_active=True,
            scim_version=1,
            last_synced_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        db.flush()
    else:
        group.display_name = display_name
        group.is_active = True
        group.scim_version += 1
        group.last_synced_at = now
        group.updated_at = now
    if replace or "members" in payload:
        replace_group_members(
            db,
            connector=connector,
            group=group,
            members=payload.get("members", []),
        )
    log_audit(
        db,
        action="identity_group_provisioned" if created else "identity_group_updated",
        entity_type="provisioned_group",
        entity_id=group.id,
        actor_email="scim@sbs.local",
        tenant_id=connector.tenant_id,
        metadata={
            "connector_id": connector.id,
            "external_id": external_id,
            "provisioning_event_id": provisioning_event_id,
        },
    )
    db.flush()
    return group, scim_group_resource(db, group, base_url=base_url), created


def delete_scim_group(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    group: ProvisionedGroup,
    provisioning_event_id: str | None = None,
) -> None:
    previous = db.scalars(
        select(ProvisionedGroupMember).where(
            ProvisionedGroupMember.group_id == group.id
        )
    ).all()
    affected_ids = {item.identity_id for item in previous}
    for item in previous:
        db.delete(item)
    group.is_active = False
    group.scim_version += 1
    group.last_synced_at = utcnow()
    group.updated_at = utcnow()
    db.flush()
    affected = db.scalars(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.id.in_(affected_ids)
        )
    ).all() if affected_ids else []
    for identity in affected:
        if identity.lifecycle_state == "ACTIVE":
            apply_identity_roles(db, connector=connector, identity=identity)
    log_audit(
        db,
        action="identity_group_deprovisioned",
        entity_type="provisioned_group",
        entity_id=group.id,
        actor_email="scim@sbs.local",
        tenant_id=connector.tenant_id,
        metadata={
            "connector_id": connector.id,
            "external_id": group.external_id,
            "provisioning_event_id": provisioning_event_id,
        },
    )


def begin_provisioning_event(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    external_event_id: str,
    resource_type: str,
    operation: str,
    external_id: str | None,
    payload: dict[str, Any],
) -> tuple[IdentityProvisioningEvent, dict[str, Any] | None]:
    payload_hash = canonical_payload_hash(payload)
    existing = db.scalar(
        select(IdentityProvisioningEvent).where(
            IdentityProvisioningEvent.connector_id == connector.id,
            IdentityProvisioningEvent.external_event_id == external_event_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise ScimProvisioningError(
                409,
                "The request identifier was already used with a different payload",
                scim_type="uniqueness",
            )
        if existing.status == "APPLIED" and existing.response_json is not None:
            return existing, existing.response_json
        if existing.status in {"RECEIVED", "RETRY_SCHEDULED"}:
            raise ScimProvisioningError(
                409,
                "The provisioning request is already being processed",
                scim_type="uniqueness",
                retryable=True,
            )
        existing.status = "RECEIVED"
        existing.operation = "RETRY"
        existing.attempts += 1
        existing.error_code = None
        existing.error_message = None
        existing.next_retry_at = None
        existing.updated_at = utcnow()
        return existing, None
    event = IdentityProvisioningEvent(
        id=str(uuid.uuid4()),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
        external_event_id=external_event_id,
        resource_type=resource_type,
        operation=operation,
        external_id=external_id,
        status="RECEIVED",
        payload_hash=payload_hash,
        payload_json=payload,
        response_json=None,
        attempts=1,
        error_code=None,
        error_message=None,
        next_retry_at=None,
        applied_user_id=None,
        completed_at=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event, None


def mark_event_applied(
    event: IdentityProvisioningEvent,
    connector: IdentityProvisioningConnector,
    *,
    response: dict[str, Any],
    applied_user_id: str | None = None,
) -> None:
    now = utcnow()
    event.status = "APPLIED"
    event.response_json = jsonable_encoder(response)
    event.applied_user_id = applied_user_id
    event.completed_at = now
    event.next_retry_at = None
    event.error_code = None
    event.error_message = None
    event.updated_at = now
    connector.success_count += 1
    connector.last_success_at = now
    connector.last_error = None
    connector.updated_at = now


def mark_event_failed(
    event: IdentityProvisioningEvent,
    connector: IdentityProvisioningConnector,
    *,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> None:
    now = utcnow()
    connector.failure_count += 1
    connector.last_failure_at = now
    connector.last_error = error_message[:4_000]
    connector.updated_at = now
    event.error_code = error_code[:80]
    event.error_message = error_message[:20_000]
    event.response_json = None
    event.updated_at = now
    if retryable and event.attempts < connector.retry_max_attempts:
        delay_seconds = min(3_600, 30 * (2 ** max(event.attempts - 1, 0)))
        event.status = "RETRY_SCHEDULED"
        event.next_retry_at = now + timedelta(seconds=delay_seconds)
        event.completed_at = None
    else:
        event.status = "DEAD_LETTER"
        event.next_retry_at = None
        event.completed_at = now


def apply_group_patch(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    group: ProvisionedGroup,
    operations: list[dict[str, Any]],
) -> None:
    current_members = db.scalars(
        select(ProvisionedGroupMember).where(
            ProvisionedGroupMember.group_id == group.id
        )
    ).all()
    by_identity = {item.identity_id: item for item in current_members}
    affected_ids = set(by_identity)
    for operation in operations:
        op_name = str(operation.get("op") or "").lower()
        path = str(operation.get("path") or "").strip()
        value = operation.get("value")
        if op_name not in {"add", "replace", "remove"}:
            raise ScimProvisioningError(
                400,
                "Unsupported PATCH operation",
                scim_type="invalidSyntax",
            )
        if path.lower() == "displayname":
            if op_name == "remove":
                raise ScimProvisioningError(
                    400,
                    "displayName cannot be removed",
                    scim_type="mutability",
                )
            display_name = _text(value, max_length=255)
            if not display_name:
                raise ScimProvisioningError(
                    400,
                    "displayName cannot be empty",
                    scim_type="invalidValue",
                )
            group.display_name = display_name
            continue
        member_filter_match = GROUP_MEMBER_FILTER_RE.match(path)
        if path.lower().startswith("members") or (
            not path and isinstance(value, dict) and "members" in value
        ):
            supplied = value.get("members") if not path and isinstance(value, dict) else value
            if member_filter_match and op_name == "remove" and supplied is None:
                supplied = {"value": member_filter_match.group(1)}
            member_items = supplied if isinstance(supplied, list) else [supplied]
            resolved: list[ProvisionedIdentity] = []
            for item in member_items:
                if not isinstance(item, dict):
                    raise ScimProvisioningError(
                        400,
                        "Group member must be an object",
                        scim_type="invalidValue",
                    )
                member_value = _text(item.get("value"), max_length=255)
                identity = (
                    _identity_from_member_value(
                        db,
                        connector_id=connector.id,
                        value=member_value,
                    )
                    if member_value
                    else None
                )
                if identity is None:
                    raise ScimProvisioningError(
                        400,
                        f"Unknown group member: {member_value or '<empty>'}",
                        scim_type="invalidValue",
                    )
                resolved.append(identity)
                affected_ids.add(identity.id)
            if op_name == "replace":
                replace_group_members(
                    db,
                    connector=connector,
                    group=group,
                    members=[{"value": item.id} for item in resolved],
                )
                by_identity = {
                    item.identity_id: item
                    for item in db.scalars(
                        select(ProvisionedGroupMember).where(
                            ProvisionedGroupMember.group_id == group.id
                        )
                    ).all()
                }
            elif op_name == "add":
                for identity in resolved:
                    if identity.id not in by_identity:
                        member = ProvisionedGroupMember(
                            id=str(uuid.uuid4()),
                            tenant_id=connector.tenant_id,
                            group_id=group.id,
                            identity_id=identity.id,
                            created_at=utcnow(),
                        )
                        db.add(member)
                        by_identity[identity.id] = member
            else:
                for identity in resolved:
                    member = by_identity.pop(identity.id, None)
                    if member is not None:
                        db.delete(member)
            continue
        raise ScimProvisioningError(
            400,
            f"Unsupported PATCH path: {path}",
            scim_type="invalidPath",
        )
    db.flush()
    affected_ids.update(by_identity)
    for identity_id in affected_ids:
        identity = db.get(ProvisionedIdentity, identity_id)
        if identity is not None and identity.lifecycle_state == "ACTIVE":
            apply_identity_roles(db, connector=connector, identity=identity)
    group.scim_version += 1
    group.last_synced_at = utcnow()
    group.updated_at = utcnow()


def replay_provisioning_event(
    db: Session,
    *,
    event: IdentityProvisioningEvent,
    connector: IdentityProvisioningConnector,
    base_url: str,
) -> dict[str, Any]:
    wrapper = event.payload_json or {}
    body = wrapper.get("body")
    resource_id = _text(wrapper.get("resource_id"), max_length=255)
    original_operation = str(wrapper.get("operation") or event.operation).upper()
    if not isinstance(body, dict):
        body = {}
    if event.resource_type == "User":
        if original_operation in {"CREATE", "REPLACE"}:
            identity, response, _ = upsert_scim_user(
                db,
                connector=connector,
                payload=body,
                base_url=base_url,
                replace=original_operation == "REPLACE",
                provisioning_event_id=event.id,
            )
            event.applied_user_id = identity.user_id
            return response
        identity = db.scalar(
            select(ProvisionedIdentity).where(
                ProvisionedIdentity.connector_id == connector.id,
                ProvisionedIdentity.id == resource_id,
            )
        )
        if identity is None:
            raise ScimProvisioningError(404, "User not found")
        if original_operation == "PATCH":
            operations = body.get("Operations")
            if not isinstance(operations, list):
                raise ScimProvisioningError(400, "Operations must be an array")
            current = scim_user_resource(db, identity, base_url=base_url)
            patched = apply_user_patch(current, operations)
            patched["externalId"] = identity.external_id
            _, response, _ = upsert_scim_user(
                db,
                connector=connector,
                payload=patched,
                base_url=base_url,
                replace=False,
                provisioning_event_id=event.id,
            )
            event.applied_user_id = identity.user_id
            return response
        if original_operation == "DELETE":
            deactivate_scim_user(
                db,
                connector=connector,
                identity=identity,
                provisioning_event_id=event.id,
            )
            event.applied_user_id = identity.user_id
            return {"deleted": True, "id": identity.id}
    elif event.resource_type == "Group":
        if original_operation in {"CREATE", "REPLACE"}:
            _, response, _ = upsert_scim_group(
                db,
                connector=connector,
                payload=body,
                base_url=base_url,
                replace=original_operation == "REPLACE",
                provisioning_event_id=event.id,
            )
            return response
        group = db.scalar(
            select(ProvisionedGroup).where(
                ProvisionedGroup.connector_id == connector.id,
                ProvisionedGroup.id == resource_id,
            )
        )
        if group is None:
            raise ScimProvisioningError(404, "Group not found")
        if original_operation == "PATCH":
            operations = body.get("Operations")
            if not isinstance(operations, list):
                raise ScimProvisioningError(400, "Operations must be an array")
            apply_group_patch(
                db,
                connector=connector,
                group=group,
                operations=operations,
            )
            return scim_group_resource(db, group, base_url=base_url)
        if original_operation == "DELETE":
            delete_scim_group(
                db,
                connector=connector,
                group=group,
                provisioning_event_id=event.id,
            )
            return {"deleted": True, "id": group.id}
    raise ScimProvisioningError(
        400,
        "Provisioning event cannot be replayed",
        scim_type="invalidSyntax",
    )


def process_due_provisioning_retries(
    db: Session,
    *,
    base_url: str,
    limit: int = 50,
) -> dict[str, int]:
    now = datetime.now(UTC)
    events = db.scalars(
        select(IdentityProvisioningEvent)
        .where(
            IdentityProvisioningEvent.status == "RETRY_SCHEDULED",
            IdentityProvisioningEvent.next_retry_at <= now,
        )
        .order_by(IdentityProvisioningEvent.next_retry_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    result = {"processed": 0, "applied": 0, "rescheduled": 0, "dead_letter": 0}
    for event in events:
        connector = db.get(IdentityProvisioningConnector, event.connector_id)
        if connector is None or connector.status != "ACTIVE":
            if connector is not None:
                event.attempts += 1
                mark_event_failed(
                    event,
                    connector,
                    error_code="CONNECTOR_INACTIVE",
                    error_message="Connector is not active",
                    retryable=True,
                )
            result["processed"] += 1
            result["rescheduled"] += 1
            continue
        event.status = "RECEIVED"
        event.attempts += 1
        try:
            with db.begin_nested():
                response = replay_provisioning_event(
                    db,
                    event=event,
                    connector=connector,
                    base_url=base_url,
                )
            mark_event_applied(
                event,
                connector,
                response=response,
                applied_user_id=event.applied_user_id,
            )
            result["applied"] += 1
        except (ScimProvisioningError, IntegrityError) as exc:
            detail = exc.detail if isinstance(exc, ScimProvisioningError) else str(exc)
            retryable = (
                exc.retryable if isinstance(exc, ScimProvisioningError) else True
            )
            mark_event_failed(
                event,
                connector,
                error_code=type(exc).__name__,
                error_message=detail,
                retryable=retryable,
            )
            result[
                "rescheduled"
                if event.status == "RETRY_SCHEDULED"
                else "dead_letter"
            ] += 1
        result["processed"] += 1
    return result
