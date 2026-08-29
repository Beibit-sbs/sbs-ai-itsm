from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.ai_actions import AiActionPolicy
from app.models.ai_runtime_controls import AiDataPolicy, AiUsageBudget
from app.models.configuration_center import ConfigurationSettingRevision
from app.models.email_channel import EmailChannel
from app.models.event_operations import EventSource
from app.models.external_system import ExternalSystem
from app.models.identity_provisioning import IdentityProvisioningConnector
from app.models.localized_content import LocalizedContentVariant
from app.models.role import Role
from app.models.system_setting import SystemSetting
from app.models.teams_collaboration import TeamsConnector
from app.models.tenant import Tenant
from app.models.tenant_experience import TenantExperienceProfile
from app.models.user import User
from app.models.user_mfa import UserMfa
from app.services.ai.provider import _overlay_settings_from_db
from app.services.audit import log_audit
from app.services.configuration_center import (
    SETTING_CATALOG,
    ConfigurationValueError,
    canonical_json,
    current_revision,
    parse_setting_value,
    scope_key,
    serialize_setting_value,
    typed_setting,
    value_digest,
)
from app.services.rbac import is_saas_root, require_permissions


router = APIRouter(prefix="/admin/configuration-center")


class TypedSettingUpdate(BaseModel):
    tenant_id: str | None = None
    expected_revision: int = Field(ge=0)
    value: bool | int | str
    reason: str = Field(min_length=3, max_length=1_000)


class TypedSettingRollback(BaseModel):
    tenant_id: str | None = None
    expected_revision: int = Field(ge=1)
    target_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1_000)


class GuidedCheckResponse(BaseModel):
    code: str
    title: str
    status: Literal[
        "PASS",
        "INFO",
        "WARNING",
        "ACTION_REQUIRED",
        "NOT_APPLICABLE",
    ]
    severity: Literal["critical", "high", "medium", "info"]
    diagnostic: str
    remediation: str
    route: str
    can_manage: bool
    required_permission: str
    safe_default: str
    evidence: dict[str, Any]
    evidence_sha256: str
    runbook: str
    audit_route: str


class ConfigurationDomainResponse(BaseModel):
    code: str
    title: str
    description: str
    scope: Literal["global", "tenant"]
    status: Literal["READY", "DEGRADED", "ACTION_REQUIRED"]
    readiness_percent: int
    configured_items: int
    required_items: int
    issues: list[str]
    route: str
    can_manage: bool
    supports_test: bool
    supports_rollback: bool
    updated_at: datetime | None
    checks: list[GuidedCheckResponse]
    owner_roles: list[str]
    runbook: str | None
    safe_default: str | None
    evidence_sha256: str


class TypedSettingResponse(BaseModel):
    key: str
    domain: str
    label: str
    description: str
    value_type: Literal["boolean", "integer"]
    value: bool | int
    default_value: bool | int
    minimum: int | None
    maximum: int | None
    scope: Literal["global", "tenant"]
    source: Literal["default", "global", "global_inherited", "tenant"]
    is_inherited: bool
    revision: int
    valid: bool
    issue: str | None
    updated_at: datetime | None


class GuidedNextActionResponse(BaseModel):
    domain_code: str
    domain_title: str
    check_code: str
    title: str
    status: str
    severity: str
    diagnostic: str
    remediation: str
    route: str
    can_manage: bool
    required_permission: str
    runbook: str
    audit_route: str
    evidence_sha256: str


class ConfigurationScopeResponse(BaseModel):
    type: Literal["global", "tenant"]
    tenant_id: str | None
    label: str


class ConfigurationOverallResponse(BaseModel):
    status: Literal["READY", "DEGRADED", "ACTION_REQUIRED"]
    readiness_percent: int
    ready_domains: int
    total_domains: int
    issues: list[str]


class AdministrationGuideResponse(BaseModel):
    version: str
    generated_at: datetime
    operator_role: str
    next_actions: list[GuidedNextActionResponse]
    total_checks: int
    action_required_checks: int
    warning_checks: int


class SecretStorageResponse(BaseModel):
    strategy: str
    plaintext_returned: bool
    global_provider_root_only: bool


class ConfigurationCenterResponse(BaseModel):
    scope: ConfigurationScopeResponse
    overall: ConfigurationOverallResponse
    domains: list[ConfigurationDomainResponse]
    settings: list[TypedSettingResponse]
    guide: AdministrationGuideResponse
    secret_storage: SecretStorageResponse


def _tenant(
    db: Session,
    user: AuthUserResponse,
    requested: str | None,
) -> str | None:
    if not is_saas_root(user):
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant scope is required")
        if requested and requested != user.tenant_id:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return user.tenant_id
    if requested and db.get(Tenant, requested) is None:
        raise HTTPException(status_code=422, detail="A valid tenant_id is required")
    return requested


def _has_permission(user: AuthUserResponse, permission: str) -> bool:
    return is_saas_root(user) or permission in set(user.permissions)


def _audit(
    db: Session,
    request: Request,
    user: AuthUserResponse,
    *,
    action: str,
    entity_id: str,
    tenant_id: str | None,
    metadata: dict[str, object],
) -> None:
    log_audit(
        db,
        action=action,
        entity_type="configuration_setting",
        entity_id=entity_id,
        actor_user=db.get(User, user.id),
        actor_email=user.email,
        tenant_id=tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,
    )


