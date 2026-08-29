from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.configuration_center import ConfigurationSettingRevision
from app.models.system_setting import SystemSetting


SettingType = Literal["boolean", "integer"]


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    domain: str
    label: str
    description: str
    value_type: SettingType
    default: bool | int
    minimum: int | None = None
    maximum: int | None = None


SETTING_CATALOG: dict[str, SettingSpec] = {
    item.key: item
    for item in (
        SettingSpec(
            "password_min_length",
            "security",
            "Минимальная длина пароля",
            "Применяется при создании и сбросе локальных паролей.",
            "integer",
            10,
            10,
            128,
        ),
        SettingSpec(
            "session_timeout_minutes",
            "security",
            "Тайм-аут бездействия",
            "Через сколько минут неактивная сессия требует повторного входа.",
            "integer",
            60,
            5,
            1440,
        ),
        SettingSpec(
            "audit_retention_days",
            "security",
            "Хранение audit trail",
            "Минимальный период хранения операционного журнала.",
            "integer",
            180,
            30,
            2555,
        ),
        SettingSpec(
            "sla_warning_threshold",
            "service_management",
            "Предупреждение SLA",
            "За сколько минут до breach показать предупреждение оператору.",
            "integer",
            30,
            1,
            10080,
        ),
        SettingSpec(
            "knowledge_publication_required",
            "service_management",
            "Approval публикации знаний",
            "Не публиковать статью без явного процесса review.",
            "boolean",
            True,
        ),
        SettingSpec(
            "ai_copilot_enabled",
            "ai",
            "AI Copilot",
            "Показывать tenant-пользователям разрешённые AI-возможности.",
            "boolean",
            True,
        ),
        SettingSpec(
            "email_notifications_enabled",
            "communications",
            "Email-уведомления",
            "Разрешить формирование исходящих email-событий.",
            "boolean",
            True,
        ),
        SettingSpec(
            "mock_email_provider_enabled",
            "communications",
            "Локальный mock email",
            "Использовать безопасную локальную доставку до подключения канала.",
            "boolean",
            True,
        ),
    )
}


class ConfigurationValueError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def value_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def scope_key(tenant_id: str | None) -> str:
    return tenant_id or "global"


def parse_setting_value(spec: SettingSpec, value: object) -> bool | int:
    if spec.value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ConfigurationValueError(f"{spec.label}: ожидается boolean")
    if isinstance(value, bool):
        raise ConfigurationValueError(f"{spec.label}: ожидается целое число")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigurationValueError(
            f"{spec.label}: ожидается целое число"
        ) from exc
    if spec.minimum is not None and parsed < spec.minimum:
        raise ConfigurationValueError(
            f"{spec.label}: значение должно быть не меньше {spec.minimum}"
        )
    if spec.maximum is not None and parsed > spec.maximum:
        raise ConfigurationValueError(
            f"{spec.label}: значение должно быть не больше {spec.maximum}"
        )
    return parsed


def serialize_setting_value(value: bool | int) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def current_revision(
    db: Session,
    *,
    tenant_id: str | None,
    setting_key: str,
) -> int:
    return int(
        db.scalar(
            select(func.max(ConfigurationSettingRevision.revision)).where(
                ConfigurationSettingRevision.scope_key == scope_key(tenant_id),
                ConfigurationSettingRevision.setting_key == setting_key,
            )
        )
        or 0
    )


def effective_setting(
    db: Session,
    *,
    tenant_id: str | None,
    setting_key: str,
) -> tuple[SystemSetting | None, bool]:
    if tenant_id:
        tenant_item = db.scalar(
            select(SystemSetting).where(
                SystemSetting.tenant_id == tenant_id,
                SystemSetting.key == setting_key,
            )
        )
        if tenant_item is not None:
            return tenant_item, False
    global_item = db.scalar(
        select(SystemSetting).where(
            SystemSetting.tenant_id.is_(None),
            SystemSetting.key == setting_key,
        )
    )
    return global_item, bool(tenant_id and global_item is not None)


def typed_setting(
    db: Session,
    *,
    tenant_id: str | None,
    setting_key: str,
) -> dict[str, Any]:
    spec = SETTING_CATALOG[setting_key]
    item, inherited = effective_setting(
        db,
        tenant_id=tenant_id,
        setting_key=setting_key,
    )
    raw_value: object = item.value if item is not None else spec.default
    try:
        value = parse_setting_value(spec, raw_value)
        valid = True
        issue = None
    except ConfigurationValueError as exc:
        value = spec.default
        valid = False
        issue = str(exc)
    return {
        "key": spec.key,
        "domain": spec.domain,
        "label": spec.label,
        "description": spec.description,
        "value_type": spec.value_type,
        "value": value,
        "default_value": spec.default,
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "scope": "global" if tenant_id is None else "tenant",
        "source": (
            "default"
            if item is None
            else "global_inherited"
            if inherited
            else "global"
            if item.tenant_id is None
            else "tenant"
        ),
        "is_inherited": inherited,
        "revision": current_revision(
            db,
            tenant_id=tenant_id,
            setting_key=setting_key,
        ),
        "valid": valid,
        "issue": issue,
        "updated_at": item.updated_at if item is not None else None,
    }
