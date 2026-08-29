from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_article import KnowledgeArticle
from app.models.localized_content import LocalizedContentVariant
from app.models.notification_template import NotificationTemplate
from app.models.tenant_experience import TenantExperienceProfile
from app.services.tenant_experience import ALLOWED_FORMAT_LOCALES, canonical_json


RESOURCE_KNOWLEDGE = "KNOWLEDGE_ARTICLE"
RESOURCE_NOTIFICATION = "NOTIFICATION_TEMPLATE"
RESOURCE_TYPES = (RESOURCE_KNOWLEDGE, RESOURCE_NOTIFICATION)
TRANSLATION_LOCALES = ALLOWED_FORMAT_LOCALES
PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
UNSAFE_CONTENT_PATTERN = re.compile(
    r"<\s*script|javascript\s*:|on(?:error|load|click)\s*=",
    re.IGNORECASE,
)


class LocalizedContentError(ValueError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_text(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    normalized = str(value).strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise LocalizedContentError(
            f"{field} must contain {minimum}-{maximum} characters"
        )
    if "\x00" in normalized or UNSAFE_CONTENT_PATTERN.search(normalized):
        raise LocalizedContentError(f"{field} contains unsafe active content")
    return normalized


def normalize_resource_type(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in RESOURCE_TYPES:
        raise LocalizedContentError(f"Unsupported resource type: {value}")
    return normalized


def normalize_locale(value: str) -> str:
    normalized = value.strip()
    if normalized not in TRANSLATION_LOCALES:
        raise LocalizedContentError(f"Unsupported locale: {normalized}")
    return normalized


def source_payload(
    db: Session,
    *,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
) -> dict[str, str]:
    normalized_type = normalize_resource_type(resource_type)
    if normalized_type == RESOURCE_KNOWLEDGE:
        item = db.get(KnowledgeArticle, resource_id)
        if item is None or item.tenant_id not in {None, tenant_id}:
            raise LocalizedContentError("Knowledge source not found")
        return {
            "title": item.title,
            "summary": item.summary,
            "content": item.content,
        }
    item = db.get(NotificationTemplate, resource_id)
    if item is None or item.tenant_id not in {None, tenant_id}:
        raise LocalizedContentError("Notification template source not found")
    return {
        "name": item.name,
        "subject_template": item.subject_template,
        "body_template": item.body_template,
    }


def source_evidence(
    db: Session,
    *,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
) -> tuple[dict[str, str], str]:
    source = source_payload(
        db,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return source, digest(source)


def validate_translation_payload(
    resource_type: str,
    payload: object,
    *,
    source: dict[str, str],
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise LocalizedContentError("Translation payload must be an object")
    normalized_type = normalize_resource_type(resource_type)
    if normalized_type == RESOURCE_KNOWLEDGE:
        fields = {
            "title": (2, 255),
            "summary": (2, 5_000),
            "content": (2, 100_000),
        }
    else:
        fields = {
            "name": (2, 255),
            "subject_template": (2, 255),
            "body_template": (2, 20_000),
        }
    if set(payload) != set(fields):
        raise LocalizedContentError(
            f"Translation fields must be exactly: {', '.join(fields)}"
        )
    normalized = {
        key: _safe_text(
            payload[key],
            key,
            minimum=limits[0],
            maximum=limits[1],
        )
        for key, limits in fields.items()
    }
    if normalized_type == RESOURCE_NOTIFICATION:
        source_placeholders = set(
            PLACEHOLDER_PATTERN.findall(
                source["subject_template"] + source["body_template"]
            )
        )
        translation_placeholders = set(
            PLACEHOLDER_PATTERN.findall(
                normalized["subject_template"] + normalized["body_template"]
            )
        )
        if translation_placeholders != source_placeholders:
            missing = sorted(source_placeholders - translation_placeholders)
            unknown = sorted(translation_placeholders - source_placeholders)
            raise LocalizedContentError(
                "Template placeholders must be preserved"
                f"; missing={missing}; unknown={unknown}"
            )
    return normalized


def variant_payload(item: LocalizedContentVariant) -> dict[str, str]:
    parsed = json.loads(item.payload_json)
    if not isinstance(parsed, dict):
        raise LocalizedContentError("Translation payload evidence is invalid")
    return {str(key): str(value) for key, value in parsed.items()}


def variant_integrity(item: LocalizedContentVariant) -> bool:
    return hashlib.sha256(item.payload_json.encode("utf-8")).hexdigest() == (
        item.payload_sha256
    )


def is_source_current(db: Session, item: LocalizedContentVariant) -> bool:
    try:
        _, current_sha256 = source_evidence(
            db,
            tenant_id=item.tenant_id,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
        )
    except LocalizedContentError:
        return False
    return current_sha256 == item.source_sha256


def resolve_localized_payload(
    db: Session,
    *,
    tenant_id: str | None,
    resource_type: str,
    resource_id: str,
    locale: str | None = None,
) -> tuple[dict[str, str] | None, LocalizedContentVariant | None]:
    if tenant_id is None:
        return None, None
    effective_locale = locale or tenant_ui_locale(db, tenant_id)
    if effective_locale not in TRANSLATION_LOCALES:
        return None, None
    item = db.scalar(
        select(LocalizedContentVariant)
        .where(
            LocalizedContentVariant.tenant_id == tenant_id,
            LocalizedContentVariant.resource_type == resource_type,
            LocalizedContentVariant.resource_id == resource_id,
            LocalizedContentVariant.locale == effective_locale,
            LocalizedContentVariant.status == "PUBLISHED",
        )
        .order_by(LocalizedContentVariant.version.desc())
        .limit(1)
    )
    if item is None or not variant_integrity(item) or not is_source_current(db, item):
        return None, item
    source, _ = source_evidence(
        db,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    try:
        return (
            validate_translation_payload(
                resource_type,
                variant_payload(item),
                source=source,
            ),
            item,
        )
    except (LocalizedContentError, json.JSONDecodeError):
        return None, item


def tenant_ui_locale(db: Session, tenant_id: str) -> str:
    profile = db.get(TenantExperienceProfile, tenant_id)
    return profile.ui_locale if profile is not None else "ru-RU"