def _domain(
    *,
    code: str,
    title: str,
    description: str,
    scope: str,
    configured: int,
    required: int,
    issues: list[str],
    route: str,
    can_manage: bool,
    supports_test: bool = False,
    supports_rollback: bool = False,
    updated_at: datetime | None = None,
    checks: list[dict[str, Any]] | None = None,
    owner_roles: list[str] | None = None,
    runbook: str | None = None,
    safe_default: str | None = None,
) -> dict[str, Any]:
    if checks is not None:
        applicable = [
            item for item in checks if item["status"] != "NOT_APPLICABLE"
        ]
        configured = sum(
            item["status"] in {"PASS", "INFO"} for item in applicable
        )
        required = len(applicable)
        issues = [
            item["diagnostic"]
            for item in applicable
            if item["status"] in {"ACTION_REQUIRED", "WARNING"}
        ]
    percentage = 100 if required == 0 else round(configured / required * 100)
    if checks and any(item["status"] == "ACTION_REQUIRED" for item in checks):
        status = "ACTION_REQUIRED"
    elif checks and any(item["status"] == "WARNING" for item in checks):
        status = "DEGRADED"
    elif issues:
        status = "ACTION_REQUIRED" if configured == 0 else "DEGRADED"
    else:
        status = "READY"
    return {
        "code": code,
        "title": title,
        "description": description,
        "scope": scope,
        "status": status,
        "readiness_percent": max(0, min(100, percentage)),
        "configured_items": configured,
        "required_items": required,
        "issues": issues,
        "route": route,
        "can_manage": can_manage,
        "supports_test": supports_test,
        "supports_rollback": supports_rollback,
        "updated_at": updated_at,
        "checks": checks or [],
        "owner_roles": owner_roles or [],
        "runbook": runbook,
        "safe_default": safe_default,
    }


def _guidance_check(
    *,
    code: str,
    title: str,
    check_status: str,
    severity: str,
    diagnostic: str,
    remediation: str,
    route: str,
    can_manage: bool,
    required_permission: str,
    safe_default: str,
    evidence: dict[str, object],
    runbook: str,
) -> dict[str, Any]:
    normalized_evidence = json.loads(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    )
    evidence_json = json.dumps(
        normalized_evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "code": code,
        "title": title,
        "status": check_status,
        "severity": severity,
        "diagnostic": diagnostic,
        "remediation": remediation,
        "route": route,
        "can_manage": can_manage,
        "required_permission": required_permission,
        "safe_default": safe_default,
        "evidence": normalized_evidence,
        "evidence_sha256": hashlib.sha256(
            evidence_json.encode("utf-8")
        ).hexdigest(),
        "runbook": runbook,
        "audit_route": "/admin?tab=audit",
    }


def _count(
    db: Session,
    model,
    tenant_id: str,
    *conditions,
) -> int:
    return int(
        db.scalar(
            select(func.count(model.id)).where(
                model.tenant_id == tenant_id,
                *conditions,
            )
        )
        or 0
    )


@router.get("", response_model=ConfigurationCenterResponse)
def configuration_center(
    http_response: Response,
    tenant_id: str | None = Query(default=None),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationCenterResponse:
    require_permissions(user, "admin.configuration.read")
    target_tenant = _tenant(db, user, tenant_id)
    scope_label = "global" if target_tenant is None else "tenant"
    settings = [
        typed_setting(db, tenant_id=target_tenant, setting_key=key)
        for key in SETTING_CATALOG
    ]
    invalid_settings = [
        f"{item['label']}: {item['issue']}"
        for item in settings
        if not item["valid"]
    ]
    can_manage = _has_permission(user, "admin.configuration.manage")
    can_manage_global = is_saas_root(user)
    latest_setting_update = max(
        (item["updated_at"] for item in settings if item["updated_at"]),
        default=None,
    )
    platform_checks = [
        _guidance_check(
            code=f"setting.{item['key']}",
            title=item["label"],
            check_status="PASS" if item["valid"] else "ACTION_REQUIRED",
            severity="high" if not item["valid"] else "info",
            diagnostic=(
                f"Значение валидно; источник {item['source']}, "
                f"revision {item['revision']}."
                if item["valid"]
                else str(item["issue"])
            ),
            remediation=(
                "Проверьте допустимый диапазон, задайте корректное значение "
                "и сохраните его с текущей revision."
            ),
            route="/admin#settings",
            can_manage=can_manage,
            required_permission="admin.configuration.manage",
            safe_default=f"При отсутствии override применяется {item['default_value']!s}.",
            evidence={
                "setting_key": item["key"],
                "source": item["source"],
                "revision": item["revision"],
                "valid": item["valid"],
                "effective_value": item["value"],
            },
            runbook="docs/operations/UNIFIED-CONFIGURATION-CENTER-RUNBOOK.md",
        )
        for item in settings
    ]
    domains = [
        _domain(
            code="platform",
            title="Основные параметры",
            description="Безопасность, SLA, знания, Copilot и уведомления.",
            scope=scope_label,
            configured=len(settings) - len(invalid_settings),
            required=len(settings),
            issues=invalid_settings,
            route="/admin#settings",
            can_manage=can_manage,
            supports_rollback=True,
            updated_at=latest_setting_update,
            checks=platform_checks,
            owner_roles=["Organization Admin", "SaaS Root"],
            runbook="docs/operations/UNIFIED-CONFIGURATION-CENTER-RUNBOOK.md",
            safe_default=(
                "Каталожные значения ограничены серверными типами и диапазонами; "
                "при отсутствии override используются проверенные defaults."
            ),
        )
    ]

    runtime = get_settings()
    _overlay_settings_from_db(runtime)
    provider = (runtime.ai_provider or "mock").lower()
    provider_key_ready = (
        provider == "mock"
        or provider == "openai"
        and bool(runtime.openai_api_key)
        or provider == "gemini"
        and bool(runtime.gemini_api_key)
    )
    ai_global_issues = []
    if not provider_key_ready:
        ai_global_issues.append(f"{provider}: API key не настроен или не расшифрован")
    if not runtime.ai_pii_redaction:
        ai_global_issues.append("PII redaction отключён")
    if provider == "mock":
        ai_global_issues.append("Активен локальный mock provider")
    ai_provider_checks = [
        _guidance_check(
            code="ai.provider.runtime",
            title="Активный AI provider",
            check_status=(
                "WARNING"
                if provider == "mock"
                else "PASS"
                if provider_key_ready
                else "ACTION_REQUIRED"
            ),
            severity=(
                "medium"
                if provider == "mock"
                else "critical"
                if not provider_key_ready
                else "info"
            ),
            diagnostic=(
                "Локальный mock provider не отправляет данные наружу, но не "
                "подходит для production AI."
                if provider == "mock"
                else f"{provider}: credential readiness = {provider_key_ready}."
            ),
            remediation=(
                "SaaS Root выбирает OpenAI или Gemini, сохраняет зашифрованный "
                "ключ и выполняет connection test."
            ),
            route="/admin#settings",
            can_manage=can_manage_global,
            required_permission="admin.settings.update (SaaS Root)",
            safe_default=(
                "Mock provider сохраняет локальность и позволяет отключить "
                "внешнюю передачу данных до утверждения поставщика."
            ),
            evidence={
                "provider": provider,
                "credential_configured": provider_key_ready,
                "credential_plaintext_returned": False,
            },
            runbook="docs/operations/AI-PROVIDER-CONFIGURATION.md",
        ),
        _guidance_check(
            code="ai.provider.pii_redaction",
            title="PII redaction",
            check_status="PASS" if runtime.ai_pii_redaction else "ACTION_REQUIRED",
            severity="critical" if not runtime.ai_pii_redaction else "info",
            diagnostic=(
                "PII redaction включён."
                if runtime.ai_pii_redaction
                else "PII redaction отключён; внешний AI-трафик небезопасен."
            ),
            remediation="Включите PII redaction до активации внешнего provider.",
            route="/admin#settings",
            can_manage=can_manage_global,
            required_permission="admin.settings.update (SaaS Root)",
            safe_default="Redaction должен оставаться включённым.",
            evidence={"pii_redaction_enabled": runtime.ai_pii_redaction},
            runbook="docs/operations/AI-PROVIDER-CONFIGURATION.md",
        ),
    ]
    domains.append(
        _domain(
            code="ai_provider",
            title="AI provider и секреты",
            description="Глобальные OpenAI/Gemini модели, encrypted credentials и connection test.",
            scope="global",
            configured=int(provider_key_ready) + int(runtime.ai_pii_redaction),
            required=2,
            issues=ai_global_issues,
            route="/admin#settings",
            can_manage=can_manage_global,
            supports_test=True,
            checks=ai_provider_checks,
            owner_roles=["SaaS Root", "AI Governance Owner"],
            runbook="docs/operations/AI-PROVIDER-CONFIGURATION.md",
            safe_default=(
                "До утверждения внешнего provider используется локальный mock; "
                "секреты никогда не возвращаются в браузер."
            ),
        )
    )

    if target_tenant:
        experience_profile = db.get(TenantExperienceProfile, target_tenant)
        published_translations = _count(
            db,
            LocalizedContentVariant,
            target_tenant,
            LocalizedContentVariant.status == "PUBLISHED",
        )
        pending_translations = _count(
            db,
            LocalizedContentVariant,
            target_tenant,
            LocalizedContentVariant.status == "IN_REVIEW",
        )
        can_manage_experience = _has_permission(
            user,
            "tenant.experience.manage",
        )
        can_manage_translations = _has_permission(
            user,
            "tenant.translations.manage",
        )
        experience_checks = [
            _guidance_check(
                code="tenant.experience.profile",
                title="Версионированный experience-профиль",
                check_status=(
                    "PASS" if experience_profile is not None else "WARNING"
                ),
                severity="medium" if experience_profile is None else "info",
                diagnostic=(
                    f"Experience revision {experience_profile.revision} опубликован."
                    if experience_profile is not None
                    else "Используется безопасный системный профиль по умолчанию."
                ),
                remediation=(
                    "Опубликуйте первый tenant-профиль после проверки контраста, "
                    "timezone, форматов и терминологии."
                ),
                route="/admin?tab=tenants",
                can_manage=can_manage_experience,
                required_permission="tenant.experience.manage",
                safe_default=(
                    "При отсутствии tenant-профиля применяется встроенная "
                    "контрастная тема ru-RU без внешнего логотипа."
                ),
                evidence={
                    "profile_exists": experience_profile is not None,
                    "revision": (
                        experience_profile.revision
                        if experience_profile is not None
                        else 0
                    ),
                },
                runbook=(
                    "docs/operations/"
                    "TENANT-BRANDING-LOCALIZATION-RUNBOOK.md"
                ),
            ),
            _guidance_check(
                code="tenant.experience.translations",
                title="Очередь управляемых переводов",
                check_status="INFO" if pending_translations else "PASS",
                severity="info",
                diagnostic=(
                    f"На независимом согласовании: {pending_translations}."
                    if pending_translations
                    else "Нет переводов, ожидающих решения."
                ),
                remediation=(
                    "Откройте редактор переводов и завершите независимое "
                    "согласование актуальных версий."
                ),
                route="/admin?tab=tenants",
                can_manage=can_manage_translations,
                required_permission="tenant.translations.publish",
                safe_default=(
                    "Неопубликованный, повреждённый или stale-перевод никогда "
                    "не используется; выполняется fallback на источник."
                ),
                evidence={
                    "published_variants": published_translations,
                    "pending_review": pending_translations,
                },
                runbook=(
                    "docs/operations/"
                    "TENANT-BRANDING-LOCALIZATION-RUNBOOK.md"
                ),
            ),
        ]
        domains.append(
            _domain(
                code="tenant_experience",
                title="Брендинг и локализация",
                description="Логотип, безопасная палитра, locale, timezone и ITSM-терминология.",
                scope="tenant",
                configured=int(experience_profile is not None),
                required=1,
                issues=(
                    []
                    if experience_profile is not None
                    else ["Experience-профиль ещё не опубликован как versioned tenant configuration"]
                ),
                route="/admin?tab=tenants",
                can_manage=can_manage_experience,
                supports_rollback=True,
                updated_at=(
                    experience_profile.updated_at
                    if experience_profile is not None
                    else None
                ),
                checks=experience_checks,
                owner_roles=["Organization Admin", "Knowledge Manager"],
                runbook=(
                    "docs/operations/"
                    "TENANT-BRANDING-LOCALIZATION-RUNBOOK.md"
                ),
                safe_default=(
                    "Встроенная тема и исходный текст остаются активны, пока "
                    "tenant-версия не прошла серверную валидацию."
                ),
            )
        )

        data_policy = db.scalar(
            select(AiDataPolicy).where(AiDataPolicy.tenant_id == target_tenant)
        )
        budget = db.scalar(
            select(AiUsageBudget).where(AiUsageBudget.tenant_id == target_tenant)
        )
        action_policy = db.scalar(
            select(AiActionPolicy).where(AiActionPolicy.tenant_id == target_tenant)
        )
        ai_enabled = bool(
            next(
                item["value"]
                for item in settings
                if item["key"] == "ai_copilot_enabled"
            )
        )
        can_manage_ai_tenant = _has_permission(user, "ai.runtime.manage")
        can_manage_ai_actions = _has_permission(user, "ai.actions.manage")
        ai_tenant_checks = [
            _guidance_check(
                code="ai.tenant.data_policy",
                title="Data and residency policy",
                check_status=(
                    "NOT_APPLICABLE"
                    if not ai_enabled
                    else "PASS"
                    if data_policy is not None
                    else "ACTION_REQUIRED"
                ),
                severity="critical" if ai_enabled and data_policy is None else "info",
                diagnostic=(
                    "AI Copilot отключён для tenant."
                    if not ai_enabled
                    else "Data/residency policy сохранена."
                    if data_policy is not None
                    else "AI включён без утверждённой data/residency policy."
                ),
                remediation="Сохраните allow/deny policy до production AI-вызовов.",
                route="/copilot",
                can_manage=can_manage_ai_tenant,
                required_permission="ai.runtime.manage",
                safe_default="Без policy tenant AI должен оставаться fail-closed.",
                evidence={
                    "ai_enabled": ai_enabled,
                    "policy_exists": data_policy is not None,
                },
                runbook="docs/operations/AI-PRIVACY-FINOPS-RUNBOOK.md",
            ),
            _guidance_check(
                code="ai.tenant.hard_budget",
                title="Hard usage budget",
                check_status=(
                    "NOT_APPLICABLE"
                    if not ai_enabled
                    else "PASS"
                    if budget is not None
                    else "ACTION_REQUIRED"
                ),
                severity="high" if ai_enabled and budget is None else "info",
                diagnostic=(
                    "AI Copilot отключён для tenant."
                    if not ai_enabled
                    else "Hard budget задан."
                    if budget is not None
                    else "AI включён без hard budget."
                ),
                remediation="Задайте период, предупреждение и hard budget.",
                route="/copilot",
                can_manage=can_manage_ai_tenant,
                required_permission="ai.runtime.manage",
                safe_default="При исчерпании hard budget новые AI-вызовы блокируются.",
                evidence={
                    "ai_enabled": ai_enabled,
                    "budget_exists": budget is not None,
                },
                runbook="docs/operations/AI-PRIVACY-FINOPS-RUNBOOK.md",
            ),
            _guidance_check(
                code="ai.tenant.guarded_actions",
                title="Guarded AI actions",
                check_status=(
                    "NOT_APPLICABLE"
                    if not ai_enabled
                    else "PASS"
                    if action_policy is not None
                    else "WARNING"
                ),
                severity=(
                    "medium" if ai_enabled and action_policy is None else "info"
                ),
                diagnostic=(
                    "AI Copilot отключён для tenant."
                    if not ai_enabled
                    else "Guarded-action policy задана."
                    if action_policy is not None
                    else "Политика не задана; действия остаются fail-closed."
                ),
                remediation="Определите разрешённые действия и approval thresholds.",
                route="/copilot",
                can_manage=can_manage_ai_actions,
                required_permission="ai.actions.manage",
                safe_default="Без policy AI не выполняет изменяющие действия.",
                evidence={
                    "ai_enabled": ai_enabled,
                    "action_policy_exists": action_policy is not None,
                },
                runbook="docs/operations/AI-GUARDED-ACTIONS-RUNBOOK.md",
            ),
        ]
        ai_tenant_issues = []
        if data_policy is None:
            ai_tenant_issues.append("Не сохранена data/residency policy")
        if budget is None:
            ai_tenant_issues.append("Не задан hard budget")
        if action_policy is None:
            ai_tenant_issues.append("Guarded actions остаются fail-closed")
        domains.append(
            _domain(
                code="ai_tenant",
                title="Tenant AI governance",
                description="Residency, budget, prompt governance и guarded actions.",
                scope="tenant",
                configured=sum(
                    item is not None for item in (data_policy, budget, action_policy)
                ),
                required=3,
                issues=ai_tenant_issues,
                route="/copilot",
                can_manage=can_manage_ai_tenant,
                checks=ai_tenant_checks,
                owner_roles=["Organization Admin", "AI Governance Owner"],
                runbook="docs/operations/AI-PRIVACY-FINOPS-RUNBOOK.md",
                safe_default=(
                    "Отсутствующие policy, budget или action rules блокируют "
                    "опасные операции вместо неявного разрешения."
                ),
            )
        )

        email_active = _count(
            db, EmailChannel, target_tenant, EmailChannel.status == "ACTIVE"
        )
        teams_active = _count(
            db, TeamsConnector, target_tenant, TeamsConnector.status == "ACTIVE"
        )
        email_enabled = bool(
            next(
                item["value"]
                for item in settings
                if item["key"] == "email_notifications_enabled"
            )
        )
        mock_email_enabled = bool(
            next(
                item["value"]
                for item in settings
                if item["key"] == "mock_email_provider_enabled"
            )
        )
        can_manage_email = _has_permission(user, "email.channel.manage")
        can_manage_teams = _has_permission(user, "teams.connectors.manage")
        communication_checks = [
            _guidance_check(
                code="communications.email_channel",
                title="Production email channel",
                check_status=(
                    "NOT_APPLICABLE"
                    if not email_enabled
                    else "PASS"
                    if email_active
                    else "WARNING"
                    if mock_email_enabled
                    else "ACTION_REQUIRED"
                ),
                severity=(
                    "high"
                    if email_enabled and not email_active and not mock_email_enabled
                    else "medium"
                    if email_enabled and not email_active
                    else "info"
                ),
                diagnostic=(
                    "Email notifications отключены для tenant."
                    if not email_enabled
                    else f"Активных production-каналов: {email_active}."
                    if email_active
                    else "Используется локальная mock-доставка без внешней отправки."
                    if mock_email_enabled
                    else "Email включён, но активного канала доставки нет."
                ),
                remediation=(
                    "Настройте production email connector, проверьте ownership "
                    "и выполните test delivery."
                ),
                route="/email-operations",
                can_manage=can_manage_email,
                required_permission="email.channel.manage",
                safe_default=(
                    "Mock delivery не отправляет сообщения наружу и сохраняет "
                    "локальный журнал до подключения канала."
                ),
                evidence={
                    "notifications_enabled": email_enabled,
                    "active_channels": email_active,
                    "mock_enabled": mock_email_enabled,
                },
                runbook="docs/operations/PRODUCTION-EMAIL-CHANNEL-RUNBOOK.md",
            ),
            _guidance_check(
                code="communications.teams",
                title="Microsoft Teams collaboration",
                check_status="PASS" if teams_active else "NOT_APPLICABLE",
                severity="info",
                diagnostic=(
                    f"Активных Teams connectors: {teams_active}."
                    if teams_active
                    else "Teams не объявлен обязательным каналом для этого tenant."
                ),
                remediation=(
                    "Если Teams выбран основным collaboration stack, настройте "
                    "connector и выполните permission/test checks."
                ),
                route="/teams-collaboration",
                can_manage=can_manage_teams,
                required_permission="teams.connectors.manage",
                safe_default="Отсутствие Teams не включает скрытую внешнюю доставку.",
                evidence={"active_connectors": teams_active},
                runbook=(
                    "docs/operations/"
                    "MICROSOFT-TEAMS-COLLABORATION-RUNBOOK.md"
                ),
            ),
        ]
        communication_issues = []
        if not email_active:
            communication_issues.append("Нет активного production email channel")
        if not teams_active:
            communication_issues.append("Нет активного Teams connector")
        domains.append(
            _domain(
                code="communications",
                title="Email и collaboration",
                description="Inbound/outbound email и Microsoft Teams delivery.",
                scope="tenant",
                configured=int(bool(email_active)) + int(bool(teams_active)),
                required=2,
                issues=communication_issues,
                route="/email-operations",
                can_manage=can_manage_email,
                supports_test=True,
                checks=communication_checks,
                owner_roles=["Messaging Owner", "Organization Admin"],
                runbook="docs/operations/PRODUCTION-EMAIL-CHANNEL-RUNBOOK.md",
                safe_default=(
                    "В local-first режиме mock email удерживает сообщения "
                    "локально; Teams остаётся optional до выбора стека."
                ),
            )
        )

        enabled_sources = _count(
            db, EventSource, target_tenant, EventSource.is_enabled.is_(True)
        )
        systems = _count(db, ExternalSystem, target_tenant)
        healthy_systems = _count(
            db,
            ExternalSystem,
            target_tenant,
            ExternalSystem.is_enabled.is_(True),
            ExternalSystem.health_status == "healthy",
        )
        can_manage_monitoring = _has_permission(
            user,
            "monitoring.connectors.manage",
        )
        can_manage_integrations = _has_permission(user, "integrations.manage")
        operations_checks = [
            _guidance_check(
                code="operations.monitoring_source",
                title="Monitoring event source",
                check_status="PASS" if enabled_sources else "ACTION_REQUIRED",
                severity="high" if not enabled_sources else "info",
                diagnostic=(
                    f"Активных monitoring sources: {enabled_sources}."
                    if enabled_sources
                    else "Нет активного источника событий."
                ),
                remediation=(
                    "Создайте source, ограничьте authentication, выполните test "
                    "intake и только затем активируйте."
                ),
                route="/event-operations",
                can_manage=can_manage_monitoring,
                required_permission="monitoring.connectors.manage",
                safe_default="Неактивный source не принимает неподтверждённые события.",
                evidence={"enabled_sources": enabled_sources},
                runbook=(
                    "docs/operations/"
                    "PRODUCTION-MONITORING-CONNECTORS-RUNBOOK.md"
                ),
            ),
            _guidance_check(
                code="operations.external_system_health",
                title="External systems health",
                check_status=(
                    "NOT_APPLICABLE"
                    if systems == 0
                    else "PASS"
                    if healthy_systems == systems
                    else "ACTION_REQUIRED"
                ),
                severity=(
                    "high"
                    if systems > 0 and healthy_systems < systems
                    else "info"
                ),
                diagnostic=(
                    "Внешние системы ещё не зарегистрированы."
                    if systems == 0
                    else f"Healthy integrations: {healthy_systems} из {systems}."
                ),
                remediation=(
                    "Откройте failing integration, проверьте credential ownership, "
                    "health test и последний error без раскрытия секрета."
                ),
                route="/integrations",
                can_manage=can_manage_integrations,
                required_permission="integrations.manage",
                safe_default="Unhealthy integration не считается готовой.",
                evidence={
                    "configured_systems": systems,
                    "healthy_systems": healthy_systems,
                },
                runbook="docs/operations/INTEGRATION-PLATFORM-RUNBOOK.md",
            ),
        ]
        ops_issues = []
        if not enabled_sources:
            ops_issues.append("Нет активного monitoring source")
        if systems and healthy_systems < systems:
            ops_issues.append("Не все интеграции healthy")
        domains.append(
            _domain(
                code="operations",
                title="Monitoring и интеграции",
                description="Event intake, health checks и внешние системы.",
                scope="tenant",
                configured=int(bool(enabled_sources)) + int(systems == healthy_systems),
                required=2,
                issues=ops_issues,
                route="/event-operations",
                can_manage=can_manage_monitoring,
                supports_test=True,
                checks=operations_checks,
                owner_roles=["Monitoring Owner", "Integration Owner"],
                runbook=(
                    "docs/operations/"
                    "PRODUCTION-MONITORING-CONNECTORS-RUNBOOK.md"
                ),
                safe_default=(
                    "Неактивные источники и unhealthy integrations не получают "
                    "скрытый статус READY."
                ),
            )
        )

        identity_connectors = _count(
            db,
            IdentityProvisioningConnector,
            target_tenant,
            IdentityProvisioningConnector.status == "ACTIVE",
        )
        can_manage_identity = _has_permission(
            user,
            "identity.provisioning.manage",
        )
        identity_applicable = runtime.oidc_enabled or identity_connectors > 0
        identity_checks = [
            _guidance_check(
                code="identity.provisioning_connector",
                title="Provisioning connector",
                check_status=(
                    "NOT_APPLICABLE"
                    if not identity_applicable
                    else "PASS"
                    if identity_connectors
                    else "ACTION_REQUIRED"
                ),
                severity=(
                    "critical"
                    if identity_applicable and not identity_connectors
                    else "info"
                ),
                diagnostic=(
                    "Локальная identity-модель активна; внешний IdP не включён."
                    if not identity_applicable
                    else f"Активных provisioning connectors: {identity_connectors}."
                ),
                remediation=(
                    "После выбора IdP настройте owner, tenant binding, dry-run, "
                    "quarantine и только затем активируйте provisioning."
                ),
                route="/admin?tab=identity",
                can_manage=can_manage_identity,
                required_permission="identity.provisioning.manage",
                safe_default=(
                    "Пока IdP не утверждён, локальные учётные записи не "
                    "синхронизируются с внешним каталогом."
                ),
                evidence={
                    "oidc_enabled": runtime.oidc_enabled,
                    "active_connectors": identity_connectors,
                },
                runbook="docs/operations/ENTERPRISE-IDENTITY-RUNBOOK.md",
            )
        ]
        domains.append(
            _domain(
                code="identity_lifecycle",
                title="Identity lifecycle",
                description="SCIM/Entra provisioning, ownership и deprovisioning.",
                scope="tenant",
                configured=int(bool(identity_connectors)),
                required=1,
                issues=[] if identity_connectors else ["Нет активного provisioning connector"],
                route="/admin#identity",
                can_manage=can_manage_identity,
                supports_test=True,
                checks=identity_checks,
                owner_roles=["Identity Owner", "Security Officer"],
                runbook="docs/operations/ENTERPRISE-IDENTITY-RUNBOOK.md",
                safe_default=(
                    "Внешнее provisioning остаётся выключенным до явного выбора "
                    "IdP и контролируемой активации."
                ),
            )
        )

        privileged_users = int(
            db.scalar(
                select(func.count(func.distinct(User.id)))
                .where(User.tenant_id == target_tenant, User.is_active.is_(True))
                .join(User.roles)
                .where(Role.code.in_(["organization_admin", "security_officer"]))
            )
            or 0
        )
        privileged_mfa_users = int(
            db.scalar(
                select(func.count(func.distinct(User.id)))
                .select_from(User)
                .join(UserMfa, UserMfa.user_id == User.id)
                .join(User.roles)
                .where(
                    User.tenant_id == target_tenant,
                    UserMfa.enabled.is_(True),
                    Role.code.in_(["organization_admin", "security_officer"]),
                )
            )
            or 0
        )
        security_issues = []
        if privileged_users and privileged_mfa_users < privileged_users:
            security_issues.append(
                f"MFA включён у {privileged_mfa_users} из {privileged_users} привилегированных пользователей"
            )
        if not runtime.mfa_enforcement_enabled:
            security_issues.append("MFA enforcement выключен")
        can_manage_security = _has_permission(user, "security.mfa.manage")
        security_checks = [
            _guidance_check(
                code="security.privileged_mfa_coverage",
                title="Privileged MFA coverage",
                check_status=(
                    "PASS"
                    if privileged_mfa_users == privileged_users
                    else "ACTION_REQUIRED"
                ),
                severity=(
                    "critical"
                    if privileged_mfa_users < privileged_users
                    else "info"
                ),
                diagnostic=(
                    f"MFA coverage: {privileged_mfa_users} из "
                    f"{privileged_users} privileged users."
                ),
                remediation=(
                    "Завершите enrollment каждого privileged user и проверьте "
                    "recovery-code ownership."
                ),
                route="/admin?tab=security",
                can_manage=can_manage_security,
                required_permission="security.mfa.manage",
                safe_default=(
                    "Пользователь без завершённого enrollment не считается "
                    "покрытым MFA."
                ),
                evidence={
                    "privileged_users": privileged_users,
                    "mfa_enabled_users": privileged_mfa_users,
                },
                runbook="docs/operations/MFA-RUNBOOK.md",
            ),
            _guidance_check(
                code="security.mfa_enforcement",
                title="MFA enforcement policy",
                check_status=(
                    "PASS" if runtime.mfa_enforcement_enabled else "WARNING"
                ),
                severity=(
                    "high" if not runtime.mfa_enforcement_enabled else "info"
                ),
                diagnostic=(
                    "MFA enforcement включён."
                    if runtime.mfa_enforcement_enabled
                    else "MFA enforcement отключён; local-first lockout protection активна."
                ),
                remediation=(
                    "После enrollment и проверки recovery активируйте enforcement "
                    "для privileged role codes."
                ),
                route="/admin?tab=security",
                can_manage=can_manage_security,
                required_permission="security.mfa.manage",
                safe_default=(
                    "Enforcement включается только после подтверждения recovery, "
                    "чтобы не заблокировать локальную администрацию."
                ),
                evidence={
                    "mfa_enforcement_enabled": runtime.mfa_enforcement_enabled,
                },
                runbook="docs/operations/MFA-RUNBOOK.md",
            ),
        ]
        domains.append(
            _domain(
                code="security",
                title="Security readiness",
                description="MFA, sessions, audit retention и privileged access.",
                scope="tenant",
                configured=int(not security_issues),
                required=1,
                issues=security_issues,
                route="/admin#security",
                can_manage=can_manage_security,
                checks=security_checks,
                owner_roles=["Security Officer", "Organization Admin"],
                runbook="docs/operations/MFA-RUNBOOK.md",
                safe_default=(
                    "Неполное MFA-покрытие явно блокирует READY; enforcement "
                    "включается после доказанного recovery path."
                ),
            )
        )

    for domain in domains:
        evidence_payload = {
            "domain": domain["code"],
            "status": domain["status"],
            "checks": [
                {
                    "code": item["code"],
                    "status": item["status"],
                    "evidence_sha256": item["evidence_sha256"],
                }
                for item in domain["checks"]
            ],
        }
        domain["evidence_sha256"] = hashlib.sha256(
            json.dumps(
                evidence_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    next_actions = [
        {
            "domain_code": domain["code"],
            "domain_title": domain["title"],
            "check_code": item["code"],
            "title": item["title"],
            "status": item["status"],
            "severity": item["severity"],
            "diagnostic": item["diagnostic"],
            "remediation": item["remediation"],
            "route": item["route"],
            "can_manage": item["can_manage"],
            "required_permission": item["required_permission"],
            "runbook": item["runbook"],
            "audit_route": item["audit_route"],
            "evidence_sha256": item["evidence_sha256"],
        }
        for domain in domains
        for item in domain["checks"]
        if item["status"] in {"ACTION_REQUIRED", "WARNING", "INFO"}
    ]
    next_actions.sort(
        key=lambda item: (
            severity_order.get(str(item["severity"]), 9),
            str(item["domain_code"]),
            str(item["check_code"]),
        )
    )
    ready_domains = sum(item["status"] == "READY" for item in domains)
    all_issues = [
        f"{item['title']}: {issue}"
        for item in domains
        for issue in item["issues"]
    ]
    response_evidence = {
        "scope": scope_key(target_tenant),
        "domains": {
            item["code"]: item["evidence_sha256"] for item in domains
        },
        "settings": {
            item["key"]: {
                "revision": item["revision"],
                "valid": item["valid"],
                "source": item["source"],
            }
            for item in settings
        },
        "guide_version": "2026.07.1",
    }
    response_etag = hashlib.sha256(
        json.dumps(
            response_evidence,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    http_response.headers["Cache-Control"] = "private, no-store"
    http_response.headers["ETag"] = f'"{response_etag}"'
    http_response.headers["X-Configuration-Guide-Version"] = "2026.07.1"
    return ConfigurationCenterResponse(
        scope={
            "type": scope_label,
            "tenant_id": target_tenant,
            "label": (
                db.get(Tenant, target_tenant).name
                if target_tenant
                else "Global platform"
            ),
        },
        overall={
            "status": (
                "READY"
                if ready_domains == len(domains)
                else "ACTION_REQUIRED"
                if ready_domains == 0
                else "DEGRADED"
            ),
            "readiness_percent": (
                round(ready_domains / len(domains) * 100) if domains else 100
            ),
            "ready_domains": ready_domains,
            "total_domains": len(domains),
            "issues": all_issues,
        },
        domains=domains,
        settings=settings,
        guide={
            "version": "2026.07.1",
            "generated_at": datetime.now(UTC),
            "operator_role": user.role,
            "next_actions": next_actions,
            "total_checks": sum(len(item["checks"]) for item in domains),
            "action_required_checks": sum(
                check["status"] == "ACTION_REQUIRED"
                for domain in domains
                for check in domain["checks"]
            ),
            "warning_checks": sum(
                check["status"] == "WARNING"
                for domain in domains
                for check in domain["checks"]
            ),
        },
        secret_storage={
            "strategy": "AES-256-GCM envelope using server credential key",
            "plaintext_returned": False,
            "global_provider_root_only": True,
        },
    )


@router.patch("/settings/{setting_key}")
def update_typed_setting(
    setting_key: str,
    payload: TypedSettingUpdate,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "admin.configuration.manage")
    target_tenant = _tenant(db, user, payload.tenant_id)
    spec = SETTING_CATALOG.get(setting_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Configuration setting not found")
    try:
        value = parse_setting_value(spec, payload.value)
    except ConfigurationValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    revision = current_revision(
        db,
        tenant_id=target_tenant,
        setting_key=setting_key,
    )
    if revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration revision conflict")
    previous = typed_setting(
        db,
        tenant_id=target_tenant,
        setting_key=setting_key,
    )
    statement = select(SystemSetting).where(
        SystemSetting.key == setting_key,
        SystemSetting.tenant_id == target_tenant
        if target_tenant
        else SystemSetting.tenant_id.is_(None),
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        item = SystemSetting(
            id=str(uuid.uuid4()),
            tenant_id=target_tenant,
            key=setting_key,
            value=serialize_setting_value(value),
            description=spec.description,
            is_sensitive=False,
        )
        db.add(item)
    else:
        item.value = serialize_setting_value(value)
        item.description = spec.description
        item.is_sensitive = False
        item.updated_at = datetime.now(UTC)
    if revision == 0:
        db.add(
            ConfigurationSettingRevision(
                id=str(uuid.uuid4()),
                tenant_id=target_tenant,
                scope_key=scope_key(target_tenant),
                setting_key=setting_key,
                revision=1,
                value_json=canonical_json(previous["value"]),
                value_sha256=value_digest(previous["value"]),
                changed_by_id=user.id,
                change_reason="Baseline captured before first managed change",
            )
        )
    new_revision = 2 if revision == 0 else revision + 1
    evidence = ConfigurationSettingRevision(
        id=str(uuid.uuid4()),
        tenant_id=target_tenant,
        scope_key=scope_key(target_tenant),
        setting_key=setting_key,
        revision=new_revision,
        value_json=canonical_json(value),
        value_sha256=value_digest(value),
        changed_by_id=user.id,
        change_reason=payload.reason,
    )
    db.add(evidence)
    _audit(
        db,
        request,
        user,
        action="configuration.setting.updated",
        entity_id=item.id,
        tenant_id=target_tenant,
        metadata={
            "setting_key": setting_key,
            "revision": new_revision,
            "value_sha256": evidence.value_sha256,
            "scope": scope_key(target_tenant),
            "reason": payload.reason,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Configuration revision conflict") from exc
    return typed_setting(
        db,
        tenant_id=target_tenant,
        setting_key=setting_key,
    )


@router.get("/settings/{setting_key}/history")
def setting_history(
    setting_key: str,
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_permissions(user, "admin.configuration.read")
    target_tenant = _tenant(db, user, tenant_id)
    if setting_key not in SETTING_CATALOG:
        raise HTTPException(status_code=404, detail="Configuration setting not found")
    items = db.scalars(
        select(ConfigurationSettingRevision)
        .where(
            ConfigurationSettingRevision.scope_key == scope_key(target_tenant),
            ConfigurationSettingRevision.setting_key == setting_key,
        )
        .order_by(ConfigurationSettingRevision.revision.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "setting_key": item.setting_key,
            "revision": item.revision,
            "value": json.loads(item.value_json),
            "value_sha256": item.value_sha256,
            "changed_by_id": item.changed_by_id,
            "change_reason": item.change_reason,
            "rolled_back_from_revision": item.rolled_back_from_revision,
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.post("/settings/{setting_key}/rollback")
def rollback_typed_setting(
    setting_key: str,
    payload: TypedSettingRollback,
    request: Request,
    user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_permissions(user, "admin.configuration.rollback")
    target_tenant = _tenant(db, user, payload.tenant_id)
    spec = SETTING_CATALOG.get(setting_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Configuration setting not found")
    revision = current_revision(
        db,
        tenant_id=target_tenant,
        setting_key=setting_key,
    )
    if revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Configuration revision conflict")
    target = db.scalar(
        select(ConfigurationSettingRevision).where(
            ConfigurationSettingRevision.scope_key == scope_key(target_tenant),
            ConfigurationSettingRevision.setting_key == setting_key,
            ConfigurationSettingRevision.revision == payload.target_revision,
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Target revision not found")
    try:
        value = parse_setting_value(spec, json.loads(target.value_json))
    except (ConfigurationValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="Target revision is invalid") from exc
    item = db.scalar(
        select(SystemSetting).where(
            SystemSetting.key == setting_key,
            SystemSetting.tenant_id == target_tenant
            if target_tenant
            else SystemSetting.tenant_id.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=409, detail="Current setting is unavailable")
    item.value = serialize_setting_value(value)
    item.updated_at = datetime.now(UTC)
    new_revision = revision + 1
    evidence = ConfigurationSettingRevision(
        id=str(uuid.uuid4()),
        tenant_id=target_tenant,
        scope_key=scope_key(target_tenant),
        setting_key=setting_key,
        revision=new_revision,
        value_json=canonical_json(value),
        value_sha256=value_digest(value),
        changed_by_id=user.id,
        change_reason=payload.reason,
        rolled_back_from_revision=payload.target_revision,
    )
    db.add(evidence)
    _audit(
        db,
        request,
        user,
        action="configuration.setting.rolled_back",
        entity_id=item.id,
        tenant_id=target_tenant,
        metadata={
            "setting_key": setting_key,
            "revision": new_revision,
            "rolled_back_from_revision": payload.target_revision,
            "value_sha256": evidence.value_sha256,
            "reason": payload.reason,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Configuration revision conflict") from exc
    return typed_setting(
        db,
        tenant_id=target_tenant,
        setting_key=setting_key,
    )
